"""
Service de routage des lignes de commande.

Fournit la règle de calcul de la destination par défaut d'une ligne (cf. brief
catégories-routage) et l'éclatement unitaire d'une ligne SGI en prestations.

Règle de routage par défaut :
  - ligne dont id_product_category ∈ (16374, 19028) → 'a_planifier'
  - sinon, ligne dont product_category contient "logiciel" (insensible casse
    et accents) → 'contrat'
  - tout le reste, y compris catégorie NULL → 'facturation_directe'

Le test SGI se fait sur l'ID (stable). Le test "logiciel" se fait sur le
libellé (Karlia change parfois la casse / le pluriel) avec normalisation
NFKD + retrait des marques diacritiques avant comparaison.
"""
from __future__ import annotations

import math
import unicodedata
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.models import CommandeLigne, Prestation


# ── Constantes catégories SGI ─────────────────────────────────────────────
CATEGORIE_SGI_FORMATION = 16374
CATEGORIE_SGI_TECHNIQUE = 19028
CATEGORIES_SGI = (CATEGORIE_SGI_FORMATION, CATEGORIE_SGI_TECHNIQUE)

# ── Destinations possibles ────────────────────────────────────────────────
DESTINATION_A_PLANIFIER         = "a_planifier"
DESTINATION_CONTRAT             = "contrat"
DESTINATION_FACTURATION_DIRECTE = "facturation_directe"
DESTINATIONS_VALIDES = (
    DESTINATION_A_PLANIFIER,
    DESTINATION_CONTRAT,
    DESTINATION_FACTURATION_DIRECTE,
)


def _normaliser(s: Optional[str]) -> str:
    """Normalise une chaîne pour comparaison : casse + diacritiques."""
    if not s:
        return ""
    # NFKD pour décomposer les caractères accentués, puis retrait des marques.
    nfkd = unicodedata.normalize("NFKD", s)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sans_accents.lower()


def destination_par_defaut(
    id_product_category: Optional[int],
    product_category: Optional[str],
) -> str:
    """
    Calcule la destination par défaut d'une ligne, selon la règle métier.

    Args:
        id_product_category: ID Karlia de la catégorie (None si pas catégorisée).
        product_category: libellé Karlia de la catégorie (None possible).

    Returns:
        L'une des trois valeurs : 'a_planifier' | 'contrat' | 'facturation_directe'.
    """
    if id_product_category in CATEGORIES_SGI:
        return DESTINATION_A_PLANIFIER
    if "logiciel" in _normaliser(product_category):
        return DESTINATION_CONTRAT
    return DESTINATION_FACTURATION_DIRECTE


def eclater_ligne_en_prestations(
    db: Session,
    ligne: CommandeLigne,
    formateur_id: Optional[int] = None,
) -> List[Prestation]:
    """
    Éclate une ligne de commande en N prestations unitaires (statut 'a_planifier').

    Règle de découpage selon la quantité :
      - Q entier (ou décimal sans partie fractionnaire) → Q prestations de
        duree_jours=1.
      - Q décimal (ex 2.5) → floor(Q) prestations de 1 jour + 1 prestation
        de duree_jours = Q - floor(Q) pour la fraction restante.
        Choix de modélisation : la fraction représente une demi-journée /
        intervention partielle ; on évite d'arrondir à l'unité supérieure
        pour ne pas surfacturer en jours.

    Les prestations sont AJOUTÉES à la session mais PAS commit ici : le
    commit est laissé à l'appelant pour rester en transaction unique sur
    toute la validation d'une commande.

    Args:
        db: session SQLAlchemy ouverte (l'appelant gère le commit/rollback).
        ligne: la CommandeLigne à éclater.
        formateur_id: pré-assignation optionnelle (cas from-commande historique).

    Returns:
        La liste des Prestation créées (objets ORM persistés via db.add).
    """
    quantite_raw = ligne.quantite
    # Tolérance entrée (Decimal/float/int/None). Default 1 si pas de quantité.
    if quantite_raw is None:
        quantite = Decimal("1")
    elif isinstance(quantite_raw, Decimal):
        quantite = quantite_raw
    else:
        quantite = Decimal(str(quantite_raw))

    if quantite <= 0:
        return []

    partie_entiere = int(math.floor(float(quantite)))
    reste = quantite - Decimal(partie_entiere)

    designation_base = ligne.designation or "Prestation"
    description = ligne.description
    created: List[Prestation] = []

    for i in range(partie_entiere):
        p = Prestation(
            commande_id=ligne.commande_id,
            commande_ligne_id=ligne.id,
            formateur_id=formateur_id,
            designation=designation_base if partie_entiere == 1 and reste == 0
                        else f"{designation_base} ({i+1}/{partie_entiere + (1 if reste > 0 else 0)})",
            description=description,
            duree_jours=1,
            statut="a_planifier",
        )
        db.add(p)
        created.append(p)

    if reste > 0:
        # Une dernière prestation porte la fraction restante.
        # duree_jours est un Integer en DB ; on stocke 1 par défaut et on
        # documente la fraction dans la description (pas de décimale possible
        # sur duree_jours en l'état actuel du modèle).
        # NOTE : si à l'avenir duree_jours devient Numeric, mettre `float(reste)`.
        note_fraction = f" [fraction restante : {reste}]"
        p = Prestation(
            commande_id=ligne.commande_id,
            commande_ligne_id=ligne.id,
            formateur_id=formateur_id,
            designation=f"{designation_base} ({partie_entiere + 1}/{partie_entiere + 1})",
            description=(description or "") + note_fraction,
            duree_jours=1,
            statut="a_planifier",
        )
        db.add(p)
        created.append(p)

    return created

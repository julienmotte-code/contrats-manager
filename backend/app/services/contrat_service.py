"""
Service métier — Gestion des contrats
Logique de calcul : prorata, plan de facturation, révision par indice
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict


def calculer_prorata(date_debut: date, montant_annuel_ht: Decimal, demi_mois: bool = False) -> Dict:
    """
    Calcule le prorata de la première année :
    - 1 au 15 : facturation dès ce mois
    - 16 à fin du mois : facturation dès le mois suivant
    - Option demi_mois : ajoute 1/24ème du montant annuel
    """
    if date_debut.month == 1 and date_debut.day == 1 and not demi_mois:
        return {
            "prorate": False,
            "nb_mois": Decimal("12"),
            "montant_ht": montant_annuel_ht,
            "detail": "Début au 1er janvier — année complète, pas de prorata",
        }
    if date_debut.day <= 15:
        mois_debut = date_debut.month
        detail = f"Début le {date_debut.day}/{date_debut.month} (≤15) : facturation dès ce mois"
    else:
        mois_debut = date_debut.month + 1
        detail = f"Début le {date_debut.day}/{date_debut.month} (>15) : facturation dès le mois suivant"
    nb_mois = Decimal(str(13 - mois_debut))
    bonus = (montant_annuel_ht / Decimal("24")).quantize(Decimal("0.01")) if demi_mois else Decimal("0")
    montant_prorate = (montant_annuel_ht * nb_mois / Decimal("12")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ) + bonus
    detail_final = detail + (f" + ½ mois ({bonus} €)" if demi_mois else "")
    return {
        "prorate": True,
        "nb_mois": nb_mois,
        "demi_mois": demi_mois,
        "bonus_demi_mois": float(bonus),
        "montant_ht": montant_prorate,
        "detail": detail_final,
    }

def calculer_nombre_annees(date_debut: date, date_fin: date) -> int:
    """
    Calcule le nombre d'années du contrat.
    Arrondi à l'année supérieure si la fin dépasse l'anniversaire.
    Ex: 01/03/2026 → 31/12/2028 = 3 factures (2026 proraté, 2027, 2028)
    """
    # Nombre d'années civiles couvertes
    return date_fin.year - date_debut.year + 1


def generer_plan_facturation(
    contrat_id: str,
    date_debut: date,
    date_fin: date,
    montant_annuel_ht: Decimal,
    prorata: Dict,
) -> List[Dict]:
    """
    Génère le plan de facturation complet d'un contrat.
    Une facture par année civile, émise le 1er janvier (sauf prorata an1).

    Retourne une liste de dicts :
    [{
        numero_facture, annee_facturation, date_echeance,
        type_facture, montant_ht_prevu, statut
    }]
    """
    plan = []
    annee_debut = date_debut.year
    annee_fin = date_fin.year
    num = 1

    for annee in range(annee_debut, annee_fin + 1):
        if annee == annee_debut and prorata["prorate"]:
            # Facture 1 : proratisée, émise dès le début ou au 1er janvier
            plan.append({
                "contrat_id": contrat_id,
                "numero_facture": num,
                "annee_facturation": annee,
                "date_echeance": date(annee, 1, 1) if date_debut.month == 1 else date_debut,
                "type_facture": "PRORATE",
                "montant_ht_prevu": float(prorata["montant_ht"]),
                "statut": "PLANIFIEE",
            })
        else:
            # Factures suivantes : annuelles au 1er janvier
            plan.append({
                "contrat_id": contrat_id,
                "numero_facture": num,
                "annee_facturation": annee,
                "date_echeance": date(annee, 1, 1),
                "type_facture": "ANNUELLE",
                "montant_ht_prevu": float(montant_annuel_ht),  # Sera révisé à l'émission
                "statut": "PLANIFIEE",
            })
        num += 1

    return plan


def generer_numero_client(nom: str, dernier_numero: int) -> str:
    """
    Génère le numéro client selon la règle :
    3 premiers caractères significatifs du nom (majuscules, sans accents) + incrément 3 chiffres

    Ex: "SARL Dumont" → "DUM" + "048" = "DUM048"
    Ex: "Orange SA" → "ORA" + "049" = "ORA049"

    Args:
        nom: Raison sociale du client
        dernier_numero: Dernier numéro incrémental utilisé dans Karlia

    Returns:
        Numéro client formaté (ex: "DUM048")
    """
    import unicodedata

    # Supprimer les accents
    nfkd = unicodedata.normalize('NFKD', nom)
    sans_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))

    # Supprimer les mots courants en début (articles, formes juridiques)
    mots_a_ignorer = {"le", "la", "les", "l", "de", "du", "des", "sarl", "sas", "sa",
                      "eurl", "sci", "sasu", "snc", "ei", "auto"}
    mots = sans_accents.upper().split()
    mots_significatifs = [m for m in mots if m.lower() not in mots_a_ignorer]

    # Prendre le nom significatif, ou le premier mot si tout est ignoré
    nom_base = mots_significatifs[0] if mots_significatifs else mots[0]

    # 3 premiers caractères alphanumériques
    chars = ''.join(c for c in nom_base if c.isalnum())
    prefix = chars[:3].upper().ljust(3, "X")  # Padder avec X si moins de 3 chars

    # Numéro incrémenté sur 3 chiffres
    nouveau_numero = dernier_numero + 1
    return f"{prefix}{nouveau_numero:03d}"

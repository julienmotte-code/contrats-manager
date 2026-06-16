"""
Routes API — Contrats
GET  /api/contrats                  → Liste avec filtres
POST /api/contrats                  → Création d'un contrat
GET  /api/contrats/{id}             → Détail
PUT  /api/contrats/{id}             → Modification
POST /api/contrats/{id}/valider     → Validation finale (génère le plan de facturation)
POST /api/contrats/{id}/terminer    → Passe en statut TERMINE
GET  /api/contrats/renouvellements  → Contrats à renouveler
POST /api/contrats/{id}/renouveler  → Traite le renouvellement (3 cas)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
import uuid
import logging

from app.core.database import get_db
from app.core.security import require_authenticated, require_role
from app.models.models import Contrat, ContratArticle, PlanFacturation, IndiceRevision, Commande
from app.services.contrat_service import (
    calculer_prorata, calculer_nombre_annees,
    generer_plan_facturation,
)
from app.services.karlia_service import karlia, KarliaError

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schémas ──────────────────────────────────────────────────

class ArticleLigne(BaseModel):
    rang: int  # 0 = principal, 1-7 = annexe
    article_karlia_id: Optional[str] = None
    designation: str
    reference: Optional[str] = None
    prix_unitaire_ht: Optional[float] = None
    quantite: float = 1.0
    unite: Optional[str] = None
    taux_tva: float = 20.0


class ContratCreate(BaseModel):
    numero_contrat: str
    client_karlia_id: str
    client_nom: str
    client_numero: Optional[str] = None
    # Famille de contrat (détermine la règle de révision ET le calcul de durée).
    # Auparavant ABSENT du schéma → le champ envoyé par le front était ignoré
    # par Pydantic et tout contrat retombait sur le défaut modèle 'COSOLUCE'.
    famille_contrat: str = "COSOLUCE"
    date_debut: date
    date_fin: date
    montant_annuel_ht: float
    articles: List[ArticleLigne]
    # Prorata
    prorate_validated: bool = False
    prorate_note: Optional[str] = None
    # Hiérarchie
    type_contrat: str = "CONTRAT"
    contrat_parent_id: Optional[str] = None
    # Indice de référence initial
    indice_reference_id: Optional[str] = None
    # Lien Karlia : opportunité d'origine (commande source). NULL pour renouvellement / saisie sans commande.
    karlia_opportunity_id: Optional[int] = None


class RenouvellementAction(BaseModel):
    type_renouvellement: str  # SPONTANE | NOUVEAU_CONTRAT | FIN
    notes: Optional[str] = None
    # Si NOUVEAU_CONTRAT : données du nouveau contrat (facultatif, sinon copie)
    nouveau_numero: Optional[str] = None
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None


# ── Routes ────────────────────────────────────────────────────

@router.get("")
def lister_contrats(
    statut: Optional[str] = None,
    recherche: Optional[str] = None,
    annee: Optional[int] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    familles: Optional[str] = Query(None, description="Familles séparées par virgule"),
    db: Session = Depends(get_db),
    current_user = Depends(require_authenticated),
):
    """Liste les contrats avec filtres."""
    q = db.query(Contrat)
    if statut and statut != "TOUS":
        q = q.filter(Contrat.statut == statut)
    if recherche:
        q = q.filter(
            or_(
                Contrat.numero_contrat.ilike(f"%{recherche}%"),
                Contrat.client_nom.ilike(f"%{recherche}%"),
                Contrat.client_numero.ilike(f"%{recherche}%"),
            )
        )
    if familles:
        liste_familles = [f.strip().upper() for f in familles.split(",")]
        q = q.filter(Contrat.famille_contrat.in_(liste_familles))
    if annee:
        q = q.filter(Contrat.date_debut <= date(annee, 12, 31))
        q = q.filter(Contrat.date_fin >= date(annee, 1, 1))

    total = q.count()
    contrats = q.order_by(Contrat.date_fin.asc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "data": [_contrat_to_dict(c) for c in contrats],
    }


@router.get("/renouvellements")
def contrats_a_renouveler(
    mois: Optional[int] = Query(None, description="Mois (1-12), défaut = mois en cours"),
    annee: Optional[int] = Query(None, description="Année, défaut = année en cours"),
    famille: Optional[str] = Query(None, description="Famille de contrat (ex: COSOLUCE)"),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    """Liste les contrats dont la date de fin est dans le mois spécifié."""
    aujourd_hui = date.today()
    mois_cible = mois or aujourd_hui.month
    annee_cible = annee or aujourd_hui.year

    # Fenêtre du mois demandé
    debut_mois = date(annee_cible, mois_cible, 1)
    if mois_cible == 12:
        fin_mois = date(annee_cible + 1, 1, 1)
    else:
        fin_mois = date(annee_cible, mois_cible + 1, 1)

    q = db.query(Contrat).filter(
        Contrat.statut.in_(["EN_COURS", "A_RENOUVELER"]),
        Contrat.date_fin >= debut_mois,
        Contrat.date_fin < fin_mois,
    )
    if famille:
        q = q.filter(Contrat.famille_contrat == famille.upper())
    contrats = q.order_by(Contrat.date_fin).all()

    return {
        "mois": mois_cible,
        "annee": annee_cible,
        "total": len(contrats),
        "data": [_contrat_to_dict(c) for c in contrats],
    }


@router.post("")
def creer_contrat(
    data: ContratCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Crée un nouveau contrat en statut BROUILLON.
    Calcule le prorata et génère le plan de facturation prévisionnaire.

    Famille DIVERS : dates et montant libres, AUCUN prorata, AUCUN plan de
    facturation, contrat validable sans étape prorata.
    """
    # Vérifier unicité du numéro
    if db.query(Contrat).filter(Contrat.numero_contrat == data.numero_contrat).first():
        raise HTTPException(400, f"Le numéro de contrat '{data.numero_contrat}' existe déjà")

    # Vérifier cohérence des dates
    if data.date_fin <= data.date_debut:
        raise HTTPException(400, "La date de fin doit être postérieure à la date de début")

    # Calculs
    montant_ht = Decimal(str(data.montant_annuel_ht))
    is_divers = (data.famille_contrat == "DIVERS")
    if is_divers:
        # Prorata neutre : aucun prorata pour la famille DIVERS.
        prorata = {
            "prorate": False,
            "nb_mois": Decimal("12"),
            "montant_ht": montant_ht,
            "detail": "Famille DIVERS — dates et montant libres, aucun prorata",
        }
    else:
        prorata = calculer_prorata(data.date_debut, montant_ht)
    nombre_annees = calculer_nombre_annees(data.date_debut, data.date_fin, data.famille_contrat)

    # Créer le contrat
    contrat = Contrat(
        numero_contrat=data.numero_contrat,
        client_karlia_id=data.client_karlia_id,
        client_nom=data.client_nom,
        client_numero=data.client_numero,
        famille_contrat=data.famille_contrat,
        date_debut=data.date_debut,
        date_fin=data.date_fin,
        nombre_annees=nombre_annees,
        montant_annuel_ht=montant_ht,
        indice_reference_id=uuid.UUID(data.indice_reference_id) if data.indice_reference_id else None,
        prorate_annee1=prorata["prorate"],
        prorate_nb_mois=prorata["nb_mois"],
        prorate_montant_ht=prorata["montant_ht"],
        # DIVERS : jamais de blocage de validation par le prorata.
        prorate_validated=True if is_divers else data.prorate_validated,
        prorate_note=data.prorate_note,
        type_contrat=data.type_contrat,
        contrat_parent_id=uuid.UUID(data.contrat_parent_id) if data.contrat_parent_id else None,
        karlia_opportunity_id=data.karlia_opportunity_id,
        statut="BROUILLON",
    )
    db.add(contrat)
    db.flush()  # Pour avoir l'ID

    # Ajouter les articles
    for art in data.articles:
        db.add(ContratArticle(
            contrat_id=contrat.id,
            rang=art.rang,
            article_karlia_id=art.article_karlia_id,
            designation=art.designation,
            reference=art.reference,
            prix_unitaire_ht=art.prix_unitaire_ht,
            quantite=art.quantite,
            unite=art.unite,
            taux_tva=art.taux_tva,
        ))

    # Générer le plan de facturation — sauf DIVERS (aucune ligne de plan)
    if is_divers:
        plan = []
    else:
        plan = generer_plan_facturation(
            contrat_id=str(contrat.id),
            date_debut=data.date_debut,
            date_fin=data.date_fin,
            montant_annuel_ht=montant_ht,
            prorata=prorata,
        )
        for p in plan:
            db.add(PlanFacturation(
                contrat_id=contrat.id,
                numero_facture=p["numero_facture"],
                annee_facturation=p["annee_facturation"],
                date_echeance=p["date_echeance"],
                type_facture=p["type_facture"],
                montant_ht_prevu=p["montant_ht_prevu"],
                statut="PLANIFIEE",
            ))

    db.commit()
    db.refresh(contrat)

    logger.info(f"Contrat créé : {data.numero_contrat} — {data.client_nom}")
    return {
        **_contrat_to_dict(contrat),
        "prorata_detail": prorata["detail"],
        "plan_facturation": plan,
    }


@router.get("/{contrat_id}")
def obtenir_contrat(
    contrat_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_authenticated),
):
    """Retourne le détail complet d'un contrat avec articles et plan de facturation."""
    contrat = _get_or_404(contrat_id, db)
    d = _contrat_to_dict(contrat)
    d["articles"] = [
        {
            "rang": a.rang,
            "article_karlia_id": a.article_karlia_id,
            "designation": a.designation,
            "reference": a.reference,
            "prix_unitaire_ht": float(a.prix_unitaire_ht) if a.prix_unitaire_ht else None,
            "quantite": float(a.quantite),
            "unite": a.unite,
            "taux_tva": float(a.taux_tva),
        }
        for a in contrat.articles
    ]
    d["plan_facturation"] = [
        {
            "id": str(p.id),
            "numero_facture": p.numero_facture,
            "annee_facturation": p.annee_facturation,
            "date_echeance": p.date_echeance.isoformat(),
            "type_facture": p.type_facture,
            "montant_ht_prevu": float(p.montant_ht_prevu) if p.montant_ht_prevu else None,
            "montant_ht_facture": float(p.montant_ht_facture) if p.montant_ht_facture else None,
            "statut": p.statut,
            "facture_karlia_id": p.facture_karlia_id,
            "facture_karlia_ref": p.facture_karlia_ref,
        }
        for p in contrat.plan_facturation
    ]
    return d


@router.post("/{contrat_id}/valider")
def valider_contrat(
    contrat_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Valide un contrat BROUILLON → EN_COURS.
    Déclenche la génération des documents (asynchrone).
    """
    contrat = _get_or_404(contrat_id, db)
    if contrat.statut != "BROUILLON":
        raise HTTPException(400, f"Seuls les brouillons peuvent être validés (statut actuel: {contrat.statut})")
    if not contrat.articles:
        raise HTTPException(400, "Le contrat doit avoir au moins un article (désignation principale)")
    if not contrat.prorate_validated and contrat.prorate_annee1:
        raise HTTPException(400, "Le prorata de la première année doit être validé avant de finaliser")

    contrat.statut = "EN_COURS"
    contrat.validated_at = datetime.utcnow()
    contrat.date_statut_change = date.today()

    # Liaison best-effort commande↔contrat : toute commande de la même opportunité
    # marquée "nécessite contrat" et non encore liée est rattachée à ce contrat
    # (sort de l'écran "Contrats à créer"). Aligné sur lier_contrat_commande (str).
    nb_commandes_liees = 0
    if contrat.karlia_opportunity_id:
        cmds = db.query(Commande).filter(
            Commande.karlia_opportunity_id == contrat.karlia_opportunity_id,
            Commande.necessite_contrat == True,
            Commande.contrat_id == None,
        ).all()
        for cmd in cmds:
            cmd.contrat_id = str(contrat.id)
            cmd.updated_at = datetime.utcnow()
            nb_commandes_liees += 1

    db.commit()

    return {
        "message": f"Contrat {contrat.numero_contrat} validé — statut EN_COURS",
        "id": contrat_id,
        "nb_commandes_liees": nb_commandes_liees,
    }


@router.delete("/{contrat_id}")
def supprimer_contrat(
    contrat_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Supprime un contrat en statut BROUILLON uniquement."""
    contrat = _get_or_404(contrat_id, db)
    if contrat.statut != "BROUILLON":
        raise HTTPException(400, "Seuls les brouillons peuvent être supprimés")
    db.delete(contrat)
    db.commit()
    return {"message": f"Contrat {contrat.numero_contrat} supprimé"}

@router.put("/{contrat_id}")
def modifier_contrat(
    contrat_id: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Modifie un contrat en statut BROUILLON uniquement.

    Famille DIVERS : aucun prorata, aucun plan de facturation (ni régénération).
    """
    from app.models.models import ContratArticle, PlanFacturation
    contrat = _get_or_404(contrat_id, db)
    if contrat.statut != "BROUILLON":
        raise HTTPException(400, "Seuls les brouillons peuvent être modifiés")

    # Champs simples
    champs = ["numero_contrat", "type_contrat", "client_karlia_id", "client_nom", "client_numero",
              "montant_annuel_ht", "prorate_validated", "prorate_note", "prorate_demi_mois",
              "indice_reference_id", "notes_internes"]
    for champ in champs:
        if champ in data:
            val = data[champ]
            if val == "" : val = None
            setattr(contrat, champ, val)

    # Dates
    if "date_debut" in data and data["date_debut"]:
        from datetime import date as date_type
        contrat.date_debut = date_type.fromisoformat(data["date_debut"])
    if "date_fin" in data and data["date_fin"]:
        from datetime import date as date_type
        contrat.date_fin = date_type.fromisoformat(data["date_fin"])
        contrat.nombre_annees = calculer_nombre_annees(
            contrat.date_debut, contrat.date_fin, contrat.famille_contrat
        )

    is_divers = (contrat.famille_contrat == "DIVERS")

    if is_divers:
        # DIVERS : aucun prorata, jamais de blocage de validation.
        from decimal import Decimal
        contrat.prorate_annee1 = False
        contrat.prorate_montant_ht = Decimal(str(contrat.montant_annuel_ht)) if contrat.montant_annuel_ht is not None else None
        contrat.prorate_validated = True
    else:
        # Recalcul prorata
        if "date_debut" in data or "montant_annuel_ht" in data:
            from app.services.contrat_service import calculer_prorata
            from decimal import Decimal
            prorata = calculer_prorata(
                contrat.date_debut,
                Decimal(str(contrat.montant_annuel_ht)),
                data.get("prorate_demi_mois", contrat.prorate_demi_mois or False)
            )
            contrat.prorate_annee1 = prorata["prorate"]
            if prorata["prorate"]:
                contrat.prorate_nb_mois = float(prorata["nb_mois"])
                contrat.prorate_montant_ht = float(prorata["montant_ht"])

    # Articles — remplacer complètement
    if "articles" in data:
        db.query(ContratArticle).filter(ContratArticle.contrat_id == contrat.id).delete()
        for a in data["articles"]:
            db.add(ContratArticle(
                contrat_id=contrat.id,
                rang=a.get("rang", 0),
                article_karlia_id=a.get("article_karlia_id") or None,
                designation=a.get("designation", ""),
                prix_unitaire_ht=a.get("prix_unitaire_ht"),
                quantite=a.get("quantite", 1),
                taux_tva=a.get("taux_tva", 20),
            ))

    # Regénérer plan de facturation — sauf DIVERS (aucun plan)
    if not is_divers and any(k in data for k in ["date_debut", "date_fin", "montant_annuel_ht"]):
        from app.services.contrat_service import generer_plan_facturation
        db.query(PlanFacturation).filter(PlanFacturation.contrat_id == contrat.id).delete()
        from decimal import Decimal
        prorata_data = {
            "prorate": contrat.prorate_annee1,
            "nb_mois": Decimal(str(contrat.prorate_nb_mois or 12)),
            "montant_ht": Decimal(str(contrat.prorate_montant_ht or contrat.montant_annuel_ht)),
        }
        plan = generer_plan_facturation(
            str(contrat.id), contrat.date_debut, contrat.date_fin,
            Decimal(str(contrat.montant_annuel_ht)), prorata_data
        )
        for p in plan:
            db.add(PlanFacturation(
                contrat_id=contrat.id,
                numero_facture=p["numero_facture"],
                annee_facturation=p["annee_facturation"],
                type_facture=p["type_facture"],
                date_echeance=p["date_echeance"],
                montant_ht_prevu=float(p["montant_ht_prevu"]),
                statut="PLANIFIEE",
            ))

    db.commit()
    db.refresh(contrat)
    return {"message": "Contrat mis à jour", "id": str(contrat.id)}

@router.post("/{contrat_id}/terminer")
def terminer_contrat(
    contrat_id: str,
    motif: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Passe un contrat en statut TERMINE — plus aucune facture ne sera émise."""
    contrat = _get_or_404(contrat_id, db)
    contrat.statut = "TERMINE"
    contrat.date_statut_change = date.today()
    contrat.motif_fin = motif
    db.commit()
    return {"message": f"Contrat {contrat.numero_contrat} terminé", "id": contrat_id}


@router.post("/{contrat_id}/renouveler")
def renouveler_contrat(
    contrat_id: str,
    action: RenouvellementAction,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Gère le renouvellement d'un contrat selon 3 cas :
    - SPONTANE : prolonge la date de fin, continue la facturation
    - NOUVEAU_CONTRAT : crée un nouveau contrat, archive l'ancien, fusionne les avenants
    - FIN : termine le contrat sans suite

    Famille DIVERS : reconduction des dates anniversaire (durée identique) et du
    montant tels quels, sans prorata, sans regroupement année civile, sans plan.
    """
    contrat = _get_or_404(contrat_id, db)
    is_divers = (contrat.famille_contrat == "DIVERS")

    if action.type_renouvellement == "FIN":
        contrat.statut = "TERMINE"
        contrat.date_statut_change = date.today()
        contrat.motif_fin = action.notes or "Départ client"
        db.commit()
        return {"message": "Contrat terminé", "type": "FIN"}

    elif action.type_renouvellement == "SPONTANE":
        if is_divers:
            # Reconduction anniversaire SUR PLACE : on décale début ET fin de la
            # même durée, montant inchangé, aucun prorata, aucune ligne de plan.
            from datetime import timedelta
            duree = contrat.date_fin - contrat.date_debut          # timedelta, calculé AVANT réassignation
            contrat.date_debut = contrat.date_fin + timedelta(days=1)
            contrat.date_fin = contrat.date_debut + duree
            contrat.nombre_annees = calculer_nombre_annees(contrat.date_debut, contrat.date_fin, "DIVERS")
            contrat.statut = "EN_COURS"
            contrat.date_statut_change = date.today()
            db.commit()
            return {"message": f"Contrat DIVERS reconduit jusqu'au {contrat.date_fin}", "type": "SPONTANE"}

        # Prolonger d'une année
        from dateutil.relativedelta import relativedelta
        nouvelle_fin = contrat.date_fin + relativedelta(years=1)
        contrat.date_fin = nouvelle_fin
        contrat.nombre_annees = calculer_nombre_annees(contrat.date_debut, nouvelle_fin, contrat.famille_contrat)
        contrat.statut = "EN_COURS"
        contrat.date_statut_change = date.today()

        # Ajouter une facture au plan
        prochaine_annee = nouvelle_fin.year
        dernier_num = max(p.numero_facture for p in contrat.plan_facturation)
        db.add(PlanFacturation(
            contrat_id=contrat.id,
            numero_facture=dernier_num + 1,
            annee_facturation=prochaine_annee,
            date_echeance=date(prochaine_annee, 1, 1),
            type_facture="ANNUELLE",
            montant_ht_prevu=float(contrat.montant_annuel_ht),
            statut="PLANIFIEE",
        ))
        db.commit()
        return {"message": f"Contrat prolongé jusqu'au {nouvelle_fin}", "type": "SPONTANE"}

    elif action.type_renouvellement == "NOUVEAU_CONTRAT":
        if is_divers:
            # Nouveau contrat lié, dates reconduites (durée identique), montant
            # inchangé, sans prorata, sans plan de facturation.
            if not action.nouveau_numero:
                raise HTTPException(400, "Le numero du nouveau contrat est obligatoire")
            from datetime import timedelta

            # 1. Archiver l'ancien
            contrat.statut = "TERMINE"
            contrat.date_statut_change = date.today()
            contrat.motif_fin = "Remplacé par nouveau contrat"

            # 2. Calcul des nouvelles dates (durée identique par défaut)
            nouvelle_date_debut = action.nouvelle_date_debut or (contrat.date_fin + timedelta(days=1))
            duree = contrat.date_fin - contrat.date_debut
            nouvelle_date_fin = action.nouvelle_date_fin or (nouvelle_date_debut + duree)

            # 3. Créer le nouveau contrat (RENOUVELLEMENT, BROUILLON)
            nouveau = Contrat(
                numero_contrat=action.nouveau_numero,
                client_karlia_id=contrat.client_karlia_id,
                client_nom=contrat.client_nom,
                client_numero=contrat.client_numero,
                famille_contrat=contrat.famille_contrat,
                date_debut=nouvelle_date_debut,
                date_fin=nouvelle_date_fin,
                nombre_annees=calculer_nombre_annees(nouvelle_date_debut, nouvelle_date_fin, "DIVERS"),
                montant_annuel_ht=contrat.montant_annuel_ht,
                prorate_annee1=False,
                prorate_montant_ht=contrat.montant_annuel_ht,
                prorate_validated=True,
                type_contrat="RENOUVELLEMENT",
                contrat_parent_id=contrat.id,
                statut="BROUILLON",
            )
            db.add(nouveau)
            db.flush()

            # 4. Copier les articles du contrat principal (aucun plan de facturation)
            for art in contrat.articles:
                db.add(ContratArticle(
                    contrat_id=nouveau.id,
                    rang=art.rang,
                    designation=art.designation,
                    article_karlia_id=art.article_karlia_id,
                    reference=art.reference,
                    prix_unitaire_ht=art.prix_unitaire_ht,
                    quantite=art.quantite,
                    unite=art.unite,
                    taux_tva=art.taux_tva,
                ))

            db.commit()
            return {
                "message": f"Nouveau contrat DIVERS {action.nouveau_numero} créé",
                "type": "NOUVEAU_CONTRAT",
                "nouveau_contrat_id": str(nouveau.id),
                "avenants_fusionnes": 0,
            }

        # 1. Archiver l'ancien
        contrat.statut = "TERMINE"
        contrat.date_statut_change = date.today()
        contrat.motif_fin = "Remplacé par nouveau contrat"

        # 2. Identifier les avenants à fusionner
        avenants = db.query(Contrat).filter(
            Contrat.contrat_parent_id == contrat.id,
            Contrat.type_contrat == "AVENANT",
        ).all()

        # 3. Créer le nouveau contrat (copie avec nouvelles dates)
        if not action.nouveau_numero:
            raise HTTPException(400, "Le numero du nouveau contrat est obligatoire")
        nouveau_numero = action.nouveau_numero
        from datetime import timedelta
        from dateutil.relativedelta import relativedelta as rdelta
        nouvelle_date_debut = action.nouvelle_date_debut or (contrat.date_fin + timedelta(days=1))
        if action.nouvelle_date_fin:
            nouvelle_date_fin = action.nouvelle_date_fin
        else:
            nouvelle_date_fin = nouvelle_date_debut + rdelta(years=contrat.nombre_annees) - timedelta(days=1)

        prorata = calculer_prorata(nouvelle_date_debut, contrat.montant_annuel_ht)
        nb_annees = calculer_nombre_annees(nouvelle_date_debut, nouvelle_date_fin, contrat.famille_contrat)

        nouveau = Contrat(
            numero_contrat=nouveau_numero,
            client_karlia_id=contrat.client_karlia_id,
            client_nom=contrat.client_nom,
            client_numero=contrat.client_numero,
            # Le renouvellement hérite de la famille du contrat parent (était
            # omis → retombait sur le défaut 'COSOLUCE').
            famille_contrat=contrat.famille_contrat,
            date_debut=nouvelle_date_debut,
            date_fin=nouvelle_date_fin,
            nombre_annees=nb_annees,
            montant_annuel_ht=contrat.montant_annuel_ht,
            prorate_annee1=prorata["prorate"],
            prorate_nb_mois=prorata["nb_mois"],
            prorate_montant_ht=prorata["montant_ht"],
            prorate_validated=not prorata["prorate"],
            type_contrat="RENOUVELLEMENT",
            contrat_parent_id=contrat.id,
            avenants_fusionnes=len(avenants) > 0,
            statut="BROUILLON",
        )
        db.add(nouveau)
        db.flush()

        # 4. Copier les articles du contrat principal
        for art in contrat.articles:
            db.add(ContratArticle(
                contrat_id=nouveau.id,
                rang=art.rang,
                designation=art.designation,
                article_karlia_id=art.article_karlia_id,
                reference=art.reference,
                prix_unitaire_ht=art.prix_unitaire_ht,
                quantite=art.quantite,
                unite=art.unite,
                taux_tva=art.taux_tva,
            ))

        # 5. Fusionner les avenants (leurs articles complémentaires sont intégrés si rang disponible)
        if avenants:
            rang_actuel = max((a.rang for a in nouveau.articles), default=0) + 1
            for avenant in avenants:
                for art in avenant.articles:
                    if rang_actuel <= 7:
                        db.add(ContratArticle(
                            contrat_id=nouveau.id,
                            rang=rang_actuel,
                            designation=f"[Avenant {avenant.numero_avenant}] {art.designation}",
                            article_karlia_id=art.article_karlia_id,
                            prix_unitaire_ht=art.prix_unitaire_ht,
                            quantite=art.quantite,
                            taux_tva=art.taux_tva,
                        ))
                        rang_actuel += 1
                avenant.statut = "TERMINE"

        # 6. Générer le plan de facturation du nouveau contrat
        plan = generer_plan_facturation(
            contrat_id=str(nouveau.id),
            date_debut=nouvelle_date_debut,
            date_fin=nouvelle_date_fin,
            montant_annuel_ht=contrat.montant_annuel_ht,
            prorata=prorata,
        )
        for p in plan:
            db.add(PlanFacturation(**{**p, "contrat_id": nouveau.id}))

        db.commit()
        return {
            "message": f"Nouveau contrat {nouveau_numero} créé",
            "type": "NOUVEAU_CONTRAT",
            "nouveau_contrat_id": str(nouveau.id),
            "avenants_fusionnes": len(avenants),
        }

    raise HTTPException(400, f"Type de renouvellement inconnu : {action.type_renouvellement}")


# ── Helpers ───────────────────────────────────────────────────

def _get_or_404(contrat_id: str, db: Session) -> Contrat:
    c = db.query(Contrat).filter(Contrat.id == uuid.UUID(contrat_id)).first()
    if not c:
        raise HTTPException(404, "Contrat introuvable")
    return c


def _contrat_to_dict(c: Contrat) -> dict:
    return {
        "id": str(c.id),
        "numero_contrat": c.numero_contrat,
        "client_karlia_id": c.client_karlia_id,
        "client_nom": c.client_nom,
        "client_numero": c.client_numero,
        "date_debut": c.date_debut.isoformat() if c.date_debut else None,
        "date_fin": c.date_fin.isoformat() if c.date_fin else None,
        "nombre_annees": c.nombre_annees,
        "montant_annuel_ht": float(c.montant_annuel_ht),
        "prorate_annee1": c.prorate_annee1,
        "prorate_nb_mois": float(c.prorate_nb_mois) if c.prorate_nb_mois else None,
        "prorate_montant_ht": float(c.prorate_montant_ht) if c.prorate_montant_ht else None,
        "prorate_validated": c.prorate_validated,
        "famille_contrat": c.famille_contrat,
        "type_contrat": c.type_contrat,
        "numero_avenant": c.numero_avenant,
        "contrat_parent_id": str(c.contrat_parent_id) if c.contrat_parent_id else None,
        "statut": c.statut,
        "motif_fin": c.motif_fin,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "validated_at": c.validated_at.isoformat() if c.validated_at else None,
    }


class RenouvellementLotAction(BaseModel):
    ids: List[str]
    type_renouvellement: str  # SPONTANE | FIN


@router.post("/renouveler-lot")
def renouveler_lot(
    action: RenouvellementLotAction,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Renouvelle plusieurs contrats d'un coup.
    Seuls SPONTANE et FIN sont supportés en mode lot.

    Famille DIVERS en SPONTANE : reconduction anniversaire sur place (décalage
    début + fin, recalcul durée DIVERS, aucune ligne de plan).
    """
    if action.type_renouvellement not in ("SPONTANE", "FIN"):
        raise HTTPException(400, "Mode lot : seuls SPONTANE et FIN sont supportés")

    resultats = []
    erreurs = []

    for contrat_id in action.ids:
        try:
            contrat = _get_or_404(contrat_id, db)
            single_action = RenouvellementAction(
                type_renouvellement=action.type_renouvellement
            )
            # Réutilise la logique existante
            if action.type_renouvellement == "FIN":
                contrat.statut = "TERMINE"
                contrat.date_statut_change = date.today()
                contrat.motif_fin = "Départ client (traitement en lot)"
                db.commit()
                resultats.append({"id": contrat_id, "numero": contrat.numero_contrat, "ok": True})

            elif action.type_renouvellement == "SPONTANE":
                if contrat.famille_contrat == "DIVERS":
                    # Reconduction anniversaire SUR PLACE (identique à renouveler_contrat).
                    from datetime import timedelta
                    duree = contrat.date_fin - contrat.date_debut
                    contrat.date_debut = contrat.date_fin + timedelta(days=1)
                    contrat.date_fin = contrat.date_debut + duree
                    contrat.nombre_annees = calculer_nombre_annees(contrat.date_debut, contrat.date_fin, "DIVERS")
                    contrat.statut = "EN_COURS"
                    contrat.date_statut_change = date.today()
                    db.commit()
                    resultats.append({"id": contrat_id, "numero": contrat.numero_contrat, "ok": True})
                    continue

                from dateutil.relativedelta import relativedelta
                nouvelle_fin = contrat.date_fin + relativedelta(years=1)
                contrat.date_fin = nouvelle_fin
                contrat.nombre_annees = calculer_nombre_annees(contrat.date_debut, nouvelle_fin, contrat.famille_contrat)
                contrat.statut = "EN_COURS"
                contrat.date_statut_change = date.today()
                prochaine_annee = nouvelle_fin.year
                dernier_num = max((p.numero_facture for p in contrat.plan_facturation), default=0)
                db.add(PlanFacturation(
                    contrat_id=contrat.id,
                    numero_facture=dernier_num + 1,
                    annee_facturation=prochaine_annee,
                    date_echeance=date(prochaine_annee, 1, 1),
                    type_facture="ANNUELLE",
                    montant_ht_prevu=float(contrat.montant_annuel_ht),
                    statut="PLANIFIEE",
                ))
                db.commit()
                resultats.append({"id": contrat_id, "numero": contrat.numero_contrat, "ok": True})

        except Exception as e:
            db.rollback()
            erreurs.append({"id": contrat_id, "erreur": str(e)})

    return {
        "traites": len(resultats),
        "erreurs": len(erreurs),
        "resultats": resultats,
        "detail_erreurs": erreurs,
    }


@router.post("/{contrat_id}/facturer-brouillon")
async def facturer_brouillon(
    contrat_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Génère une facture BROUILLON dans Karlia directement depuis un contrat DIVERS.

    Aucune révision, aucun prorata : les prix et quantités sont envoyés TELS QUE
    saisis sur le contrat. La facture est créée en brouillon côté Karlia
    (id_status=0, id_type=4 — gérés par karlia.creer_facture), éditable et
    supprimable là-bas. Aucune persistance en base pour ce lot.
    """
    contrat = _get_or_404(contrat_id, db)

    # ── Gardes métier (avant tout appel Karlia) ──
    if contrat.famille_contrat != "DIVERS":
        raise HTTPException(400, "Génération de facture brouillon réservée aux contrats DIVERS")
    if contrat.statut != "EN_COURS":
        raise HTTPException(400, "Le contrat doit être EN_COURS pour générer une facture brouillon")
    if not contrat.client_karlia_id:
        raise HTTPException(400, "Client Karlia manquant sur ce contrat")

    # ── Construction des lignes (prix tels que saisis, aucune révision) ──
    articles_contrat = sorted(contrat.articles, key=lambda a: a.rang)
    if articles_contrat:
        lignes = [
            {
                "id_product": art.article_karlia_id or None,
                "description": art.designation or "",
                "unit_price": float(art.prix_unitaire_ht or 0),
                "quantity": float(art.quantite or 1),
                "vat_rate": float(art.taux_tva or 20.0),
            }
            for art in articles_contrat
        ]
    else:
        # Fallback : aucun article → ligne unique au montant du contrat
        lignes = [{
            "description": f"Contrat {contrat.numero_contrat}",
            "unit_price": float(contrat.montant_annuel_ht),
            "quantity": 1,
            "vat_rate": 20.0,
        }]

    # ── Appel Karlia (brouillon : id_status=0 / id_type=4 gérés par creer_facture) ──
    try:
        res = await karlia.creer_facture(
            client_karlia_id=contrat.client_karlia_id,
            lignes=lignes,
            reference_contrat=contrat.numero_contrat,
            date_echeance=contrat.date_fin,          # date_end Karlia = fin du contrat
            montant_ht=float(contrat.montant_annuel_ht),
            description=f"Contrat {contrat.numero_contrat}",
            id_opportunity=contrat.karlia_opportunity_id,
        )
    except KarliaError as e:
        raise HTTPException(502, f"Erreur Karlia : {e}")

    return {
        "ok": True,
        "karlia_doc_id": res.get("id"),
        "karlia_doc_ref": res.get("reference"),
        "numero_contrat": contrat.numero_contrat,
    }

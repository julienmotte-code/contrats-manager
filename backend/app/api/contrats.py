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
from app.models.models import Contrat, ContratArticle, PlanFacturation, IndiceRevision
from app.services.contrat_service import (
    calculer_prorata, calculer_nombre_annees,
    generer_plan_facturation, calculer_statut_renouvellement,
)

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
    db: Session = Depends(get_db),
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
def creer_contrat(data: ContratCreate, db: Session = Depends(get_db)):
    """
    Crée un nouveau contrat en statut BROUILLON.
    Calcule le prorata et génère le plan de facturation prévisionnaire.
    """
    # Vérifier unicité du numéro
    if db.query(Contrat).filter(Contrat.numero_contrat == data.numero_contrat).first():
        raise HTTPException(400, f"Le numéro de contrat '{data.numero_contrat}' existe déjà")

    # Vérifier cohérence des dates
    if data.date_fin <= data.date_debut:
        raise HTTPException(400, "La date de fin doit être postérieure à la date de début")

    # Calculs
    montant_ht = Decimal(str(data.montant_annuel_ht))
    prorata = calculer_prorata(data.date_debut, montant_ht)
    nombre_annees = calculer_nombre_annees(data.date_debut, data.date_fin)

    # Créer le contrat
    contrat = Contrat(
        numero_contrat=data.numero_contrat,
        client_karlia_id=data.client_karlia_id,
        client_nom=data.client_nom,
        client_numero=data.client_numero,
        date_debut=data.date_debut,
        date_fin=data.date_fin,
        nombre_annees=nombre_annees,
        montant_annuel_ht=montant_ht,
        indice_reference_id=uuid.UUID(data.indice_reference_id) if data.indice_reference_id else None,
        prorate_annee1=prorata["prorate"],
        prorate_nb_mois=prorata["nb_mois"],
        prorate_montant_ht=prorata["montant_ht"],
        prorate_validated=data.prorate_validated,
        prorate_note=data.prorate_note,
        type_contrat=data.type_contrat,
        contrat_parent_id=uuid.UUID(data.contrat_parent_id) if data.contrat_parent_id else None,
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

    # Générer le plan de facturation
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
def obtenir_contrat(contrat_id: str, db: Session = Depends(get_db)):
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
def valider_contrat(contrat_id: str, db: Session = Depends(get_db)):
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
    db.commit()

    return {"message": f"Contrat {contrat.numero_contrat} validé — statut EN_COURS", "id": contrat_id}


@router.delete("/{contrat_id}")
def supprimer_contrat(contrat_id: str, db: Session = Depends(get_db)):
    """Supprime un contrat en statut BROUILLON uniquement."""
    contrat = _get_or_404(contrat_id, db)
    if contrat.statut != "BROUILLON":
        raise HTTPException(400, "Seuls les brouillons peuvent être supprimés")
    db.delete(contrat)
    db.commit()
    return {"message": f"Contrat {contrat.numero_contrat} supprimé"}

@router.put("/{contrat_id}")
def modifier_contrat(contrat_id: str, data: dict, db: Session = Depends(get_db)):
    """Modifie un contrat en statut BROUILLON uniquement."""
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
        contrat.nombre_annees = contrat.date_fin.year - contrat.date_debut.year + 1

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

    # Regénérer plan de facturation
    if any(k in data for k in ["date_debut", "date_fin", "montant_annuel_ht"]):
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
def terminer_contrat(contrat_id: str, motif: Optional[str] = None, db: Session = Depends(get_db)):
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
):
    """
    Gère le renouvellement d'un contrat selon 3 cas :
    - SPONTANE : prolonge la date de fin, continue la facturation
    - NOUVEAU_CONTRAT : crée un nouveau contrat, archive l'ancien, fusionne les avenants
    - FIN : termine le contrat sans suite
    """
    contrat = _get_or_404(contrat_id, db)

    if action.type_renouvellement == "FIN":
        contrat.statut = "TERMINE"
        contrat.date_statut_change = date.today()
        contrat.motif_fin = action.notes or "Départ client"
        db.commit()
        return {"message": "Contrat terminé", "type": "FIN"}

    elif action.type_renouvellement == "SPONTANE":
        # Prolonger d'une année
        from dateutil.relativedelta import relativedelta
        nouvelle_fin = contrat.date_fin + relativedelta(years=1)
        contrat.date_fin = nouvelle_fin
        contrat.nombre_annees = calculer_nombre_annees(contrat.date_debut, nouvelle_fin)
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
        nouvelle_date_debut = action.nouvelle_date_debut or date(contrat.date_fin.year + 1, 1, 1)
        nouvelle_date_fin = action.nouvelle_date_fin or date(
            nouvelle_date_debut.year + contrat.nombre_annees - 1, 12, 31
        )
        nouveau_numero = action.nouveau_numero or f"{contrat.numero_contrat}-R"

        prorata = calculer_prorata(nouvelle_date_debut, contrat.montant_annuel_ht)
        nb_annees = calculer_nombre_annees(nouvelle_date_debut, nouvelle_date_fin)

        nouveau = Contrat(
            numero_contrat=nouveau_numero,
            client_karlia_id=contrat.client_karlia_id,
            client_nom=contrat.client_nom,
            client_numero=contrat.client_numero,
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
):
    """
    Renouvelle plusieurs contrats d'un coup.
    Seuls SPONTANE et FIN sont supportés en mode lot.
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
                from dateutil.relativedelta import relativedelta
                nouvelle_fin = contrat.date_fin + relativedelta(years=1)
                contrat.date_fin = nouvelle_fin
                contrat.nombre_annees = calculer_nombre_annees(contrat.date_debut, nouvelle_fin)
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

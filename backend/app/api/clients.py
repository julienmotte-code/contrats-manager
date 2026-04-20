"""
Routes API — Clients
GET  /api/clients          → Liste (depuis cache local + synchro Karlia)
GET  /api/clients/search   → Recherche en temps réel dans Karlia
POST /api/clients          → Création dans Karlia + cache local
GET  /api/clients/{id}     → Détail d'un client
POST /api/clients/synchro  → Resynchronise le cache depuis Karlia
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel, EmailStr
from app.core.database import get_db
from app.models.models import ClientCache
from app.services.karlia_service import karlia, KarliaError
from app.services.contrat_service import generer_numero_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schémas Pydantic ────────────────────────────────────────

class ClientCreate(BaseModel):
    """Données pour créer un nouveau client dans Karlia."""
    nom: str
    forme_juridique: Optional[str] = None
    adresse_ligne1: Optional[str] = None
    adresse_ligne2: Optional[str] = None
    code_postal: Optional[str] = None
    ville: Optional[str] = None
    pays: str = "France"
    email: Optional[str] = None
    telephone: Optional[str] = None
    mobile: Optional[str] = None
    siret: Optional[str] = None
    tva_intracom: Optional[str] = None
    contact_nom: Optional[str] = None
    contact_prenom: Optional[str] = None
    contact_fonction: Optional[str] = None
    notes: Optional[str] = None
    prospect: int = 0  # 0 = Client


# ── Routes ──────────────────────────────────────────────────

@router.get("")
async def lister_clients(
    recherche: Optional[str] = Query(None, description="Recherche par nom ou numéro"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    source: str = Query("cache", description="'cache' ou 'karlia'"),
    db: Session = Depends(get_db),
):
    """
    Liste les clients.
    Par défaut depuis le cache local (rapide).
    Avec source=karlia : requête directe à Karlia (pour forcer la mise à jour).
    """
    if source == "karlia":
        try:
            result = await karlia.lister_clients(recherche=recherche, limit=limit, offset=offset)
            return {
                "source": "karlia",
                "total": result.get("pagination", {}).get("total", 0),
                "data": [_formater_client_karlia(c) for c in result.get("data", [])],
            }
        except KarliaError as e:
            raise HTTPException(status_code=502, detail=f"Erreur Karlia : {e.message}")

    # Depuis le cache local
    query = db.query(ClientCache)
    if recherche:
        query = query.filter(
            ClientCache.nom.ilike(f"%{recherche}%") |
            ClientCache.numero_client.ilike(f"%{recherche}%")
        )
    total = query.count()
    clients = query.order_by(ClientCache.nom).offset(offset).limit(limit).all()

    return {
        "source": "cache",
        "total": total,
        "data": [_client_to_dict(c) for c in clients],
    }


@router.get("/search")
def rechercher_clients_cache(
    q: str = Query(..., min_length=2, description="Terme de recherche"),
    db: Session = Depends(get_db),
):
    """Recherche dans le cache local en mode contient — nom, numéro, ville, SIRET, email."""
    termes = q.strip().split()
    query = db.query(ClientCache)
    for terme in termes:
        pattern = f"%{terme}%"
        query = query.filter(
            ClientCache.nom.ilike(pattern) |
            ClientCache.numero_client.ilike(pattern) |
            ClientCache.ville.ilike(pattern) |
            ClientCache.siret.ilike(pattern) |
            ClientCache.email.ilike(pattern)
        )
    clients = query.order_by(ClientCache.nom).limit(30).all()
    return {
        "data": [
            {
                "karlia_id": c.karlia_id,
                "numero_client": c.numero_client,
                "nom": c.nom,
                "ville": c.ville,
                "email": c.email,
                "siret": c.siret,
            }
            for c in clients
        ]
    }


@router.get("/numero-suivant")
async def prochain_numero_client(db: Session = Depends(get_db)):
    """
    Retourne le prochain numéro incrémental disponible.
    Interroge Karlia pour être sûr de ne pas créer un doublon.
    """
    try:
        dernier = await karlia.dernier_numero_client()
        return {"dernier_numero": dernier, "prochain": dernier + 1}
    except KarliaError as e:
        raise HTTPException(status_code=502, detail=f"Erreur Karlia : {e.message}")


@router.post("")
async def creer_client(
    data: ClientCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Crée un client dans Karlia et le met en cache local.
    Le numéro client est généré automatiquement selon la règle métier.
    """
    # 1. Récupérer le dernier numéro
    try:
        dernier_num = await karlia.dernier_numero_client()
    except KarliaError as e:
        raise HTTPException(status_code=502, detail=f"Impossible de récupérer la numérotation Karlia : {e.message}")

    # 2. Générer le numéro client
    numero_client = generer_numero_client(data.nom, dernier_num)

    # 3. Construire le payload Karlia
    payload_karlia = {
        "name": data.nom,
        "individual": 0,
        "prospect": data.prospect,
        "client_number": numero_client,
        "email": data.email,
        "phone": data.telephone,
        "mobile": data.mobile,
        "siret": data.siret,
        "vat_number": data.tva_intracom,
        "legal_form": data.forme_juridique,
        "description": data.notes,
        "langId": 1,  # Français
        "main_address": data.adresse_ligne1,
        "main_zip_code": data.code_postal,
        "main_city": data.ville,
        "main_country": data.pays,
        # Adresse de facturation = adresse principale par défaut
        "invoice_address": data.adresse_ligne1,
        "invoice_zip_code": data.code_postal,
        "invoice_city": data.ville,
        "invoice_country": data.pays,
    }
    # Retirer les champs None pour ne pas polluer l'API
    payload_karlia = {k: v for k, v in payload_karlia.items() if v is not None}

    # 4. Créer dans Karlia
    try:
        client_karlia = await karlia.creer_client(payload_karlia)
    except KarliaError as e:
        raise HTTPException(status_code=502, detail=f"Erreur création Karlia : {e.message}")

    karlia_id = str(client_karlia["id"])

    # 5. Mettre en cache local
    cache = ClientCache(
        karlia_id=karlia_id,
        numero_client=numero_client,
        nom=data.nom,
        adresse_ligne1=data.adresse_ligne1,
        adresse_ligne2=data.adresse_ligne2,
        code_postal=data.code_postal,
        ville=data.ville,
        pays=data.pays,
        email=data.email,
        telephone=data.telephone,
        mobile=data.mobile,
        siret=data.siret,
        tva_intracom=data.tva_intracom,
        forme_juridique=data.forme_juridique,
        contact_nom=data.contact_nom,
        contact_prenom=data.contact_prenom,
        contact_fonction=data.contact_fonction,
        notes=data.notes,
    )
    db.add(cache)
    db.commit()
    db.refresh(cache)

    # 6. Créer le contact principal si renseigné (en arrière-plan)
    if data.contact_nom:
        background_tasks.add_task(
            _creer_contact_karlia,
            karlia_id=karlia_id,
            nom=data.contact_nom,
            prenom=data.contact_prenom,
            fonction=data.contact_fonction,
        )

    logger.info(f"Client créé : {numero_client} — {data.nom} (Karlia ID: {karlia_id})")
    return {
        "id": str(cache.id),
        "karlia_id": karlia_id,
        "numero_client": numero_client,
        "nom": data.nom,
        "message": f"Client {numero_client} créé avec succès dans Karlia",
    }


@router.get("/{karlia_id}/fiche")
def fiche_client(
    karlia_id: str,
    db: Session = Depends(get_db),
):
    """
    Fiche complete d'un client : coordonnees + contrats actifs + historique termines.
    """
    from app.models.models import Contrat

    client = db.query(ClientCache).filter(ClientCache.karlia_id == karlia_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable dans le cache local")

    tous_contrats = (
        db.query(Contrat)
        .filter(Contrat.client_karlia_id == karlia_id)
        .order_by(Contrat.date_debut.desc())
        .all()
    )

    statuts_termines = {"TERMINE", "RESILIE", "EXPIRE"}

    def contrat_to_dict(c):
        return {
            "id": str(c.id),
            "numero_contrat": c.numero_contrat,
            "famille_contrat": c.famille_contrat,
            "statut": c.statut,
            "date_debut": c.date_debut.isoformat() if c.date_debut else None,
            "date_fin": c.date_fin.isoformat() if c.date_fin else None,
            "nombre_annees": c.nombre_annees,
            "montant_annuel_ht": float(c.montant_annuel_ht) if c.montant_annuel_ht else 0,
            "notes_internes": c.notes_internes,
        }

    contrats_actifs        = [contrat_to_dict(c) for c in tous_contrats if c.statut not in statuts_termines]
    contrats_termines_list = [contrat_to_dict(c) for c in tous_contrats if c.statut in statuts_termines]

    from app.models.models import PlanFacturation
    ids_contrats = [c.id for c in tous_contrats]
    factures = []
    if ids_contrats:
        plans = (
            db.query(PlanFacturation)
            .filter(
                PlanFacturation.contrat_id.in_(ids_contrats),
                PlanFacturation.statut == "EMISE",
            )
            .order_by(PlanFacturation.date_echeance.desc())
            .all()
        )
        map_contrats = {c.id: c.numero_contrat for c in tous_contrats}
        for p in plans:
            factures.append({
                "id": str(p.id),
                "numero_contrat": map_contrats.get(p.contrat_id, ""),
                "annee_facturation": p.annee_facturation,
                "date_echeance": p.date_echeance.isoformat() if p.date_echeance else None,
                "montant_ht": float(p.montant_ht_facture) if p.montant_ht_facture else (float(p.montant_revise_ht) if p.montant_revise_ht else float(p.montant_ht_prevu) if p.montant_ht_prevu else 0),
                "reference_karlia": p.facture_karlia_ref or "",
                "statut": p.statut,
            })

    return {
        "client": _client_to_dict(client),
        "contrats_actifs": contrats_actifs,
        "contrats_termines": contrats_termines_list,
        "factures": factures,
        "stats": {
            "nb_contrats_actifs": len(contrats_actifs),
            "nb_contrats_termines": len(contrats_termines_list),
            "montant_annuel_total": sum(c["montant_annuel_ht"] for c in contrats_actifs),
            "nb_factures": len(factures),
            "montant_factures_total": sum(f["montant_ht"] for f in factures),
        },
    }


@router.get("/{karlia_id}")
async def obtenir_client(karlia_id: str, db: Session = Depends(get_db)):
    """Retourne le détail d'un client (cache local en priorité)."""
    client = db.query(ClientCache).filter(ClientCache.karlia_id == karlia_id).first()
    if client:
        return _client_to_dict(client)
    # Fallback vers Karlia
    try:
        c = await karlia.obtenir_client(karlia_id)
        return _formater_client_karlia(c)
    except KarliaError as e:
        raise HTTPException(status_code=404, detail="Client introuvable")


@router.post("/synchro")
async def synchroniser_clients(db: Session = Depends(get_db)):
    """
    Resynchronise le cache local depuis Karlia.
    À lancer manuellement ou planifier périodiquement.
    """
    try:
        total_synchro = 0
        offset = 0
        limit = 100

        while True:
            result = await karlia.lister_clients(limit=limit, offset=offset)
            clients_karlia = result.get("data", [])
            if not clients_karlia:
                break

            for c in clients_karlia:
                karlia_id = str(c["id"])
                existing = db.query(ClientCache).filter(ClientCache.karlia_id == karlia_id).first()
                addr = next((a for a in c.get("address_list", []) if a.get("type") == "main"), {})

                data = {
                    "karlia_id": karlia_id,
                    "numero_client": str(c.get("client_number", "")),
                    "nom": c.get("title", c.get("name", "")),
                    "adresse_ligne1": addr.get("address"),
                    "code_postal": addr.get("zip_code"),
                    "ville": addr.get("city"),
                    "pays": addr.get("country", "France"),
                    "email": c.get("email"),
                    "telephone": c.get("phone"),
                    "mobile": c.get("mobile"),
                    "siret": c.get("siret"),
                    "tva_intracom": c.get("vat_number"),
                    "forme_juridique": c.get("legal_form"),
                }
                if existing:
                    for k, v in data.items():
                        setattr(existing, k, v)
                else:
                    # Vérifier aussi par numero_client pour éviter les doublons (seulement si non vide)
                    existing_num = None
                    if data["numero_client"]:
                        existing_num = db.query(ClientCache).filter(
                            ClientCache.numero_client == data["numero_client"]
                        ).first()
                    if existing_num:
                        for k, v in data.items():
                            setattr(existing_num, k, v)
                    else:
                        db.add(ClientCache(**data))
                total_synchro += 1

            db.commit()
            if len(clients_karlia) < limit:
                break
            offset += limit

        return {"message": f"{total_synchro} clients synchronisés depuis Karlia"}
    except KarliaError as e:
        raise HTTPException(status_code=502, detail=f"Erreur Karlia : {e.message}")


# ── Helpers ────────────────────────────────────────────────

def _client_to_dict(c: ClientCache) -> dict:
    return {
        "id": str(c.id),
        "karlia_id": c.karlia_id,
        "numero_client": c.numero_client,
        "nom": c.nom,
        "adresse_ligne1": c.adresse_ligne1,
        "adresse_ligne2": c.adresse_ligne2,
        "code_postal": c.code_postal,
        "ville": c.ville,
        "pays": c.pays,
        "email": c.email,
        "telephone": c.telephone,
        "siret": c.siret,
        "tva_intracom": c.tva_intracom,
        "forme_juridique": c.forme_juridique,
        "contact_nom": c.contact_nom,
        "contact_prenom": c.contact_prenom,
        "contact_fonction": c.contact_fonction,
    }


def _formater_client_karlia(c: dict) -> dict:
    addr = next((a for a in c.get("address_list", []) if a.get("type") == "main"), {})
    return {
        "karlia_id": str(c.get("id", "")),
        "numero_client": str(c.get("client_number", "")),
        "nom": c.get("title", c.get("name", "")),
        "email": c.get("email"),
        "telephone": c.get("phone"),
        "adresse_ligne1": addr.get("address"),
        "code_postal": addr.get("zip_code"),
        "ville": addr.get("city"),
        "pays": addr.get("country"),
        "siret": c.get("siret"),
        "tva_intracom": c.get("vat_number"),
        "forme_juridique": c.get("legal_form"),
    }


async def _creer_contact_karlia(karlia_id: str, nom: str, prenom: str = None, fonction: str = None):
    """Tâche de fond : crée le contact principal dans Karlia."""
    try:
        import httpx
        from app.core.config import settings
        payload = {
            "id_customer_supplier": int(karlia_id),
            "lastname": nom,
            "firstname": prenom or "",
            "position_title": fonction or "",
        }
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.KARLIA_API_URL}/contacts",
                json=payload,
                headers={"Authorization": f"Bearer {settings.KARLIA_API_KEY}"},
                timeout=15,
            )
    except Exception as e:
        logger.warning(f"Impossible de créer le contact Karlia pour {karlia_id} : {e}")

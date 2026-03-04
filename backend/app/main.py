"""
Module Gestion des Contrats — Backend FastAPI
Point d'entrée principal
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from app.api import clients, produits, contrats, facturation, indices, documents, auth, parametres, utilisateurs, audit
from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.services.karlia_service import karlia
from app.models.models import ClientCache, ArticleCache, Parametre

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Module Gestion Contrats",
    description="API de gestion des contrats pluriannuels — Interface Karlia",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,         prefix="/api/auth",        tags=["Authentification"])
app.include_router(clients.router,      prefix="/api/clients",     tags=["Clients"])
app.include_router(produits.router,     prefix="/api/produits",    tags=["Produits / Articles"])
app.include_router(contrats.router,     prefix="/api/contrats",    tags=["Contrats"])
app.include_router(facturation.router,  prefix="/api/facturation", tags=["Facturation"])
app.include_router(indices.router,      prefix="/api/indices",     tags=["Indices Syntec"])
app.include_router(utilisateurs.router,  prefix="/api/utilisateurs", tags=["Utilisateurs"])
app.include_router(documents.router,    prefix="/api/documents",   tags=["Documents"])
app.include_router(parametres.router,   prefix="/api/parametres",  tags=["Paramètres"])
app.include_router(audit.router,        prefix="/api/audit",       tags=["Audit"])

async def synchro_karlia():
    """Synchronise clients et articles depuis Karlia."""
    print(f"[SYNCHRO] Démarrage synchro Karlia — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    db = SessionLocal()
    total_clients = 0
    total_articles = 0
    try:
        # Synchro clients
        offset = 0
        limit = 100
        while True:
            result = await karlia.lister_clients(limit=limit, offset=offset)
            clients_data = result.get("data", [])
            if not clients_data:
                break
            for c in clients_data:
                karlia_id = str(c["id"])
                numero = str(c.get("client_number", "") or "").strip()
                if not numero:
                    numero = f"K{karlia_id}"
                addr = next((a for a in c.get("address_list", []) if a.get("type") == "main"), {})
                existing = db.query(ClientCache).filter(ClientCache.karlia_id == karlia_id).first()
                data = dict(
                    karlia_id=karlia_id, numero_client=numero,
                    nom=c.get("title", c.get("name", "")),
                    adresse_ligne1=addr.get("address"), code_postal=addr.get("zip_code"),
                    ville=addr.get("city"), pays=addr.get("country", "France"),
                    email=c.get("email"), telephone=c.get("phone"), mobile=c.get("mobile"),
                    siret=c.get("siret"), tva_intracom=c.get("vat_number"),
                    forme_juridique=c.get("legal_form"),
                )
                if existing:
                    for k, v in data.items():
                        setattr(existing, k, v)
                else:
                    num_exists = db.query(ClientCache).filter(ClientCache.numero_client == numero).first()
                    if num_exists:
                        data["numero_client"] = f"K{karlia_id}"
                    db.add(ClientCache(**data))
                total_clients += 1
            db.commit()
            if len(clients_data) < limit:
                break
            offset += limit

        # Synchro articles
        result = await karlia.lister_produits(limit=500)
        produits_data = result.get("data", [])
        for p in produits_data:
            karlia_id = str(p["id"])
            existing = db.query(ArticleCache).filter(ArticleCache.karlia_id == karlia_id).first()
            prix = p.get("sell_price", {})
            prix_ht = prix.get("price") if isinstance(prix, dict) else None
            data = dict(
                karlia_id=karlia_id, reference=str(p.get("reference", "") or ""),
                designation=p.get("title", p.get("name", "")),
                prix_unitaire_ht=prix_ht, unite=str(p.get("unit", "") or ""), actif=True,
            )
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
            else:
                db.add(ArticleCache(**data))
            total_articles += 1
        db.commit()

        # Sauvegarder date de dernière synchro
        param = db.query(Parametre).filter(Parametre.cle == "derniere_synchro").first()
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        if param:
            param.valeur = now_str
        else:
            db.add(Parametre(cle="derniere_synchro", valeur=now_str, description="Dernière synchronisation Karlia"))
        param2 = db.query(Parametre).filter(Parametre.cle == "synchro_stats").first()
        stats = f"{total_clients} clients, {total_articles} articles"
        if param2:
            param2.valeur = stats
        else:
            db.add(Parametre(cle="synchro_stats", valeur=stats, description="Stats dernière synchro"))
        db.commit()
        print(f"[SYNCHRO] Terminée — {total_clients} clients, {total_articles} articles")
    except Exception as e:
        print(f"[SYNCHRO] Erreur : {e}")
    finally:
        db.close()

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup():
    # Charger la clé API Karlia depuis la base si elle existe
    db = SessionLocal()
    try:
        param = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
        if param and param.valeur:
            karlia.api_key = param.valeur
            print(f"[CONFIG] Clé API Karlia chargée depuis la base")
    finally:
        db.close()
    # Synchro au démarrage
    await synchro_karlia()
    # Synchro nocturne à 2h
    scheduler.add_job(synchro_karlia, CronTrigger(hour=2, minute=0))
    scheduler.start()
    print("[SCHEDULER] Synchro nocturne planifiée à 2h00")

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}

@app.get("/api/synchro/statut")
async def statut_synchro():
    db = SessionLocal()
    try:
        p1 = db.query(Parametre).filter(Parametre.cle == "derniere_synchro").first()
        p2 = db.query(Parametre).filter(Parametre.cle == "synchro_stats").first()
        return {
            "derniere_synchro": p1.valeur if p1 else None,
            "stats": p2.valeur if p2 else None,
        }
    finally:
        db.close()

@app.post("/api/synchro/lancer")
async def lancer_synchro():
    await synchro_karlia()
    db = SessionLocal()
    try:
        p1 = db.query(Parametre).filter(Parametre.cle == "derniere_synchro").first()
        p2 = db.query(Parametre).filter(Parametre.cle == "synchro_stats").first()
        return {
            "derniere_synchro": p1.valeur if p1 else None,
            "stats": p2.valeur if p2 else None,
        }
    finally:
        db.close()

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict
from app.core.database import get_db
from app.models.models import Parametre, ClientCache, ArticleCache
from app.services.karlia_service import karlia
from app.api.auth import get_current_user
from app.models.models import Utilisateur
from pydantic import BaseModel

router = APIRouter()


class ParamUpdate(BaseModel):
    valeur: str


@router.get("/")
def get_parametres(db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    params = db.query(Parametre).all()
    result = {p.cle: p.valeur for p in params}
    # Masquer la clé API — afficher seulement les 8 premiers caractères
    from app.core.config import settings
    cle_active = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
    cle = cle_active.valeur if cle_active else settings.KARLIA_API_KEY
    result["karlia_api_key_apercu"] = cle[:8] + "..." if cle else ""
    result["derniere_synchro"] = result.get("derniere_synchro", "Jamais")
    result["synchro_stats"] = result.get("synchro_stats", "")
    return result


@router.put("/karlia-api-key")
def update_karlia_api_key(
    body: ParamUpdate,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    param = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
    if param:
        param.valeur = body.valeur
    else:
        db.add(Parametre(cle="karlia_api_key", valeur=body.valeur, description="Clé API Karlia active"))
    db.commit()
    # Mettre à jour le service Karlia en mémoire
    karlia.api_key = body.valeur
    return {"message": "Clé API mise à jour"}


@router.post("/tester-connexion")
async def tester_connexion(
    current_user: Utilisateur = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        result = await karlia.tester_connexion()
        if isinstance(result, dict):
            company = result.get("company", result)
            name = company.get("name", "")
            siret = company.get("siret", "")
            expiration = company.get("expiration_date", "")
            message = f"Connexion réussie — {name} (SIRET: {siret}) — Abonnement jusqu'au {expiration}"
        else:
            message = str(result)
        return {"succes": True, "message": message}
    except Exception as e:
        return {"succes": False, "message": str(e)}


@router.post("/vider-cache")
def vider_cache(
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    nb_clients = db.query(ClientCache).count()
    nb_articles = db.query(ArticleCache).count()
    db.query(ClientCache).delete()
    db.query(ArticleCache).delete()
    # Réinitialiser stats synchro
    for cle in ["derniere_synchro", "synchro_stats"]:
        p = db.query(Parametre).filter(Parametre.cle == cle).first()
        if p:
            db.delete(p)
    db.commit()
    return {"message": f"Cache vidé — {nb_clients} clients et {nb_articles} articles supprimés"}


# ══════════════════════════════════════════════════════════════════════════════
# CHORUS PRO
# ══════════════════════════════════════════════════════════════════════════════

CHORUS_PARAMS = [
    'chorus_client_id',
    'chorus_client_secret',
    'chorus_tech_username',
    'chorus_tech_password',
    'chorus_siret_emetteur',
    'chorus_code_service',
    'chorus_code_banque',
    'chorus_id_fournisseur',
    'chorus_id_utilisateur_courant',
    'chorus_mode_qualification',
]


@router.get("/chorus")
def get_chorus_params(
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """Récupère les paramètres Chorus Pro (masque les secrets)."""
    params = db.query(Parametre).filter(Parametre.cle.in_(CHORUS_PARAMS)).all()
    result = {}
    for p in params:
        # Masquer les secrets
        if p.cle in ('chorus_client_secret', 'chorus_tech_password'):
            result[p.cle] = '••••••••' if p.valeur else ''
        else:
            result[p.cle] = p.valeur or ''
    return result


@router.put("/chorus")
def update_chorus_params(
    data: Dict[str, str],
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """Met à jour les paramètres Chorus Pro."""
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    
    updated = 0
    for cle in CHORUS_PARAMS:
        if cle not in data:
            continue
        valeur = data[cle]
        
        # Ne pas écraser les secrets si on envoie la valeur masquée
        if valeur == '••••••••':
            continue
            
        param = db.query(Parametre).filter(Parametre.cle == cle).first()
        if param:
            param.valeur = valeur
        else:
            descriptions = {
                'chorus_client_id': 'Client ID OAuth2 PISTE pour Chorus Pro',
                'chorus_client_secret': 'Client Secret OAuth2 PISTE pour Chorus Pro',
                'chorus_tech_username': 'Login du compte technique Chorus Pro',
                'chorus_tech_password': 'Mot de passe du compte technique Chorus Pro',
                'chorus_siret_emetteur': 'SIRET de la structure émettrice',
                'chorus_code_service': 'Code service fournisseur (optionnel)',
                'chorus_code_banque': 'Code coordonnées bancaires fournisseur',
                'chorus_id_fournisseur': 'Identifiant Chorus du fournisseur',
                'chorus_id_utilisateur_courant': 'Identifiant Chorus de l\'utilisateur courant',
                'chorus_mode_qualification': 'Utiliser l\'environnement de qualification (sandbox)',
            }
            db.add(Parametre(cle=cle, valeur=valeur, description=descriptions.get(cle, '')))
        updated += 1
    
    db.commit()
    return {"message": f"{updated} paramètre(s) mis à jour"}

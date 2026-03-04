from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Utilisateur
from app.api.auth import get_current_user
import bcrypt

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
import uuid

router = APIRouter()

ROLES = ["ADMIN", "GESTIONNAIRE", "CONSULTANT"]

DROITS = {
    "ADMIN":        {"contrats_ecriture": True,  "facturation": True,  "indices": True,  "parametres": True,  "utilisateurs": True},
    "GESTIONNAIRE": {"contrats_ecriture": True,  "facturation": True,  "indices": True,  "parametres": False, "utilisateurs": False},
    "CONSULTANT":   {"contrats_ecriture": False, "facturation": False, "indices": False, "parametres": False, "utilisateurs": False},
}

def require_admin(current_user: Utilisateur = Depends(get_current_user)):
    if current_user.role != "ADMIN":
        raise HTTPException(403, "Accès réservé aux administrateurs")
    return current_user

@router.get("/droits")
def get_droits(current_user: Utilisateur = Depends(get_current_user)):
    """Retourne les droits de l'utilisateur connecté."""
    role = current_user.role if current_user.role in DROITS else "CONSULTANT"
    return {
        "role": role,
        "droits": DROITS[role],
        "roles_disponibles": ROLES,
    }

@router.get("")
def lister_utilisateurs(
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(require_admin)
):
    """Liste tous les utilisateurs."""
    users = db.query(Utilisateur).order_by(Utilisateur.nom_complet).all()
    return {"data": [{
        "id": str(u.id),
        "login": u.login,
        "email": u.email,
        "nom_complet": u.nom_complet,
        "role": u.role,
        "actif": u.actif,
        "derniere_connexion": str(u.derniere_connexion) if u.derniere_connexion else None,
        "created_at": str(u.created_at),
    } for u in users]}

@router.post("")
def creer_utilisateur(
    data: dict,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(require_admin)
):
    """Crée un nouvel utilisateur."""
    login = data.get("login", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "CONSULTANT")

    if not login or not email or not password:
        raise HTTPException(400, "login, email et password sont obligatoires")
    if role not in ROLES:
        raise HTTPException(400, f"Rôle invalide. Valeurs acceptées : {ROLES}")
    if db.query(Utilisateur).filter(Utilisateur.login == login).first():
        raise HTTPException(400, f"Login '{login}' déjà utilisé")
    if db.query(Utilisateur).filter(Utilisateur.email == email).first():
        raise HTTPException(400, f"Email '{email}' déjà utilisé")

    user = Utilisateur(
        id=uuid.uuid4(),
        login=login,
        email=email,
        nom_complet=data.get("nom_complet", ""),
        password_hash=get_password_hash(password),
        role=role,
        actif=True,
    )
    db.add(user)
    db.commit()
    return {"id": str(user.id), "login": user.login, "role": user.role}

@router.put("/{user_id}")
def modifier_utilisateur(
    user_id: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(require_admin)
):
    """Modifie un utilisateur."""
    user = db.query(Utilisateur).filter(Utilisateur.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé")
    # Empêcher de se rétrograder soi-même
    if str(user.id) == str(current_user.id) and data.get("role") != "ADMIN":
        raise HTTPException(400, "Impossible de modifier votre propre rôle")

    if "nom_complet" in data: user.nom_complet = data["nom_complet"]
    if "email" in data: user.email = data["email"]
    if "role" in data and data["role"] in ROLES: user.role = data["role"]
    if "actif" in data: user.actif = data["actif"]
    if "password" in data and data["password"]:
        user.password_hash = get_password_hash(data["password"])
    db.commit()
    return {"id": str(user.id), "login": user.login, "role": user.role, "actif": user.actif}

@router.delete("/{user_id}")
def supprimer_utilisateur(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(require_admin)
):
    """Supprime un utilisateur."""
    if str(user_id) == str(current_user.id):
        raise HTTPException(400, "Impossible de supprimer votre propre compte")
    user = db.query(Utilisateur).filter(Utilisateur.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé")
    db.delete(user)
    db.commit()
    return {"message": "Utilisateur supprimé"}

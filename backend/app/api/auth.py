"""
Authentification utilisateurs.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import bcrypt

from app.core.database import get_db
from app.core.config import settings
from app.models.models import Utilisateur

router = APIRouter(tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def verifier_mot_de_passe(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

def creer_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Utilisateur).filter(Utilisateur.login == form.username).first()
    if not user or not user.actif or not verifier_mot_de_passe(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants incorrects")
    
    token = creer_token({
        "sub": user.login, 
        "role": user.role, 
        "id": str(user.id),
        "formateur_id": user.formateur_id
    })
    
    return {
        "access_token": token, 
        "token_type": "bearer", 
        "nom_complet": user.nom_complet, 
        "role": user.role,
        "formateur_id": user.formateur_id
    }

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        login: str = payload.get("sub")
        if login is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(Utilisateur).filter(Utilisateur.login == login).first()
    if user is None or not user.actif:
        raise credentials_exception
    return user

@router.get("/me")
async def get_me(current_user: Utilisateur = Depends(get_current_user)):
    return {
        "login": current_user.login, 
        "nom_complet": current_user.nom_complet, 
        "role": current_user.role, 
        "email": current_user.email,
        "formateur_id": current_user.formateur_id
    }

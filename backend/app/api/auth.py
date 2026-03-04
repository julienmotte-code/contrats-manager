from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from app.core.database import get_db
from app.core.config import settings
from app.models.models import Utilisateur

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def verifier_password(plain, hashed):
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

def creer_token(data: dict):
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

@router.post("/token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Utilisateur).filter(Utilisateur.login == form.username, Utilisateur.actif == True).first()
    if not user or not verifier_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants incorrects")
    user.derniere_connexion = datetime.utcnow()
    db.commit()
    token = creer_token({"sub": user.login, "role": user.role, "id": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "nom_complet": user.nom_complet, "role": user.role}

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        login = payload.get("sub")
        if not login:
            raise HTTPException(status_code=401, detail="Token invalide")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")
    user = db.query(Utilisateur).filter(Utilisateur.login == login).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    return user

@router.get("/me")
def me(current_user: Utilisateur = Depends(get_current_user)):
    return {"login": current_user.login, "nom_complet": current_user.nom_complet, "role": current_user.role, "email": current_user.email}

"""
Routes API — Documents générés + gestion des modèles Word
GET    /api/documents/contrat/{contrat_id}   → Liste des docs d'un contrat
POST   /api/documents/generer/{contrat_id}   → Génère le contrat Word
GET    /api/documents/telecharger/{doc_id}   → Télécharge le fichier
GET    /api/documents/modeles                → Liste les modèles
POST   /api/documents/modeles/upload         → Upload modèle (ADMIN)
PATCH  /api/documents/modeles/{id}/activer   → Active un modèle (ADMIN)
DELETE /api/documents/modeles/{id}           → Supprime un modèle (ADMIN)
"""
import uuid
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Contrat, ClientCache, DocumentGenere, ModeleDocument, Utilisateur
from app.api.auth import get_current_user
from app.services.document_service import generer_document, lister_documents_contrat, MODELES_DIR

router = APIRouter()

TYPES_VALIDES = [
    "CONTRAT_COSOLUCE", "CONTRAT_CANTINE", "CONTRAT_MAINTENANCE",
    "CONTRAT_ASSISTANCE_TEL", "CONTRAT_DIGITECH", "CONTRAT_KIWI_BACKUP",
]


@router.get("/contrat/{contrat_id}")
def liste_documents(contrat_id: str, db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    return {"data": lister_documents_contrat(contrat_id, db)}


@router.post("/generer/{contrat_id}")
def generer_contrat(contrat_id: str, db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    contrat = db.query(Contrat).filter(Contrat.id == uuid.UUID(contrat_id)).first()
    if not contrat:
        raise HTTPException(404, "Contrat introuvable")
    client = None
    if contrat.client_karlia_id:
        client = db.query(ClientCache).filter(ClientCache.karlia_id == contrat.client_karlia_id).first()
    result = generer_document(contrat=contrat, client=client, db=db, generated_by=current_user.login)
    if not result["success"]:
        raise HTTPException(500, result.get("error", "Erreur génération"))
    return {"success": True, "document_id": result["document_id"], "nom_fichier": result["nom_fichier"]}


@router.get("/telecharger/{doc_id}")
def telecharger_document(doc_id: str, db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    doc = db.query(DocumentGenere).filter(DocumentGenere.id == uuid.UUID(doc_id)).first()
    if not doc:
        raise HTTPException(404, "Document introuvable")
    chemin = Path(doc.chemin_docx)
    if not chemin.exists():
        raise HTTPException(404, "Fichier introuvable sur le serveur")
    return FileResponse(path=str(chemin), filename=doc.nom_fichier,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/modeles")
def liste_modeles(db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    modeles = db.query(ModeleDocument).order_by(ModeleDocument.type_document, ModeleDocument.uploaded_at.desc()).all()
    return {"data": [{"id": str(m.id), "type_document": m.type_document, "nom": m.nom, "version": m.version,
        "actif": m.actif, "uploaded_by": m.uploaded_by,
        "uploaded_at": m.uploaded_at.isoformat() if m.uploaded_at else None,
        "description": m.description} for m in modeles]}


@router.post("/modeles/upload")
async def uploader_modele(fichier: UploadFile = File(...), type_document: str = Form(...),
    nom: str = Form(...), version: str = Form("1.0"), description: str = Form(""),
    db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    if current_user.role != "ADMIN":
        raise HTTPException(403, "Réservé aux administrateurs")
    if type_document not in TYPES_VALIDES:
        raise HTTPException(400, f"Type invalide. Valeurs acceptées : {TYPES_VALIDES}")
    if not fichier.filename.endswith(".docx"):
        raise HTTPException(400, "Seuls les fichiers .docx sont acceptés")
    MODELES_DIR.mkdir(parents=True, exist_ok=True)
    nom_fichier = f"{type_document}_v{version.replace('.', '_')}.docx"
    chemin = MODELES_DIR / nom_fichier
    with chemin.open("wb") as f:
        shutil.copyfileobj(fichier.file, f)
    db.query(ModeleDocument).filter(ModeleDocument.type_document == type_document).update({"actif": False})
    modele = ModeleDocument(type_document=type_document, nom=nom, version=version,
        chemin_fichier=str(chemin), actif=True, uploaded_by=current_user.login, description=description)
    db.add(modele)
    db.commit()
    db.refresh(modele)
    return {"success": True, "id": str(modele.id), "message": f"Modèle '{nom}' activé pour {type_document}"}


@router.patch("/modeles/{modele_id}/activer")
def activer_modele(modele_id: str, db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    if current_user.role != "ADMIN":
        raise HTTPException(403, "Réservé aux administrateurs")
    modele = db.query(ModeleDocument).filter(ModeleDocument.id == uuid.UUID(modele_id)).first()
    if not modele:
        raise HTTPException(404, "Modèle introuvable")
    db.query(ModeleDocument).filter(ModeleDocument.type_document == modele.type_document).update({"actif": False})
    modele.actif = True
    db.commit()
    return {"success": True}


@router.delete("/modeles/{modele_id}")
def supprimer_modele(modele_id: str, db: Session = Depends(get_db), current_user: Utilisateur = Depends(get_current_user)):
    if current_user.role != "ADMIN":
        raise HTTPException(403, "Réservé aux administrateurs")
    modele = db.query(ModeleDocument).filter(ModeleDocument.id == uuid.UUID(modele_id)).first()
    if not modele:
        raise HTTPException(404, "Modèle introuvable")
    chemin = Path(modele.chemin_fichier)
    if chemin.exists():
        chemin.unlink()
    db.delete(modele)
    db.commit()
    return {"success": True}

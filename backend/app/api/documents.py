"""Routes documents - Phase 4"""
from fastapi import APIRouter
router = APIRouter()

@router.get("")
def lister_documents():
    return {"message": "Module documents disponible en Phase 4 (apres fourniture des modeles Word)"}

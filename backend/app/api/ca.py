from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_role
from app.services import ca_service

router = APIRouter(prefix="/api/ca", tags=["ca"])


@router.get("/comparatif")
def comparatif(
    date_debut: date = Query(...),
    date_fin: date = Query(...),
    n: int = Query(5, ge=1, le=15),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    if date_fin < date_debut:
        raise HTTPException(status_code=400, detail="date_fin anterieure a date_debut")
    return ca_service.calculer_comparatif(db, date_debut, date_fin, n)


@router.post("/rafraichir-karlia")
def rafraichir_karlia(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    try:
        return ca_service.rafraichir_karlia(db)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

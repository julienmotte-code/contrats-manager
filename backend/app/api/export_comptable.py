"""
Transfert comptable Sage : conversion d'un export FEC Karlia (.xlsx) en
fichier d'import Sage 100 (#MECG). Accès : ADMIN et GESTIONNAIRE.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.security import require_role
from app.services.fec_sage_service import FecIntegriteError, convertir_fec_vers_sage

logger = logging.getLogger(__name__)
router = APIRouter()
TAILLE_MAX_MO = 25


@router.post("/transfert-sage/convertir")
async def convertir_transfert_sage(
    fichier: UploadFile = File(...),
    inclure_banque: bool = Form(False),
    current_user=Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    nom = (fichier.filename or "").lower()
    if not nom.endswith(".xlsx"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Le fichier doit être un export Excel (.xlsx) de Karlia.")
    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
    if len(contenu) > TAILLE_MAX_MO * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Fichier trop volumineux (max {TAILLE_MAX_MO} Mo).")
    try:
        octets, recap = convertir_fec_vers_sage(contenu, inclure_banque=inclure_banque)
    except FecIntegriteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except Exception as exc:
        logger.exception("Erreur conversion FEC->Sage")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"Erreur interne lors de la conversion : {exc}")

    return {
        "nom_fichier": f"IMPORT_SAGE_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        "encodage": "latin-1",
        "contenu_base64": base64.b64encode(octets).decode("ascii"),
        "recap": {
            "nb_lignes": recap.nb_lignes,
            "total_debit": recap.total_debit,
            "total_credit": recap.total_credit,
            "equilibre": recap.equilibre,
            "periode_min": recap.periode_min,
            "periode_max": recap.periode_max,
            "banque_incluse": recap.banque_incluse,
            "comptes_utilises": recap.comptes_utilises,
            "journaux": [
                {"code_karlia": j.code_karlia, "code_sage": j.code_sage,
                 "nb_ecritures": j.nb_ecritures, "total_debit": j.total_debit,
                 "total_credit": j.total_credit}
                for j in recap.journaux
            ],
        },
    }

"""
Service Chorus Pro — voie de transmission "dépôt de flux".

Cette voie est utilisée à la place de `soumettre` (API REST JSON V5.01)
car les endpoints de consultation et structures sont bloqués 403 pour
la configuration actuelle de SGI. `deposer/flux` est en revanche ouvert
et permet le dépôt d'un Factur-X (PDF/A-3 avec XML CII embarqué).

Endpoints couverts :
  - POST /cpro/factures/v1/deposer/flux          → deposerFluxFacture
  - POST /cpro/factures/v1/consulter/compteRendu → consulterCRDetailleParNumeroFluxDepot

Auth : on réutilise une instance `ChorusProService` existante pour
mutualiser l'obtention du token OAuth2 (cache) et le calcul du header
`cpro-account`. Aucune logique d'authentification dupliquée ici.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from app.services.chorus_service import ChorusError, ChorusProService

logger = logging.getLogger(__name__)


# Syntaxe officielle Chorus Pro pour Factur-X (PDF/A-3 + XML CII embarqué)
SYNTAXE_FACTURX = "IN_DP_E2_CII_FACTURX"

# Endpoints relatifs au base_url Factures V1 (ChorusProService.api_url)
ENDPOINT_DEPOSER_FLUX = "/deposer/flux"
ENDPOINT_CONSULTER_CR = "/consulter/compteRendu"


@dataclass
class DepotFluxResult:
    """Résultat d'un dépôt /deposer/flux."""
    code_retour: Optional[int]
    libelle: Optional[str]
    numero_flux_depot: Optional[str]
    date_depot: Optional[str]
    syntaxe_flux: Optional[str]
    raw: Dict[str, Any]


@dataclass
class CompteRenduResult:
    """Résultat d'un /consulter/compteRendu pour un numéroFluxDepot."""
    code_retour: Optional[int]
    libelle: Optional[str]
    statut: Optional[str]                 # ex. "IN_INTEGRE" / "IN_REJETE" / "EN_COURS"
    date_traitement: Optional[str]
    raw: Dict[str, Any]


class ChorusFluxService:
    """
    Client minimal pour la voie 'dépôt de flux' Chorus Pro.

    Cycle de vie :
        svc = ChorusFluxService(chorus_pro_service)
        result = await svc.deposer_flux(pdf_bytes, "facture_8906.pdf")
        # plus tard, lecture du CR :
        cr = await svc.consulter_cr(result.numero_flux_depot)
    """

    def __init__(self, chorus_pro_service: ChorusProService):
        if chorus_pro_service is None:
            raise ValueError("chorus_pro_service requis")
        self._svc = chorus_pro_service

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _build_headers(self) -> Dict[str, str]:
        token = await self._svc._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "cpro-account": self._svc._cpro_account_header(),
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
        }

    def _url(self, endpoint: str) -> str:
        # ChorusProService.api_url = https://.../cpro/factures/v1
        return f"{self._svc.api_url}{endpoint}"

    @staticmethod
    def _safe_dict(maybe_json: Any) -> Dict[str, Any]:
        return maybe_json if isinstance(maybe_json, dict) else {}

    # ── deposer/flux ──────────────────────────────────────────────────────

    async def deposer_flux(
        self,
        pdf_bytes: bytes,
        nom_fichier: str,
        syntaxe_flux: str = SYNTAXE_FACTURX,
    ) -> DepotFluxResult:
        """
        Dépose un flux Factur-X (PDF/A-3 + XML CII) auprès de Chorus Pro.

        Args:
            pdf_bytes   : contenu du PDF Factur-X final.
            nom_fichier : nom logique du fichier (extension .pdf attendue).
            syntaxe_flux: identifiant Chorus Pro de la syntaxe — par défaut
                          IN_DP_E2_CII_FACTURX (Factur-X).

        Returns:
            DepotFluxResult avec numero_flux_depot et date_depot exploitables
            ensuite via `consulter_cr`.

        Raises:
            ChorusError si HTTP != 200 ou si la réponse est inutilisable.
        """
        if not pdf_bytes:
            raise ValueError("pdf_bytes vide")
        if not nom_fichier:
            raise ValueError("nom_fichier vide")

        body = {
            "fichierFlux": base64.b64encode(pdf_bytes).decode("ascii"),
            "nomFichier": nom_fichier,
            "syntaxeFlux": syntaxe_flux,
        }
        headers = await self._build_headers()
        url = self._url(ENDPOINT_DEPOSER_FLUX)

        logger.info(
            "Chorus Pro deposer/flux : %d bytes (b64=%d), nom=%s, syntaxe=%s",
            len(pdf_bytes), len(body["fichierFlux"]), nom_fichier, syntaxe_flux,
        )

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            logger.error(
                "deposer/flux HTTP %s : %r (correlation=%s)",
                response.status_code, response.text, response.headers.get("x-correlationid"),
            )
            raise ChorusError(
                response.status_code,
                "Échec dépôt flux Chorus Pro",
                {
                    "x-correlationid": response.headers.get("x-correlationid"),
                    "body": response.text,
                },
            )

        try:
            data = response.json()
        except Exception as exc:
            raise ChorusError(200, f"Réponse deposer/flux non-JSON : {exc}", {"body": response.text})

        result = DepotFluxResult(
            code_retour=data.get("codeRetour"),
            libelle=data.get("libelle"),
            numero_flux_depot=str(data.get("numeroFluxDepot")) if data.get("numeroFluxDepot") is not None else None,
            date_depot=data.get("dateDepot"),
            syntaxe_flux=data.get("syntaxeFlux"),
            raw=self._safe_dict(data),
        )
        logger.info(
            "Chorus Pro deposer/flux OK : codeRetour=%s, numeroFluxDepot=%s, dateDepot=%s",
            result.code_retour, result.numero_flux_depot, result.date_depot,
        )
        return result

    # ── consulter/compteRendu ─────────────────────────────────────────────

    async def consulter_cr(self, numero_flux_depot: str) -> CompteRenduResult:
        """
        Consulte le compte rendu détaillé d'un flux déposé.

        Args:
            numero_flux_depot: identifiant retourné par `deposer_flux`.

        Returns:
            CompteRenduResult avec le statut d'intégration côté Chorus Pro.
            Le statut effectif (IN_INTEGRE / IN_REJETE / EN_COURS / ...) est
            disponible dans le champ `statut` ou dans `raw` selon le profil.
        """
        if not numero_flux_depot:
            raise ValueError("numero_flux_depot vide")

        body = {"numeroFluxDepot": str(numero_flux_depot)}
        headers = await self._build_headers()
        url = self._url(ENDPOINT_CONSULTER_CR)

        logger.info("Chorus Pro consulter/CR : numeroFluxDepot=%s", numero_flux_depot)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            logger.error(
                "consulter/CR HTTP %s : %r (correlation=%s)",
                response.status_code, response.text, response.headers.get("x-correlationid"),
            )
            raise ChorusError(
                response.status_code,
                "Échec consultation compte rendu Chorus Pro",
                {
                    "x-correlationid": response.headers.get("x-correlationid"),
                    "body": response.text,
                },
            )

        try:
            data = response.json()
        except Exception as exc:
            raise ChorusError(200, f"Réponse consulter/CR non-JSON : {exc}", {"body": response.text})

        # Le champ statut Chorus Pro peut s'appeler 'statutFlux', 'statut', ou
        # vivre dans une sous-structure. On expose le plus probable et on
        # laisse l'appelant inspecter raw pour les cas exotiques.
        statut = (
            data.get("statutFlux")
            or data.get("statut")
            or (data.get("etatTraitement") if isinstance(data.get("etatTraitement"), str) else None)
        )
        result = CompteRenduResult(
            code_retour=data.get("codeRetour"),
            libelle=data.get("libelle"),
            statut=statut,
            date_traitement=data.get("dateTraitement") or data.get("dateDernierStatut"),
            raw=self._safe_dict(data),
        )
        logger.info(
            "Chorus Pro consulter/CR OK : codeRetour=%s, statut=%s",
            result.code_retour, result.statut,
        )
        return result

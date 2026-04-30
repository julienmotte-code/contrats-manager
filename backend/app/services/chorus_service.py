"""
Service d'intégration Chorus Pro via API PISTE
Gère l'authentification OAuth2 et la soumission de factures
"""
import httpx
import base64
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, date, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

# URLs des environnements
PISTE_SANDBOX_OAUTH = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
PISTE_PROD_OAUTH = "https://oauth.piste.gouv.fr/api/oauth/token"

CHORUS_SANDBOX_API = "https://sandbox-api.piste.gouv.fr/cpro/factures/v1"
CHORUS_PROD_API = "https://api.piste.gouv.fr/cpro/factures/v1"

CHORUS_SANDBOX_TRANSVERSES = "https://sandbox-api.piste.gouv.fr/cpro/transverses/v1"
CHORUS_PROD_TRANSVERSES = "https://api.piste.gouv.fr/cpro/transverses/v1"


class ChorusError(Exception):
    """Erreur retournée par l'API Chorus Pro"""
    def __init__(self, status_code: int, message: str, detail: dict = None):
        self.status_code = status_code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"Chorus Pro API {status_code}: {message}")


class ChorusProService:
    """
    Client pour l'API Chorus Pro via PISTE.
    Utilise OAuth2 pour l'authentification.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tech_username: str,
        tech_password: str,
        siret_emetteur: str,
        code_service: str = None,
        code_banque: str = None,
        id_fournisseur: str = None,
        id_utilisateur_courant: str = None,
        mode_qualification: bool = True
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tech_username = tech_username
        self.tech_password = tech_password
        self.siret_emetteur = siret_emetteur
        self.code_service = code_service
        self.code_banque = code_banque
        self.id_fournisseur = id_fournisseur
        self.id_utilisateur_courant = id_utilisateur_courant
        self.mode_qualification = mode_qualification

        # Sélection des URLs selon l'environnement
        if mode_qualification:
            self.oauth_url = PISTE_SANDBOX_OAUTH
            self.api_url = CHORUS_SANDBOX_API
            self.transverses_url = CHORUS_SANDBOX_TRANSVERSES
        else:
            self.oauth_url = PISTE_PROD_OAUTH
            self.api_url = CHORUS_PROD_API
            self.transverses_url = CHORUS_PROD_TRANSVERSES

        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None

        # Diagnostic : dernière requête / réponse Chorus (hors OAuth), pour traçage en BDD
        self.last_request: Optional[Dict[str, Any]] = None
        self.last_response: Optional[Dict[str, Any]] = None

    def _record_exchange(self, method: str, url: str, headers: dict, body: Any, response: Optional[httpx.Response]) -> None:
        """Stocke le détail d'un échange Chorus pour traçage."""
        safe_headers = {k: v for k, v in headers.items()}
        for sensitive in ("Authorization", "authorization", "cpro-account"):
            if sensitive in safe_headers:
                val = safe_headers[sensitive]
                safe_headers[sensitive] = (val[:12] + "…" + val[-6:]) if len(val) > 24 else "…"
        self.last_request = {
            "method": method,
            "url": url,
            "headers": safe_headers,
            "body": body,
        }
        if response is None:
            self.last_response = None
            return
        try:
            body_text = response.text
        except Exception:
            body_text = None
        self.last_response = {
            "status": response.status_code,
            "reason": response.reason_phrase,
            "headers": dict(response.headers),
            "body_raw": body_text,
            "x_correlation_id": response.headers.get("x-correlationid"),
        }

    def _cpro_account_header(self) -> str:
        """Encode le compte technique pour le header `cpro-account` exigé par Chorus Pro."""
        raw = f"{self.tech_username}:{self.tech_password}".encode()
        return base64.b64encode(raw).decode()

    async def _get_access_token(self) -> str:
        """Obtient un token OAuth2 via PISTE."""
        # Vérifier si le token est encore valide
        if self._access_token and self._token_expires:
            if datetime.now() < self._token_expires:
                return self._access_token

        # Credentials en Base64
        credentials = base64.b64encode(
            f"{self.tech_username}:{self.tech_password}".encode()
        ).decode()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.oauth_url,
                data={
                    "grant_type": "client_credentials",
                    "scope": "openid",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {credentials}",
                },
                auth=(self.client_id, self.client_secret)
            )

            if response.status_code != 200:
                logger.error(f"Erreur OAuth Chorus: {response.status_code} - {response.text}")
                raise ChorusError(
                    response.status_code,
                    "Échec de l'authentification OAuth",
                    {"response": response.text}
                )

            data = response.json()
            self._access_token = data["access_token"]
            # Token valide 1 heure, on garde une marge de 5 minutes
            expires_in = data.get("expires_in", 3600) - 300
            self._token_expires = datetime.now() + timedelta(seconds=expires_in)

            logger.info("Token OAuth Chorus Pro obtenu avec succès")
            return self._access_token

    def _client(self) -> httpx.AsyncClient:
        """Client HTTP configuré."""
        return httpx.AsyncClient(
            base_url=self.api_url,
            timeout=60.0,
        )

    async def _post(self, endpoint: str, data: dict) -> dict:
        """Requête POST authentifiée."""
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "cpro-account": self._cpro_account_header(),
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
        }

        async with self._client() as client:
            response = None
            try:
                response = await client.post(endpoint, json=data, headers=headers)
            finally:
                self._record_exchange("POST", f"{self.api_url}{endpoint}", headers, data, response)

            if response.status_code == 200:
                return response.json()

            logger.error(f"Erreur Chorus {endpoint}: {response.status_code} - {response.text!r}")
            try:
                detail = response.json()
                message = detail.get("libelle") or detail.get("message") or f"Erreur sur {endpoint}"
            except Exception:
                detail = {"raw": response.text}
                if response.status_code == 400 and not response.text.strip():
                    message = (
                        f"Erreur sur {endpoint} — réponse 400 vide de PISTE. "
                        "Cause probable : champ requis manquant ou null dans le payload "
                        "(typiquement idFournisseur ou idUtilisateurCourant)."
                    )
                elif response.status_code == 403 and not response.text.strip():
                    correl = response.headers.get("x-correlationid")
                    message = (
                        f"Erreur sur {endpoint} — 403 vide de PISTE "
                        f"(x-correlationid={correl}). Causes typiques : souscription PISTE inactive, "
                        "scope manquant, IP non autorisée, ou en-tête cpro-account refusé."
                    )
                else:
                    message = f"Erreur sur {endpoint}"
            raise ChorusError(response.status_code, message, detail)

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        """Requête GET authentifiée."""
        token = await self._get_access_token()

        async with self._client() as client:
            response = await client.get(
                endpoint,
                params=params or {},
                headers={
                    "Authorization": f"Bearer {token}",
                    "cpro-account": self._cpro_account_header(),
                    "Accept": "application/json",
                }
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Erreur Chorus {endpoint}: {response.status_code}")
                raise ChorusError(response.status_code, f"Erreur sur {endpoint}")

    async def tester_connexion(self) -> dict:
        """Teste la connexion à Chorus Pro."""
        try:
            await self._get_access_token()
            return {
                "ok": True,
                "message": "Connexion OAuth réussie",
                "mode": "qualification" if self.mode_qualification else "production"
            }
        except ChorusError as e:
            return {"ok": False, "error": str(e), "detail": e.detail}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def rechercher_structure_destinataire(self, siret: str) -> dict:
        """
        Recherche une structure destinataire par SIRET.
        Retourne les informations de la structure (id, services, etc.)
        """
        data = {
            "typeIdentifiantStructure": "SIRET",
            "identifiantStructure": siret,
            "statutStructure": "ACTIF"
        }
        return await self._post("/rechercher/structures", data)

    async def consulter_structure(self, id_structure: int) -> dict:
        """Consulte les détails d'une structure par son ID Chorus."""
        return await self._post("/consulter/structure", {"idStructure": id_structure})

    async def rechercher_services_structure(self, id_structure: int) -> dict:
        """Récupère les services d'une structure (codes services)."""
        return await self._post("/rechercher/services", {"idStructure": id_structure})

    async def soumettre_facture(
        self,
        destinataire_siret: str,
        destinataire_code_service: str = None,
        numero_facture: str = "",
        date_facture: date = None,
        date_echeance: date = None,
        montant_ht: Decimal = Decimal("0"),
        montant_tva: Decimal = Decimal("0"),
        montant_ttc: Decimal = Decimal("0"),
        lignes: List[Dict] = None,
        numero_engagement: str = None,
        numero_marche: str = None,
        commentaire: str = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Soumet une facture à Chorus Pro.

        Args:
            destinataire_siret: SIRET de la collectivité destinataire
            destinataire_code_service: Code service optionnel
            numero_facture: Numéro de la facture (généré si vide)
            date_facture: Date d'émission
            date_echeance: Date d'échéance
            montant_ht: Montant HT total
            montant_tva: Montant TVA total
            montant_ttc: Montant TTC total
            lignes: Liste des lignes de facture
            numero_engagement: Numéro d'engagement juridique (optionnel)
            numero_marche: Numéro de marché (optionnel)
            commentaire: Commentaire libre

        Returns:
            Réponse de l'API avec identifiant de flux
        """
        if date_facture is None:
            date_facture = date.today()

        if not self.id_fournisseur:
            raise ChorusError(
                0,
                "idFournisseur manquant — paramètre 'chorus_id_fournisseur' vide en base. "
                "Renseignez-le via l'écran Paramètres ou appelez POST /api/chorus/auto-config "
                "pour le récupérer automatiquement depuis Chorus Pro.",
                {"missing_param": "chorus_id_fournisseur"}
            )

        # Construction du payload selon le format Chorus Pro
        lignes_poste = []
        if lignes:
            for i, ligne in enumerate(lignes, 1):
                lignes_poste.append({
                    "lignePosteNumero": i,
                    "lignePosteReference": ligne.get("reference", f"L{i}"),
                    "lignePosteDenomination": ligne.get("designation", "Article"),
                    "lignePosteQuantite": float(ligne.get("quantite", 1)),
                    "lignePosteUnite": ligne.get("unite", "lot"),
                    "lignePosteMontantUnitaireHT": float(ligne.get("prix_unitaire_ht", 0)),
                    "lignePosteMontantRemiseHT": 0,
                    "lignePosteTauxTva": None,
                    "lignePosteTauxTvaManuel": float(ligne.get("taux_tva", 20)),
                })
        else:
            # Ligne unique par défaut
            lignes_poste.append({
                "lignePosteNumero": 1,
                "lignePosteReference": "GLOBAL",
                "lignePosteDenomination": commentaire or "Prestation de service",
                "lignePosteQuantite": 1,
                "lignePosteUnite": "lot",
                "lignePosteMontantUnitaireHT": float(montant_ht),
                "lignePosteMontantRemiseHT": 0,
                "lignePosteTauxTva": None,
                "lignePosteTauxTvaManuel": 20.0,
            })

        fournisseur_payload = {
            "idFournisseur": int(self.id_fournisseur) if self.id_fournisseur else None,
            "idServiceFournisseur": int(self.code_service) if self.code_service else None,
            "codeCoordonneesBancairesFournisseur": int(self.code_banque) if self.code_banque else None,
        }

        payload = {
            "modeDepot": "SAISIE_API",
            "numeroFactureSaisi": numero_facture or None,
            "dateFacture": date_facture.strftime("%Y-%m-%d"),
            "commentaire": commentaire,
            "destinataire": {
                "codeDestinataire": destinataire_siret,
            },
            "fournisseur": fournisseur_payload,
            "cadreDeFacturation": {
                "codeCadreFacturation": "A1_FACTURE_FOURNISSEUR",
                "codeStructureValideur": None,
            },
            "references": {
                "deviseFacture": "EUR",
                "typeFacture": "FACTURE",
                "typeTva": "TVA_SUR_DEBIT",
                "motifExonerationTva": None,
                "numeroMarche": numero_marche,
                "numeroEngagement": numero_engagement,
                "numeroBonCommande": None,
                "numeroFactureOrigine": None,
                "modePaiement": "VIREMENT",
            },
            "lignePoste": lignes_poste,
            "ligneTva": [
                {
                    "ligneRecapTvaTauxManuel": 20.0,
                    "ligneRecapTvaMontantBaseHtParTaux": float(montant_ht),
                    "ligneRecapTvaMontantTvaParTaux": float(montant_tva),
                }
            ],
            "montantTotal": {
                "montantHtTotal": float(montant_ht),
                "montantTvaTotal": float(montant_tva),
                "montantTtcTotal": float(montant_ttc),
                "montantRemiseGlobaleTTC": 0,
                "motifRemiseGlobaleTTC": None,
                "montantAPayer": float(montant_ttc),
                "montantAcompte": 0,
            },
        }

        if destinataire_code_service:
            payload["destinataire"]["codeServiceExecutant"] = destinataire_code_service

        if self.id_utilisateur_courant:
            payload["idUtilisateurCourant"] = int(self.id_utilisateur_courant)

        if dry_run:
            self.last_request = {
                "method": "POST",
                "url": f"{self.api_url}/soumettre",
                "headers": {"<dry_run>": "aucune requête HTTP n'a été envoyée"},
                "body": payload,
            }
            self.last_response = {"status": None, "body_raw": None, "x_correlation_id": None, "note": "dry-run"}
            return {"dry_run": True, "payload": payload}

        logger.info(f"Soumission facture Chorus Pro: {numero_facture} → {destinataire_siret}")
        logger.debug(f"Payload Chorus /soumettre: {payload}")
        return await self._post("/soumettre", payload)

    async def recuperer_utilisateur_courant(self) -> dict:
        """
        Récupère idUtilisateurCourant + structure courante via le module transverses.
        Utilisé pour auto-configurer idFournisseur et idUtilisateurCourant.
        """
        token = await self._get_access_token()
        endpoint = "/recuperer/utilisateurCourant"
        headers = {
            "Authorization": f"Bearer {token}",
            "cpro-account": self._cpro_account_header(),
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(base_url=self.transverses_url, timeout=30.0) as client:
            response = None
            try:
                response = await client.post(endpoint, json={}, headers=headers)
            finally:
                self._record_exchange("POST", f"{self.transverses_url}{endpoint}", headers, {}, response)

            if response.status_code != 200:
                logger.error(f"Erreur recuperer/utilisateurCourant: {response.status_code} - {response.text!r}")
                try:
                    detail = response.json()
                except Exception:
                    detail = {"raw": response.text}
                correl = response.headers.get("x-correlationid")
                raise ChorusError(
                    response.status_code,
                    f"Échec récupération utilisateur courant (x-correlationid={correl})",
                    detail,
                )
            return response.json()

    async def consulter_statut_facture(self, id_facture: str) -> dict:
        """Consulte le statut d'une facture soumise."""
        return await self._post("/consulter/facture", {"idFacture": id_facture})

    async def rechercher_factures_emises(
        self,
        date_debut: date = None,
        date_fin: date = None,
        statut: str = None
    ) -> dict:
        """Recherche les factures émises."""
        data = {
            "typeIdentifiantStructure": "SIRET",
            "identifiantStructure": self.siret_emetteur,
        }
        if date_debut:
            data["dateDepotDebut"] = date_debut.strftime("%Y-%m-%d")
        if date_fin:
            data["dateDepotFin"] = date_fin.strftime("%Y-%m-%d")
        if statut:
            data["statutFacture"] = statut

        return await self._post("/rechercher/factures/fournisseur", data)


def get_chorus_service_from_params(params: Dict[str, str]) -> Optional[ChorusProService]:
    """
    Crée un service Chorus Pro à partir des paramètres en base.
    Retourne None si la configuration est incomplète.
    """
    required = ['chorus_client_id', 'chorus_client_secret',
                'chorus_tech_username', 'chorus_tech_password', 'chorus_siret_emetteur']

    for key in required:
        if not params.get(key):
            logger.warning(f"Paramètre Chorus Pro manquant: {key}")
            return None

    return ChorusProService(
        client_id=params['chorus_client_id'],
        client_secret=params['chorus_client_secret'],
        tech_username=params['chorus_tech_username'],
        tech_password=params['chorus_tech_password'],
        siret_emetteur=params['chorus_siret_emetteur'],
        code_service=params.get('chorus_code_service'),
        code_banque=params.get('chorus_code_banque'),
        id_fournisseur=params.get('chorus_id_fournisseur'),
        id_utilisateur_courant=params.get('chorus_id_utilisateur_courant'),
        mode_qualification=params.get('chorus_mode_qualification', 'true').lower() == 'true'
    )

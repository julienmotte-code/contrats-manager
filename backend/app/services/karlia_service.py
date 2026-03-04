"""
Service d'intégration Karlia API v2
Toutes les interactions avec Karlia passent par cette classe.
La clé API n'est jamais exposée côté frontend.
"""
import httpx
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from app.core.config import settings

logger = logging.getLogger(__name__)

KARLIA_BASE = settings.KARLIA_API_URL


class KarliaError(Exception):
    """Erreur retournée par l'API Karlia"""
    def __init__(self, status_code: int, message: str, detail: dict = None):
        self.status_code = status_code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"Karlia API {status_code}: {message}")


class KarliaService:
    """
    Client HTTP pour l'API Karlia.
    Utilise httpx en mode async pour les performances (traitements en lot).
    """

    def __init__(self):
        self.api_key = settings.KARLIA_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=KARLIA_BASE,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        """Requête GET générique avec gestion d'erreurs."""
        async with self._client() as client:
            response = await client.get(endpoint, params=params or {})
            return self._handle_response(response, endpoint)

    async def _post(self, endpoint: str, data: dict) -> dict:
        """Requête POST générique avec gestion d'erreurs."""
        async with self._client() as client:
            response = await client.post(endpoint, json=data)
            return self._handle_response(response, endpoint)

    def _handle_response(self, response: httpx.Response, endpoint: str) -> dict:
        """Analyse la réponse Karlia et lève une exception claire si erreur."""
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            raise KarliaError(401, "Clé API Karlia invalide ou expirée", {"endpoint": endpoint})
        elif response.status_code == 429:
            raise KarliaError(429, "Quota API Karlia dépassé (100 req/min)", {"endpoint": endpoint})
        else:
            try:
                detail = response.json()
            except Exception:
                detail = {"raw": response.text}
            raise KarliaError(response.status_code, f"Erreur Karlia sur {endpoint}", detail)

    # ─────────────────────────────────────────────
    # CLIENTS
    # ─────────────────────────────────────────────

    async def lister_clients(
        self,
        recherche: str = None,
        limit: int = 100,
        offset: int = 0
    ) -> dict:
        """
        Liste les clients Karlia.
        Retourne : { total, data: [{ id, client_number, title, email, address_list, ... }] }
        """
        params = {"limit": limit, "offset": offset, "archived": 0}
        if recherche:
            params["quick_search"] = recherche
        return await self._get("/customers", params)

    async def obtenir_client(self, karlia_id: str) -> dict:
        """Récupère un client Karlia par son ID."""
        return await self._get(f"/customers/{karlia_id}")

    async def creer_client(self, data: dict) -> dict:
        """
        Crée un client dans Karlia.
        Le champ client_number (numéro personnalisé) est inclus dans data.
        Retourne le client créé avec son id Karlia.
        """
        logger.info(f"Création client Karlia : {data.get('name')}")
        return await self._post("/customers", data)

    async def dernier_numero_client(self) -> int:
        """
        Récupère le numéro incrémental le plus élevé chez Karlia.
        Utilisé pour reprendre la séquence de numérotation.
        Retourne l'entier numérique (ex: 47 si le dernier est DUP047).
        """
        result = await self._get("/customers", {
            "limit": 1,
            "order": "creation_date",
            "direction": "DESC",
            "fields": "client_number",
            "archived": 0,
        })
        # Récupère tous les numéros et extrait la partie numérique
        all_clients = await self._get("/customers", {"limit": 500, "fields": "client_number", "archived": 0})
        max_num = 0
        for c in all_clients.get("data", []):
            num_str = c.get("client_number", "")
            # Extrait les chiffres en fin de chaîne (ex: "DUP047" → 47)
            digits = ''.join(filter(str.isdigit, num_str))
            if digits:
                max_num = max(max_num, int(digits))
        return max_num

    # ─────────────────────────────────────────────
    # PRODUITS / ARTICLES
    # ─────────────────────────────────────────────

    async def lister_produits(self, recherche: str = None, limit: int = 200) -> dict:
        """
        Liste les articles/produits du catalogue Karlia.
        Retourne : { data: [{ id, reference, title, sell_price, ... }] }
        """
        params = {"limit": limit}
        if recherche:
            params["quick_search"] = recherche
        return await self._get("/products", params)

    async def obtenir_produit(self, karlia_id: str) -> dict:
        """Récupère un produit par son ID Karlia."""
        return await self._get(f"/products/{karlia_id}")

    async def obtenir_prix_vente(self, karlia_id: str) -> dict:
        """Récupère le prix de vente d'un produit."""
        return await self._get(f"/products/{karlia_id}/sell-price")

    # ─────────────────────────────────────────────
    # DOCUMENTS (Factures dans Karlia)
    # ─────────────────────────────────────────────

    async def lister_types_documents(self) -> dict:
        """
        Liste les types de documents disponibles dans Karlia.
        Permet d'identifier le bon type pour 'facture'.
        """
        return await self._get("/documents", {"limit": 1})

    async def creer_facture(
        self,
        client_karlia_id: str,
        lignes: List[Dict],
        reference_contrat: str,
        date_echeance: date,
        montant_ht: float,
        description: str = "",
    ) -> dict:
        """
        Crée une facture dans Karlia via l'endpoint Documents.

        Args:
            client_karlia_id: ID du client dans Karlia
            lignes: Liste des lignes de facture [{id_product, quantity, unit_price, ...}]
            reference_contrat: Numéro du contrat (référence interne)
            date_echeance: Date d'échéance de la facture
            montant_ht: Montant HT total
            description: Description de la facture

        Returns:
            Document créé dans Karlia avec son id et sa référence
        """
        # Convertir les lignes au format Karlia
        products_list = []
        for ligne in lignes:
            tva = ligne.get("vat_rate", 20.0)
            # id_vat: 1=20%, 2=10%, 3=5.5%, 4=0%
            if tva >= 20: id_vat = "1"
            elif tva >= 10: id_vat = "2"
            elif tva >= 5: id_vat = "3"
            else: id_vat = "4"
            p = {
                "description": ligne.get("description", ""),
                "price_without_tax": ligne.get("unit_price", 0),
                "quantity": ligne.get("quantity", 1),
                "id_vat": id_vat,
            }
            if ligne.get("id_product"):
                p["id_product"] = ligne["id_product"]
            products_list.append(p)

        payload = {
            "id_customer": int(client_karlia_id),
            "id_type": 4,                              # 4 = Facture dans Karlia
            "id_status": 2,                            # 2 = Envoyée (directement émise)
            "reference": reference_contrat,
            "date": datetime.now().strftime("%d/%m/%Y"),
            "date_end": date_echeance.strftime("%d/%m/%Y"),
            "description": description or f"Facturation annuelle — Contrat {reference_contrat}",
            "products_list": products_list,
        }
        logger.info(f"Création facture Karlia pour contrat {reference_contrat}, client {client_karlia_id}")
        return await self._post("/documents", payload)

    async def obtenir_document(self, doc_id: str) -> dict:
        """Récupère un document Karlia (facture, devis...) par son ID."""
        return await self._get(f"/documents/{doc_id}")

    async def lister_templates_documents(self) -> dict:
        """Liste les templates de documents disponibles dans Karlia."""
        return await self._get("/documents/templates")

    # ─────────────────────────────────────────────
    # UTILITAIRES
    # ─────────────────────────────────────────────

    async def tester_connexion(self) -> dict:
        """
        Teste que la clé API fonctionne.
        Retourne un dict avec statut et infos company.
        """
        try:
            result = await self._get("/company")
            return {"ok": True, "company": result}
        except KarliaError as e:
            return {"ok": False, "error": str(e)}

    async def traitement_lot_factures(
        self,
        factures: List[Dict],
        delai_entre_requetes: float = 0.8,
    ) -> List[Dict]:
        """
        Émet plusieurs factures en lot avec respect du quota API (100 req/min).
        Traite les factures une par une avec un délai, journalise chaque résultat.

        Args:
            factures: Liste de dicts avec les paramètres de chaque facture
            delai_entre_requetes: Secondes entre chaque appel (0.8s = ~75 req/min, sous le quota)

        Returns:
            Liste de résultats : [{ contrat_id, succes, karlia_id, erreur }]
        """
        resultats = []
        for i, f in enumerate(factures):
            try:
                logger.info(f"Lot factures : traitement {i+1}/{len(factures)} — contrat {f.get('reference_contrat')}")
                doc = await self.creer_facture(
                    client_karlia_id=f["client_karlia_id"],
                    lignes=f["lignes"],
                    reference_contrat=f["reference_contrat"],
                    date_echeance=f["date_echeance"],
                    montant_ht=f["montant_ht"],
                    description=f.get("description", ""),
                )
                resultats.append({
                    "plan_id": f.get("plan_id"),
                    "contrat_id": f.get("contrat_id"),
                    "succes": True,
                    "karlia_doc_id": doc.get("id"),
                    "karlia_doc_ref": doc.get("reference", doc.get("number", "")),
                    "erreur": None,
                })
            except KarliaError as e:
                resultats.append({
                    "plan_id": f.get("plan_id"),
                    "contrat_id": f.get("contrat_id"),
                    "succes": False,
                    "karlia_doc_id": None,
                    "karlia_doc_ref": None,
                    "erreur": e.message,
                })
                logger.error(f"Erreur facture contrat {f.get('reference_contrat')} : {e}")
                print(f"[ERREUR FACTURE] detail={e.detail} payload={f}", flush=True)

            # Respecter le quota : pause entre chaque requête
            if i < len(factures) - 1:
                await asyncio.sleep(delai_entre_requetes)

        logger.info(f"Lot terminé : {sum(r['succes'] for r in resultats)}/{len(resultats)} succès")
        return resultats


# Instance singleton utilisée dans toute l'application
karlia = KarliaService()

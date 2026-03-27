"""
Service de synchronisation des devis acceptés depuis Karlia.
"""
import httpx
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Commande, CommandeLigne, Parametre

logger = logging.getLogger(__name__)

KARLIA_TYPE_DEVIS = 1
KARLIA_STATUS_DEVIS_ACCEPTE = 3
KARLIA_STATUS_DEVIS_SIGNE = 4


class KarliaDevisService:
    def __init__(self):
        self.base_url = settings.KARLIA_API_URL.rstrip('/')
        self.api_key = self._get_api_key_from_db()
    
    def _get_api_key_from_db(self) -> str:
        db = SessionLocal()
        try:
            param = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
            return param.valeur if param and param.valeur else ""
        finally:
            db.close()
    
    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _get_derniere_synchro(self, db: Session) -> Optional[datetime]:
        param = db.query(Parametre).filter(Parametre.cle == "derniere_synchro_devis").first()
        if param and param.valeur:
            try:
                return datetime.fromisoformat(param.valeur)
            except ValueError:
                return None
        return None
    
    def _set_derniere_synchro(self, db: Session, date_synchro: datetime):
        param = db.query(Parametre).filter(Parametre.cle == "derniere_synchro_devis").first()
        if param:
            param.valeur = date_synchro.isoformat()
        else:
            param = Parametre(cle="derniere_synchro_devis", valeur=date_synchro.isoformat())
            db.add(param)
        db.commit()
    
    async def get_devis_acceptes(self, depuis_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        devis_acceptes = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for status in [KARLIA_STATUS_DEVIS_ACCEPTE, KARLIA_STATUS_DEVIS_SIGNE]:
                page = 1
                has_more = True
                while has_more:
                    params = {
                        "id_type": KARLIA_TYPE_DEVIS,
                        "id_status": status,
                        "page": page,
                        "per_page": 50
                    }
                    if depuis_date:
                        params["updated_after"] = depuis_date.strftime("%Y-%m-%d")
                    
                    try:
                        response = await client.get(
                            f"{self.base_url}/documents",
                            headers=self._get_headers(),
                            params=params
                        )
                        response.raise_for_status()
                        data = response.json()
                        documents = data.get("data", data) if isinstance(data, dict) else data
                        if isinstance(documents, list):
                            devis_acceptes.extend(documents)
                            has_more = len(documents) == 50
                            page += 1
                        else:
                            has_more = False
                    except httpx.HTTPError as e:
                        logger.error(f"Erreur API Karlia: {e}")
                        has_more = False
        
        return devis_acceptes
    
    async def get_devis_detail(self, document_id: int) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/documents/{document_id}",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(f"Erreur détail devis {document_id}: {e}")
                return None
    
    async def get_devis_pdf(self, document_id: int) -> Optional[Tuple[bytes, str]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/documents/{document_id}/download",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                content_disp = response.headers.get("Content-Disposition", "")
                filename = f"devis_{document_id}.pdf"
                if "filename=" in content_disp:
                    filename = content_disp.split("filename=")[1].strip('"')
                return (response.content, filename)
            except httpx.HTTPError as e:
                logger.error(f"Erreur PDF devis {document_id}: {e}")
                return None
    
    async def get_customer_detail(self, customer_id: int) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/customers/{customer_id}",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(f"Erreur client {customer_id}: {e}")
                return None
    
    def _parse_karlia_date(self, date_str: Optional[str]) -> Optional[date]:
        if not date_str:
            return None
        try:
            if "/" in date_str:
                return datetime.strptime(date_str, "%d/%m/%Y").date()
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None
    
    def _format_address(self, customer_data: Dict[str, Any]) -> str:
        parts = []
        if customer_data.get("address"):
            parts.append(customer_data["address"])
        if customer_data.get("address2"):
            parts.append(customer_data["address2"])
        city_parts = []
        if customer_data.get("zip_code"):
            city_parts.append(customer_data["zip_code"])
        if customer_data.get("city"):
            city_parts.append(customer_data["city"])
        if city_parts:
            parts.append(" ".join(city_parts))
        return "\n".join(parts)
    
    def _parse_tva(self, tva_value: Any) -> Optional[float]:
        if tva_value is None:
            return None
        tva_map = {"1": 20.0, "2": 10.0, "3": 5.5, "4": 0.0, 1: 20.0, 2: 10.0, 3: 5.5, 4: 0.0}
        if tva_value in tva_map:
            return tva_map[tva_value]
        try:
            return float(tva_value)
        except (ValueError, TypeError):
            return None
    
    async def sync_devis_acceptes(self, db: Session, force_full: bool = False) -> Dict[str, Any]:
        result = {"success": True, "nouveaux_devis": 0, "devis_mis_a_jour": 0, "erreurs": [], "message": ""}
        
        try:
            depuis_date = None if force_full else self._get_derniere_synchro(db)
            logger.info(f"Sync devis depuis: {depuis_date or 'début'}")
            
            devis_list = await self.get_devis_acceptes(depuis_date)
            logger.info(f"Devis trouvés: {len(devis_list)}")
            
            for devis_data in devis_list:
                try:
                    karlia_id = devis_data.get("id")
                    if not karlia_id:
                        continue
                    
                    existing = db.query(Commande).filter(Commande.karlia_document_id == karlia_id).first()
                    
                    if existing:
                        if existing.statut == 'nouvelle':
                            await self._update_commande(db, existing, devis_data)
                            result["devis_mis_a_jour"] += 1
                    else:
                        await self._create_commande(db, devis_data)
                        result["nouveaux_devis"] += 1
                except Exception as e:
                    error_msg = f"Erreur devis {devis_data.get('id', '?')}: {str(e)}"
                    logger.error(error_msg)
                    result["erreurs"].append(error_msg)
            
            self._set_derniere_synchro(db, datetime.utcnow())
            result["message"] = f"Sync terminée: {result['nouveaux_devis']} nouveaux, {result['devis_mis_a_jour']} MAJ"
        except Exception as e:
            result["success"] = False
            result["message"] = f"Erreur sync: {str(e)}"
            result["erreurs"].append(str(e))
            logger.error(f"Erreur sync: {e}")
        
        return result
    
    async def _create_commande(self, db: Session, devis_data: Dict[str, Any]) -> Commande:
        devis_detail = await self.get_devis_detail(devis_data["id"])
        if devis_detail:
            devis_data.update(devis_detail)
        
        customer_id = devis_data.get("id_customer") or devis_data.get("customer_id")
        client_info = {}
        if customer_id:
            customer_data = await self.get_customer_detail(customer_id)
            if customer_data:
                client_info = {
                    "client_nom": customer_data.get("name") or customer_data.get("company_name"),
                    "client_email": customer_data.get("email"),
                    "client_telephone": customer_data.get("phone"),
                    "client_adresse": self._format_address(customer_data),
                    "client_siret": customer_data.get("siret") or customer_data.get("vat_number")
                }
        
        commande = Commande(
            karlia_document_id=devis_data["id"],
            karlia_customer_id=customer_id,
            reference_devis=devis_data.get("reference") or devis_data.get("number"),
            client_nom=client_info.get("client_nom") or devis_data.get("customer_name"),
            client_email=client_info.get("client_email"),
            client_telephone=client_info.get("client_telephone"),
            client_adresse=client_info.get("client_adresse"),
            client_siret=client_info.get("client_siret"),
            montant_ht=devis_data.get("total_without_tax") or devis_data.get("total_ht"),
            montant_tva=devis_data.get("total_tax") or devis_data.get("total_tva"),
            montant_ttc=devis_data.get("total_with_tax") or devis_data.get("total_ttc"),
            date_devis=self._parse_karlia_date(devis_data.get("date")),
            date_acceptation=self._parse_karlia_date(devis_data.get("date_accepted") or devis_data.get("date_signed")),
            statut="nouvelle"
        )
        
        db.add(commande)
        db.flush()
        
        products = devis_data.get("products_list") or devis_data.get("lines") or []
        for idx, product in enumerate(products):
            ligne = CommandeLigne(
                commande_id=commande.id,
                karlia_product_id=str(product.get("id_product") or product.get("product_id") or ""),
                designation=product.get("description") or product.get("name"),
                description=product.get("long_description"),
                quantite=product.get("quantity", 1),
                unite=product.get("unit"),
                prix_unitaire_ht=product.get("price_without_tax") or product.get("unit_price"),
                taux_tva=self._parse_tva(product.get("id_vat") or product.get("vat_rate")),
                montant_ht=product.get("total_without_tax"),
                montant_tva=product.get("total_tax"),
                montant_ttc=product.get("total_with_tax"),
                ordre=idx
            )
            db.add(ligne)
        
        db.commit()
        return commande
    
    async def _update_commande(self, db: Session, commande: Commande, devis_data: Dict[str, Any]):
        devis_detail = await self.get_devis_detail(devis_data["id"])
        if devis_detail:
            devis_data.update(devis_detail)
        
        commande.montant_ht = devis_data.get("total_without_tax") or commande.montant_ht
        commande.montant_tva = devis_data.get("total_tax") or commande.montant_tva
        commande.montant_ttc = devis_data.get("total_with_tax") or commande.montant_ttc
        commande.updated_at = datetime.utcnow()
        
        db.commit()


karlia_devis_service = KarliaDevisService()

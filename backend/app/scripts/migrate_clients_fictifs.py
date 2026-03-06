"""
Script de migration des clients fictifs vers Karlia.
Usage : docker compose exec backend python3 -m app.scripts.migrate_clients_fictifs
"""
import asyncio
import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.models import Contrat, ClientCache, Parametre
from app.services.karlia_service import KarliaService, KarliaError
from app.core import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def generer_numero_client(nom: str, index: int) -> str:
    prefix = ''.join(c for c in nom.upper() if c.isalpha())[:3].ljust(3, 'X')
    return f"{prefix}{str(index).zfill(3)}"


async def migrate():
    # 1. Charger la clé Karlia depuis la base
    db: Session = SessionLocal()
    p = db.query(Parametre).filter(Parametre.cle == 'karlia_api_key').first()
    config.settings.KARLIA_API_KEY = p.valeur if p and p.valeur else ''
    db.close()

    if not config.settings.KARLIA_API_KEY:
        logger.error("Clé Karlia introuvable en base")
        return

    logger.info(f"Clé Karlia chargée : {config.settings.KARLIA_API_KEY[:8]}...")
    karlia = KarliaService()
    db = SessionLocal()

    try:
        # 2. Clients fictifs distincts
        rows = db.execute(text("""
            SELECT DISTINCT client_karlia_id, client_nom
            FROM contrats
            WHERE (client_karlia_id LIKE '98%' OR client_karlia_id LIKE '99%')
            ORDER BY client_nom
        """)).fetchall()
        logger.info(f"{len(rows)} clients fictifs distincts à migrer")

        # 3. Dernier numéro Karlia
        try:
            dernier_num = await karlia.dernier_numero_client()
            logger.info(f"Dernier numéro Karlia : {dernier_num}")
        except KarliaError as e:
            logger.error(f"Impossible de récupérer la numérotation : {e}")
            return

        # 4. Créer chaque client dans Karlia
        mapping = {}
        erreurs = []

        for i, (ancien_id, nom) in enumerate(rows):
            numero_client = generer_numero_client(nom, dernier_num + i + 1)
            payload = {
                'name': nom,
                'individual': 0,
                'prospect': 0,
                'client_number': numero_client,
                'langId': 1,
                'main_country': 'FR',
                'invoice_country': 'FR',
            }
            try:
                await asyncio.sleep(0.7)
                result = await karlia.creer_client(payload)
                nouveau_id = str(result['id'])
                mapping[ancien_id] = nouveau_id
                logger.info(f"✅ {nom} ({ancien_id}) → {nouveau_id} [{numero_client}]")

                # Mettre à jour ou créer dans le cache local
                cache = db.query(ClientCache).filter(ClientCache.karlia_id == ancien_id).first()
                if cache:
                    cache.karlia_id = nouveau_id
                    cache.numero_client = numero_client
                else:
                    db.add(ClientCache(
                        karlia_id=nouveau_id,
                        numero_client=numero_client,
                        nom=nom,
                        pays='FR',
                    ))
            except KarliaError as e:
                logger.error(f"❌ {nom} ({ancien_id}) : {e}")
                erreurs.append((ancien_id, nom, str(e)))

        db.commit()

        # 5. Mettre à jour les contrats
        nb_contrats = 0
        for ancien_id, nouveau_id in mapping.items():
            contrats = db.query(Contrat).filter(Contrat.client_karlia_id == ancien_id).all()
            for c in contrats:
                c.client_karlia_id = nouveau_id
                nb_contrats += 1
        db.commit()

        # 6. Rapport
        logger.info("=" * 50)
        logger.info(f"✅ {len(mapping)} clients créés dans Karlia")
        logger.info(f"✅ {nb_contrats} contrats mis à jour")
        if erreurs:
            logger.warning(f"❌ {len(erreurs)} erreurs :")
            for ancien_id, nom, err in erreurs:
                logger.warning(f"   {nom} ({ancien_id}) : {err}")

    finally:
        db.close()


if __name__ == '__main__':
    asyncio.run(migrate())

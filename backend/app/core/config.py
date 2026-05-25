"""
Configuration centralisée — chargée depuis .env
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Base de données PostgreSQL
    DATABASE_URL: str = "postgresql://contrats_user:contrats_pass@localhost:5432/contrats_db"

    # API Karlia
    KARLIA_API_URL: str = "https://karlia.fr/app/api/v2"
    KARLIA_API_KEY: str = ""  # À renseigner dans .env — JAMAIS en dur ici

    # Sécurité JWT
    SECRET_KEY: str = "changez-cette-cle-en-production-32-chars-min"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 heures

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "https://gestion.sginformatique.fr"]

    # Fichiers
    UPLOAD_DIR: str = "./data/modeles"
    DOCUMENTS_DIR: str = "./data/documents"

    # Quota Karlia : 100 req/min — on limite à 80 pour sécurité
    KARLIA_MAX_REQUESTS_PER_MINUTE: int = 80

    # Sync devis Karlia : sleep entre chaque itération du loop.
    # 1.2s ≈ 50 req/min en pire cas (4 appels/devis) → marge confortable
    # sous le quota 100. À ajuster si la sync devient trop lente sur de
    # gros volumes (variable d'env KARLIA_SYNC_SLEEP_SECONDS).
    KARLIA_SYNC_SLEEP_SECONDS: float = 1.2

    # TTL (secondes) du cache mémoire du catalogue produits Karlia utilisé
    # par la fonctionnalité factures fournisseurs. Le catalogue change
    # rarement (catégories produits) et son chargement coûte ~4 s
    # (4 pages /products). 600 s = 10 min : compromis fraîcheur / coût.
    # Le bouton « Rafraîchir » côté UI force un rechargement (force_refresh=true).
    KARLIA_CATALOGUE_CACHE_TTL: int = 600

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

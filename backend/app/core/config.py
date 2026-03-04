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
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Fichiers
    UPLOAD_DIR: str = "./data/modeles"
    DOCUMENTS_DIR: str = "./data/documents"

    # Quota Karlia : 100 req/min — on limite à 80 pour sécurité
    KARLIA_MAX_REQUESTS_PER_MINUTE: int = 80

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

FROM python:3.12-slim

WORKDIR /app

# Dépendances système :
#   build-essential libpq-dev : compilation extensions Python (psycopg2, etc.)
#   ghostscript               : normalisation PDF -> PDF/A-3 pour la transmission
#                               Factur-X vers Chorus Pro (deposer/flux). Fournit
#                               aussi les profils ICC (/usr/share/ghostscript/.../iccprofiles/)
#                               utilisés par PDFA_def.ps lors de la conversion.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Dossiers de données
RUN mkdir -p data/modeles data/documents

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

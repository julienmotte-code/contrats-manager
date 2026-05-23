# 07 — Déploiement (Docker, nginx, .env)

## 1. docker-compose.yml

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: contrats
      POSTGRES_USER: contrats
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U contrats"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    build: ./backend
    env_file: .env
    environment:
      DATABASE_URL: postgresql://contrats:${DB_PASSWORD}@db:5432/contrats
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    volumes:
      - ./storage:/app/storage

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "80:80"
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  postgres_data:
```

État vérifié avec `docker compose ps` au commit de référence : 3 services up (db healthy depuis 8 semaines, backend et frontend up depuis 16 h).

## 2. Backend — `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data/modeles data/documents

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

Notes :
- `--reload` est conservé en production (rechargement automatique sur modification de fichier — coût mineur, simplifie les patchs à chaud).
- Pas de healthcheck déclaré côté Dockerfile.
- Volume `./storage:/app/storage` monté pour persister modèles et documents générés (cf. `document_service.STORAGE_DIR`).

## 3. Frontend — `Dockerfile.frontend`

```dockerfile
FROM nginx:alpine
COPY contrats-ui/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

Le build CRA est attendu déjà présent dans `contrats-ui/build/` au moment du `docker compose build` — il n'est **pas** produit par le Dockerfile lui-même. Procédure de déploiement frontend documentée dans `MEMORY.md → frontend_deployment_procedure.md` :
1. Sources éditées dans `~/contrats/contrats-ui-src/`.
2. Recopiées dans `~/contrats-ui/` (avec MUI dans `package.json`).
3. `npm run build` → `~/contrats-ui/build/`.
4. `cp -r ~/contrats-ui/build ~/contrats/contrats-ui/build`.
5. `docker compose build frontend && docker compose up -d frontend`.

## 4. `nginx.conf`

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location = /index.html {
        try_files $uri /index.html;
        add_header Cache-Control "no-store, no-cache, must-revalidate";
        add_header Pragma "no-cache";
        expires 0;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

Notes :
- `index.html` est servi avec en-têtes "no-store" pour éviter qu'un cache navigateur retienne un ancien hash JS.
- Tous les fichiers static sont servis depuis `/usr/share/nginx/html`.
- Le reverse proxy `/api` cible directement `http://backend:8000` via le réseau docker-compose, timeouts 5 minutes (utile pour les sync Karlia).
- Pas de TLS — TLS terminé en amont (cf. domaine `gestion.sginformatique.fr`).

## 5. Variables d'environnement

### 5.1 `.env` à la racine (utilisé par docker-compose)

Clés présentes (valeurs masquées) :

```
DB_PASSWORD=••••••••
DATABASE_URL=postgresql://contrats:••••••••@db:5432/contrats
KARLIA_API_KEY=••••••••                   # surchargé par parametres.karlia_api_key au démarrage
SECRET_KEY=••••••••                       # signature JWT
CORS_ORIGINS=••••••••                     # ["http://localhost:3000", "https://gestion.sginformatique.fr", ...]
TZ=••••••••                               # ex Europe/Paris
```

(Liste obtenue via `cut -d'=' -f1 .env` — aucune valeur exposée.)

### 5.2 `backend/.env` (legacy)

Fichier conservé pour rétrocompatibilité ; n'est **pas** monté par `docker-compose.yml` (qui utilise `.env` à la racine). Clés :

```
DATABASE_URL=••••••••
KARLIA_API_KEY=••••••••
SECRET_KEY=••••••••
CORS_ORIGINS=••••••••
```

### 5.3 `backend/.env.example`

Template public (committé) avec placeholders explicites :
```
DATABASE_URL=postgresql://contrats_user:VOTRE_MOT_DE_PASSE@localhost:5432/contrats_db
KARLIA_API_KEY=VOTRE_CLE_API_KARLIA_ICI
SECRET_KEY=changez-cette-cle-par-une-valeur-aleatoire-longue
CORS_ORIGINS=["http://localhost:3000","https://votre-domaine.com"]
```

Pas de `.env.example` à la racine du repo (`docker-compose.yml`'s `${DB_PASSWORD}` n'a pas de template équivalent).

## 6. Stockage local

`./storage/` (monté dans le backend) :
- `storage/modeles/` — modèles DOCX uploadés (`POST /api/documents/modeles/upload`).
- `storage/documents_generes/` — DOCX générés (`document_service.generer_document`).

Aucun mécanisme de purge automatique. Les chemins en dur dans `document_service.py` sont absolus (`/app/storage/...`), donc la dépendance au volume Docker est forte.

## 7. Backups

Dossier `./backups/` (présent, non versionné) — usage local, pas d'automatisation visible dans le repo.

## 8. CI/CD

Aucun workflow GitHub Actions ni script CI dans le repo. Le déploiement est manuel via `docker compose build && docker compose up -d`.

## 9. Tests

- `tests/rbac_check.sh` — script bash unique qui interroge l'API avec des tokens de différents rôles pour vérifier les codes HTTP attendus. Pas d'exécution automatique dans la CI.
- Pas de tests unitaires backend (`pytest` non dans `requirements.txt`).
- Pas de tests frontend métier (seul `App.test.js` par défaut CRA).

## 10. Versioning & tags

`git tag --sort=-creatordate` (5 derniers) :

```
v2.5.1-pre-emission-guard
v2.5.0-rbac-backend
v2.4.9-vague-1-complete
v2.4.8-schema-alignment
v2.4.7-dead-code-cleanup
```

Le commit de référence de ce dossier est sur `main` à `8752ab8 docs: journal merge chantier 2.2 + tag v2.5.1`. Les sauts de tag (ex v2.4.2 → v2.4.5) sont volontaires et documentés dans `MEMORY.md → versioning_baseline.md` — ne pas alerter en cas d'écart.

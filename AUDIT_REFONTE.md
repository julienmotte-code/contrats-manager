# Audit de refonte — Module Gestion des Contrats

> **Version auditée** : `main` au commit `f0d4c22` (tag `v2.4.6`)
> **Date de l'audit** : 21 mai 2026
> **Audit précédent** : `audit/module-v2.3.0` (commit `73648f4` du 18 mai 2026, 2176 lignes — non mergé sur main)
> **Branche de l'audit** : `audit/refonte-v2`
> **Objectif** : base documentaire pour une refonte lourde du module (migration GCP, dette technique, refonte UI)

Ce document est en **lecture seule** sur le code et la DB. Aucune modification, aucun redémarrage de containers, aucune valeur sensible (clés API, tokens, mots de passe) n'est révélée — ces valeurs sont remplacées par `<masqué>` ou tronquées.

---

## 1. Architecture générale et stack

### 1.1 Vue d'ensemble

Le module est une application monolithique trois-tiers, packagée en trois conteneurs Docker, accessible derrière un proxy nginx :

```
Internet ──► nginx (port 80)
                │
                ├── /          → SPA React buildée (HTML/JS/CSS statiques)
                └── /api/*     → reverse-proxy vers backend FastAPI (port 8000 interne)

backend FastAPI ──► PostgreSQL (port 5432 interne)
                ├── HTTP sortant → Karlia CRM (api.karlia.fr)
                ├── HTTP sortant → PISTE / Chorus Pro (sandbox.piste.gouv.fr)
                └── lecture/écriture fichiers locaux (storage/modeles, storage/documents_generes)
```

Le module est déployé sur une VM Ubuntu unique (`192.168.1.186`), avec accès externe via Cloudflare Tunnel (cf. tag `v2.4.0`, commit `a8690b7`).

### 1.2 Services Docker — `docker-compose.yml`

Le fichier (`docker-compose.yml`, 35 lignes) déclare 3 services et 1 volume nommé.

| Service | Image | Ports | Volumes | Dépendances | Redémarrage |
|---|---|---|---|---|---|
| `db` | `postgres:16` | `5432/tcp` (interne uniquement) | `postgres_data:/var/lib/postgresql/data` | — | `unless-stopped` |
| `backend` | build local `./backend` | `8000/tcp` (interne uniquement) | `./storage:/app/storage` (bind-mount hôte) | `db` (healthy) | `unless-stopped` |
| `frontend` | build local (`Dockerfile.frontend`) | `0.0.0.0:80→80` | — | `backend` | `unless-stopped` |

**Healthcheck DB** : `pg_isready -U contrats` toutes les 10 s, timeout 5 s, 5 retries.

**Variables d'environnement** :
- `db` : `POSTGRES_DB=contrats`, `POSTGRES_USER=contrats`, `POSTGRES_PASSWORD=${DB_PASSWORD}`
- `backend` : `env_file: .env` + `DATABASE_URL=postgresql://contrats:${DB_PASSWORD}@db:5432/contrats`
- `frontend` : aucune (image nginx statique pure)

État live des conteneurs (constaté le 2026-05-21 13:25) :

```
NAMES                 IMAGE               STATUS                 PORTS
contrats-backend-1    contrats-backend    Up 22 minutes          8000/tcp
contrats-frontend-1   contrats-frontend   Up 17 hours            0.0.0.0:80->80/tcp
contrats-db-1         postgres:16         Up 7 weeks (healthy)   5432/tcp
```

> **Observation** : `db` tourne sans interruption depuis 7 semaines, ce qui suggère qu'aucun re-déploiement complet n'a été nécessaire ; seules `backend` et `frontend` sont régulièrement rebuilées. Le backend démarre avec `--reload` (rechargement du code à chaud), pratique en dev mais à proscrire en production.

### 1.3 Topologie réseau et `nginx.conf`

Le fichier `nginx.conf` (24 lignes) configure une seule route HTTP :

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location = /index.html {
        try_files $uri /index.html;
        add_header Cache-Control "no-store, no-cache, must-revalidate";
        ...
    }
    location / {
        try_files $uri $uri/ /index.html;     # SPA fallback
    }
    location /api {
        proxy_pass http://backend:8000;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

- Pas de TLS : la terminaison HTTPS est déléguée au Cloudflare Tunnel externe.
- Timeout proxy à 300 s pour absorber les générations Word longues et les sync Karlia bloquantes.
- Aucun rate-limit nginx ; le seul garde-fou de débit est le `KARLIA_MAX_REQUESTS_PER_MINUTE=80` (cf. § 1.5).

**Topologie de ports** :

| Port | Exposition | Service | Usage |
|---|---|---|---|
| 80 | externe (host:80) | nginx (frontend) | SPA + proxy `/api` |
| 8000 | interne réseau Docker uniquement | backend FastAPI | accessible depuis `frontend` via `http://backend:8000` |
| 5432 | interne réseau Docker uniquement | PostgreSQL | accessible depuis `backend` via `db:5432` |

### 1.4 Variables d'environnement — `.env` + `config.py`

Le fichier `.env` est git-ignoré (`.gitignore:4`). Clés présentes (valeurs masquées) :

| Clé | Rôle | Présence | Lieu de consommation |
|---|---|---|---|
| `DATABASE_URL` | DSN PostgreSQL | masqué | `backend/app/core/database.py` |
| `KARLIA_API_KEY` | clé API Karlia v2 | masqué | `backend/app/services/karlia_service.py` (mais surchargée par DB — cf. § 4) |
| `SECRET_KEY` | clé JWT HS256 | masqué | `backend/app/api/auth.py` |
| `CORS_ORIGINS` | origines autorisées | masqué | `backend/app/main.py` |
| `DB_PASSWORD` | mot de passe Postgres | masqué | `docker-compose.yml` (`db` + `backend`) |
| `TZ` | fuseau horaire (probable Europe/Paris) | masqué | conteneurs |

Le fichier `backend/app/core/config.py` (`Settings` Pydantic) déclare des **défauts non-fonctionnels** pour les variables sensibles (placeholder pour `KARLIA_API_KEY=""`, `SECRET_KEY="changez-cette-cle-en-production-32-chars-min"`). Les défauts CORS incluent `http://localhost:3000`, `http://localhost:5173` et `https://gestion.sginformatique.fr` (production publique).

Constantes spécifiques au scheduler Karlia :

```python
KARLIA_MAX_REQUESTS_PER_MINUTE: int = 80   # quota Karlia est 100/min — marge 20 %
KARLIA_SYNC_SLEEP_SECONDS: float = 1.2     # sleep entre devis dans karlia_devis_service
ACCESS_TOKEN_EXPIRE_MINUTES: int = 480     # JWT valide 8 h
```

> **Nouveauté depuis l'audit v2.3.0** : `KARLIA_SYNC_SLEEP_SECONDS` (ajouté commit `6e4e714`, fix rate-limit 429 sur la sync devis).

### 1.5 Stockage persistant

| Emplacement | Mode | Contenu | Persistance |
|---|---|---|---|
| Volume Docker `contrats_postgres_data` | volume nommé | base PostgreSQL complète | sauvegardée par snapshot VM uniquement |
| Bind-mount `./storage:/app/storage` | bind-mount hôte | `modeles/` (templates Word), `documents_generes/` (Word produits) | sauvegardé via le repo hôte |
| `storage/modeles/` | hôte | 9 fichiers `.docx` (assistance tel, cantine, Cosoluce, maintenance, etc.) | versionné |
| `storage/documents_generes/` | hôte | 1 fichier `.docx` à date (`Contrat_AV1-ABCOS2026-MAI173_…`) | **git-ignoré** (`.gitignore:14`) |
| `backups/` | hôte | dumps SQL et listes d'IDs supprimés | sauvegardé sélectivement (`*.sql` git-ignoré, fichiers `.txt` versionnés) |

> **Observation** : le seul snapshot de la DB pour rejouer en cas de catastrophe est `backups/backup_pre_cleanup_bc_20260520_163107.sql` (créé avant le cleanup des 66 BC). Aucun mécanisme de backup automatique n'est planifié dans le module — c'est une dépendance opérationnelle externe.

### 1.6 Stack Python — `backend/requirements.txt`

Dépendances figées (versions exactes) :

| Paquet | Version | Rôle |
|---|---|---|
| `fastapi` | 0.115.0 | framework web ASGI |
| `uvicorn[standard]` | 0.30.0 | serveur ASGI |
| `sqlalchemy` | 2.0.35 | ORM |
| `psycopg2-binary` | 2.9.9 | driver PostgreSQL |
| `pydantic` | 2.9.2 | validation / sérialisation |
| `pydantic-settings` | 2.5.2 | chargement `.env` typé |
| `httpx` | 0.27.2 | client HTTP async (Karlia + PISTE) |
| `python-jose[cryptography]` | 3.3.0 | JWT |
| `passlib[bcrypt]` | 1.7.4 | hash mot de passe |
| `python-multipart` | 0.0.12 | uploads multipart |
| `python-dateutil` | 2.9.0 | parsing dates |
| `alembic` | 1.13.3 | **présent mais non utilisé** — aucun répertoire `migrations/` |
| `apscheduler` | 3.10.4 | scheduler in-process pour la sync Karlia |
| `python-docx` | 1.1.2 | génération de contrats Word |
| `email-validator` | non figé | validation emails Pydantic |

> **Anti-pattern à noter** : Alembic est dans `requirements.txt` mais le module utilise `Base.metadata.create_all(bind=engine)` (`backend/app/main.py:16`) pour créer le schéma — pas de migration versionnée. Toute évolution de schéma se fait manuellement sur la DB live.

### 1.7 Stack frontend — `contrats-ui-src/package.json`

**Source de référence** : `~/contrats/contrats-ui-src/src/` (versionnée). Le dossier `~/contrats/contrats-ui/` ne contient que le build statique embarqué dans l'image nginx.

Dépendances runtime :

| Paquet | Version | Rôle |
|---|---|---|
| `react` | 19.2.4 | framework UI (React 19 — assez récent) |
| `react-dom` | 19.2.4 | rendu DOM |
| `react-router-dom` | 7.13.1 | routing SPA |
| `react-scripts` | 5.0.1 | toolchain CRA (CRA est en mode maintenance) |
| `axios` | 1.13.6 | client HTTP |
| `react-hot-toast` | 2.6.0 | notifications toast |
| `react-datepicker` | 9.1.0 | sélection de dates |
| `react-select` | 5.10.2 | dropdown avec recherche |
| `lucide-react` | 0.576.0 | icônes SVG |
| `date-fns` | 4.1.0 | manipulation dates |

DevDeps : `tailwindcss@3.4.19`, `postcss`, `autoprefixer` — **Tailwind est la bibliothèque de styles principale**.

> **Anti-patterns frontend à porter en compte pour la refonte** :
> - Create React App (CRA) est obsolète depuis 2024 — la refonte devrait probablement viser Vite ou Next.js.
> - Aucun gestionnaire d'état global (pas de Redux/Zustand) — l'état partagé passe uniquement par `AuthContext` (cf. § 5.3).
> - Pas de TypeScript : tout est en JS.

### 1.8 Topologie de scheduling

Le seul mécanisme planifié est dans `backend/app/main.py` (lignes 152-168) :

```python
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup():
    # Synchro au démarrage
    await synchro_karlia()
    # Synchro nocturne à 2h
    scheduler.add_job(synchro_karlia, CronTrigger(hour=2, minute=0))
    scheduler.start()
```

- **Sync Karlia au boot** : synchrone et bloquante — le serveur ne sert pas de requête tant que la sync clients + articles n'est pas terminée.
- **Sync Karlia nocturne** : cron quotidien `02:00` heure du conteneur (dépend de `TZ`).
- **Aucun autre job planifié** : pas de cron pour la facturation Syntec, pas de cron pour Chorus Pro, pas de cron pour Google Calendar.

> **Risques identifiés** :
> 1. Sync au boot synchrone → bouclage de redémarrage si Karlia est indisponible.
> 2. Si plusieurs instances du backend tournent en parallèle (future scalabilité GCP), chacune lancera sa propre synchro Karlia → 2× le quota, doublons potentiels (un upsert par `karlia_id` limite le risque mais pas la consommation de quota).
> 3. APScheduler `AsyncIOScheduler` n'est pas distribué — incompatible avec une mise à l'échelle horizontale.

### 1.9 Arbre des dossiers (2 niveaux)

```
~/contrats/
├── AUDIT_REFONTE.md            ← ce fichier (nouveau)
├── CODING_RULES.md             ← règles de dev (193 lignes)
├── PROJECT_CONTEXT.md          ← contexte projet pour Claude (88 lignes)
├── README.md                   ← README utilisateur (201 lignes)
├── GUIDE_DEMARRAGE.md          ← guide de démarrage (217 lignes)
├── docker-compose.yml          ← 3 services
├── Dockerfile.frontend         ← image nginx + build React
├── nginx.conf                  ← config nginx (24 lignes)
├── .env                        ← git-ignoré
├── .gitignore
│
├── backend/
│   ├── Dockerfile              ← python:3.12-slim + uvicorn --reload
│   ├── requirements.txt        ← 14 paquets figés
│   └── app/
│       ├── main.py             ← point d'entrée FastAPI + synchro_karlia + scheduler
│       ├── api/                ← 15 routers (auth, clients, contrats, commandes, chorus, dashboard, …)
│       ├── core/               ← config.py + database.py
│       ├── models/models.py    ← modèles SQLAlchemy (17 tables)
│       ├── services/           ← 8 services (karlia, karlia_devis, chorus, contrat, revision, validation, document, …)
│       └── scripts/            ← seeds (mairies, charge, test_data) + migrate_clients_fictifs
│
├── contrats-ui-src/            ← SOURCE de référence frontend
│   ├── package.json            ← React 19 + Tailwind 3
│   ├── public/
│   ├── src/
│   │   ├── App.js              ← routes
│   │   ├── pages/              ← 21 pages
│   │   ├── components/Layout.js
│   │   ├── context/AuthContext.js
│   │   └── services/api.js
│   └── build/                  ← build CRA (git-ignoré)
│
├── contrats-ui/                ← copie du build embarqué dans l'image nginx
│
├── docs/
│   └── DIAGNOSTIC_PDF_COMMANDES.md   ← rapport diag du 20/05/2026 (261 lignes)
│
├── scripts/                    ← scripts one-shot exécutés hors container
│   ├── cleanup_bc_commandes.py        ← suppression 66 BC (commit 1045343)
│   └── rattrapage_pdf_url.py          ← rattrapage 106 pdf_url manquants (commit 8cf0cf3)
│
├── storage/                    ← bind-mount → /app/storage du backend
│   ├── modeles/                ← 9 templates .docx (gabarits contrats)
│   └── documents_generes/      ← contrats Word produits (git-ignoré)
│
└── backups/                    ← dumps SQL + listes IDs supprimés
    ├── backup_pre_cleanup_bc_20260520_163107.sql  (git-ignoré)
    └── deleted_bc_ids_20260520_164326.txt
```

> **Note** : le dossier `~/contrats-ui/` (en dehors du projet, mentionné dans `PROJECT_CONTEXT.md:18`) n'est **plus la source canonique** depuis le 21/04/2026 — la source officielle est `~/contrats/contrats-ui-src/`. Le `PROJECT_CONTEXT.md` n'a pas été mis à jour sur ce point.

### 1.10 Historique git et tags

Le module a publié **22 tags** au total. Tags ordonnés par date de création (15 plus récents) :

| Tag | Commit | Sujet | Date approx. |
|---|---|---|---|
| `v2.4.6.1` | `ed3f9d5` | fix Karlia factures id_status:0 (en cours, non-mergé sur main) | 21/05/2026 |
| `v2.4.6` | `f0d4c22` | nettoyage code mort pdf_devis | 21/05/2026 |
| `v2.4.5` | `9a7fede` | sleep + retry 429 sync Karlia | 20/05/2026 |
| `v2.4.2` | `a3e4ecd` | Dashboard refondu — endpoint unique `/api/dashboard/stats` | 19/05/2026 |
| `v2.4.1` | `a63795c` | factures Karlia en Brouillon | 19/05/2026 |
| `v2.4.0` | `a8690b7` | accès externe via Cloudflare Tunnel | 18/05/2026 |
| `v2.3.2` | `1530552` | fix sync Karlia filter id_type | 19/05/2026 |
| `v2.3.1` | `2f0a215` | cleanup 66 BC commandes | 19/05/2026 |
| `v2.3.0-pre-dashboard-fix` | `a63795c` | snapshot pré-refonte dashboard | 19/05/2026 |
| `v2.3.0-pre-chorus-merge` | `35d5acf` | snapshot pré-merge Chorus | 18/05/2026 |
| `v2.3.0` | `ad36a41` | suppression rôle CONSULTANT, ajout TECHNICIEN | 18/05/2026 |
| `v2.2.1` | `512411f` | suppression onglet À traiter | 17/05/2026 |
| `v2.2.0` | `b2dc457` | filtrage devis par opportunité Traité | 17/05/2026 |
| `v2.1.0` | `5195778` | Chorus Pro — fix URLs API | 17/05/2026 |
| `v1.5.0` | `d129acd` | ajout module gestion commandes | mars/avril 2026 |

**Anomalies de versioning** : sauts `v2.4.2 → v2.4.5` (deux paliers ignorés). Ces sauts sont volontaires d'après la note `versioning_baseline.md` en mémoire utilisateur — à ne pas signaler comme anomalie technique.

**Branches actives sur origin** (20 au total) :
- `main` : tronc de production (HEAD = `f0d4c22`)
- `audit/module-v2.3.0` : audit précédent du 18/05 (commit `73648f4`)
- `audit/refonte-v2` : **cet audit**
- Branches `feature/*` en attente ou abandonnées : `feature/chorus-pro`, `feature/dashboard-refonte`, `feature/ecran-clients`, `feature/generation-contrats-word`, `feature/gestion-commandes`, `feature/gestion-formateurs`, `feature/google-agenda-planning`, `feature/renouvellements-multi-selection`, `feature/seed-test-data`, `feature/sync-devis-opportunites-traitees`, `feature/contrats-onglets-statut`
- Branches `fix/*` en attente ou abandonnées : `fix/chorus-payload-v5-01`, `fix/chorus-payload-v5-01-clean`, `fix/karlia-api-key-centralisation`, `fix/karlia-facture-brouillon-v2`, `fix/karlia-factures-brouillon`
- Branches `diag/*` : `diag/karlia-facture-statut`
- Branches `feat/*` : `feat/dashboard-stats-endpoint`, `feat/stabilisations-v2.3.1`

> **Observation** : 18 branches obsolètes sur l'origine — la stratégie de cleanup des branches mergées n'est pas appliquée. À traiter en pré-refonte.

### 1.11 Documents complémentaires à la racine

| Fichier | Lignes | Rôle | À jour ? |
|---|---|---|---|
| `README.md` | 201 | présentation publique | **non** — décrit encore `id_status=1 (Brouillon)` corrigé en `id_status=0` depuis `v2.4.6.1` (branche non-mergée) |
| `GUIDE_DEMARRAGE.md` | 217 | installation locale | à valider |
| `PROJECT_CONTEXT.md` | 88 | contexte projet pour assistants AI | **partiellement obsolète** — référence `~/contrats-ui` comme source frontend (faux depuis 21/04) |
| `CODING_RULES.md` | 193 | règles de dev (imports React, dates ISO, etc.) | à jour |
| `docs/DIAGNOSTIC_PDF_COMMANDES.md` | 261 | rapport diag PDF manquants (20/05/2026) | historique |

Les fichiers `CLAUDE.md` et `AUDIT_MODULE_v2.3.0.md` ont été **supprimés de main** (visibles seulement sur la branche `audit/module-v2.3.0`).

---

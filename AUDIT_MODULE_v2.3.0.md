# Audit exhaustif — Module Gestion des Contrats

**Version auditée** : étiquette symbolique `v2.3.0` (audit de l'état du code à
HEAD le 2026-05-18, branche `audit/module-v2.3.0` créée depuis
`fix/chorus-payload-v5-01` à `71f2547`).

**Périmètre** : intégralité du module `~/contrats/` — backend FastAPI,
frontend React, base PostgreSQL, intégrations Karlia et Chorus Pro / PISTE.

**Objet** : cartographie exhaustive pré-refonte. Le document décrit le code
tel qu'il est, sans recommandations d'évolution sauf section 8.

## Table des matières

- [1. Architecture générale et stack](#1-architecture-générale-et-stack)
- [2. Modèle de données PostgreSQL](#2-modèle-de-données-postgresql)
- [3. API Backend (FastAPI)](#3-api-backend-fastapi)
- [4. Services métier backend](#4-services-métier-backend)
- [5. Frontend React](#5-frontend-react)
- [6. Workflows métier de bout en bout](#6-workflows-métier-de-bout-en-bout)
- [7. Intégrations externes](#7-intégrations-externes)
- [8. État actuel et perspectives](#8-état-actuel-et-perspectives)
- [Questions ouvertes pour la refonte](#questions-ouvertes-pour-la-refonte)

---

## 1. Architecture générale et stack

### 1.1 Vue d'ensemble

Application web auto-hébergée sur une VM Ubuntu (`192.168.1.186`) du LAN
SG Informatique, exposée également en externe via un Cloudflare Tunnel
(`gestion.sginformatique.fr`). Le stack est packagé en trois services Docker
orchestrés par Docker Compose, le frontend statique étant servi par nginx
qui fait également office de reverse-proxy vers le backend Python.

- **Backend** : FastAPI 0.115 + SQLAlchemy 2.0 + Uvicorn (Python 3.12)
- **Frontend** : React 19 (Create React App) + Tailwind CSS 3.4 + Material-UI
  (mix de Tailwind sur certaines pages et MUI sur d'autres — cf. section 5)
- **Base de données** : PostgreSQL 16
- **Reverse-proxy** : nginx (Alpine)
- **Scheduler** : APScheduler 3.10 (cron interne au backend)
- **Auth** : JWT signé HS256 via `python-jose` + bcrypt via `passlib`
- **Génération de documents** : `python-docx` 1.1

### 1.2 Services Docker — `docker-compose.yml`

Fichier source : `~/contrats/docker-compose.yml`. Trois services + un volume.

| Service | Image | Build | Ports | Volumes | Healthcheck | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `db` | `postgres:16` | non | aucun (5432 interne) | `postgres_data:/var/lib/postgresql/data` | `pg_isready -U contrats` toutes les 10s, 5 retries | DB `contrats`, user `contrats`, password via `${DB_PASSWORD}` |
| `backend` | image locale (build `./backend`) | `backend/Dockerfile` | aucun (8000 interne) | `./storage:/app/storage` | aucun | `env_file: .env`, dépend de `db` healthy, `restart: unless-stopped`, mode `--reload` activé (Uvicorn) |
| `frontend` | image locale (build `Dockerfile.frontend`) | `Dockerfile.frontend` | **80:80 (LAN/host)** | aucun (build copié dans l'image) | aucun | nginx Alpine, dépend de `backend` |

Le `Dockerfile.frontend` est minimal :
```dockerfile
FROM nginx:alpine
COPY contrats-ui/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```
Cela signifie que **le build React doit déjà exister dans `contrats-ui/build/`
au moment du `docker compose build`** — il est généré à partir de
`~/contrats-ui/src/` (sources de build, hors-repo) ou de
`~/contrats/contrats-ui-src/src/` (sources versionnées) puis copié à la main
dans `contrats-ui/build/` avant rebuild de l'image. Voir section 5.6.

Le backend tourne en mode auto-reload (`uvicorn --reload`) défini dans le
CMD du Dockerfile, ce qui implique que **toute modification de fichier
Python dans `./backend/app/` est rechargée à chaud sans rebuild**, mais
nécessite que les fichiers soient présents dans le filesystem du conteneur
(et donc rebuild si la modification est ailleurs que dans un dossier mounté).

### 1.3 Topologie réseau

- **Port 80** (hôte) → conteneur `frontend` (nginx).
- **nginx** sert :
  - les fichiers statiques React sous `/usr/share/nginx/html` pour toute
    URL sauf `/api`
  - `/api/*` → proxy vers `http://backend:8000` (réseau Docker interne, DNS
    Docker Compose). Timeouts `read/connect/send` portés à 300s (utile pour
    les synchros Karlia longues et les générations Word/PDF).
  - SPA fallback : `try_files $uri $uri/ /index.html` (toutes les routes
    React fonctionnent sur reload).
  - `index.html` servi avec `Cache-Control: no-store, no-cache,
    must-revalidate` pour éviter de servir un index obsolète qui pointerait
    vers d'anciens assets.
- **Port 5432** : non exposé, accès uniquement via `docker compose exec db
  psql -U contrats -d contrats`. Le mot de passe `contrats_user/contrats_db`
  mentionné dans `CLAUDE.md` est obsolète — la réalité est `-U contrats -d
  contrats`.
- **Port 8000** : non exposé non plus, uniquement joignable par nginx via le
  réseau bridge Docker (`backend:8000`).
- **Accès externe** : un Cloudflare Tunnel (`/home/user/.cloudflared/cert.pem`
  présent sur la machine, configuration non versionnée) expose
  `https://gestion.sginformatique.fr` vers le port 80 local. Le tag git
  `v2.4.0` (`a8690b7`) est précisément le commit qui a ajouté l'origine
  CORS correspondante.

### 1.4 Variables d'environnement (`.env` + `config.py`)

Fichier d'environnement : `~/contrats/.env` (gitignored), chargé à la fois par
Docker Compose (`env_file: .env` sur le backend) et par `pydantic-settings`
côté Python (`backend/app/core/config.py`, classe `Settings`).

Variables effectives (valeurs masquées) :

| Variable | Présence | Origine / usage |
| --- | --- | --- |
| `DATABASE_URL` | rempli | URL Postgres complète (`postgresql://contrats:***@db:5432/contrats`). Recomposée aussi par `docker-compose.yml` en override (la variable du `.env` est surchargée en environnement du conteneur backend pour pointer vers `db:5432`). |
| `DB_PASSWORD` | rempli | Utilisé par `docker-compose.yml` pour `POSTGRES_PASSWORD` du conteneur Postgres ET pour reconstruire `DATABASE_URL` côté backend. |
| `KARLIA_API_KEY` | doit être vide en `.env` selon `CODING_RULES.md` | Clé fallback. La vraie source d'autorité est la table `parametres.karlia_api_key`, lue au démarrage et substituée dans l'instance globale `karlia` (`backend/app/main.py`). |
| `SECRET_KEY` | rempli | Signe les JWT HS256 (`config.py` → `app/api/auth.py`). 32 chars min recommandés. |
| `CORS_ORIGINS` | rempli | Liste d'origines autorisées (intégrée dans `settings.CORS_ORIGINS`). Inclut localhost dev, IP LAN, et `gestion.sginformatique.fr`. |
| `TZ` | `Europe/Paris` | Timezone du conteneur backend (validée par `docker compose exec backend python3 -c "import os; print(os.getenv('TZ'))"`). |

Le fichier `backend/.env.example` documente le format attendu.

Defaults définis dans `backend/app/core/config.py` (utilisés si une variable
manque, mais ne devraient jamais primer en production) :

- `KARLIA_API_URL` = `https://karlia.fr/app/api/v2`
- `KARLIA_MAX_REQUESTS_PER_MINUTE` = `80` (quota Karlia documenté = 100/min,
  marge de sécurité de 20)
- `ACCESS_TOKEN_EXPIRE_MINUTES` = `480` (JWT 8h)
- `ALGORITHM` = `HS256`
- `UPLOAD_DIR` = `./data/modeles` (dossier interne au conteneur)
- `DOCUMENTS_DIR` = `./data/documents`

### 1.5 Stockage persistant

| Chemin (hôte) | Type | Contenu | Volume Docker |
| --- | --- | --- | --- |
| `~/contrats/storage/modeles/` | dossier | Modèles Word `.docx` uploadés (fallback si pas en base) | `./storage:/app/storage` (monté sur backend) |
| `~/contrats/storage/documents_generes/` | dossier | Documents Word/PDF générés à la volée (contrats édités, devis exportés). Gitignored. | idem |
| `postgres_data` | volume Docker nommé | Toute la base PostgreSQL | géré par Docker, lifecycle découplé du repo |

Note : `backend/Dockerfile` crée aussi `data/modeles` et `data/documents` à
l'intérieur du conteneur (chemins définis dans `config.py`), mais ces
dossiers **ne sont pas montés** — ils ne survivent pas à un `docker compose
down -v`. Le vrai stockage de production est `./storage` qui est monté en
volume. Il y a donc une incohérence entre `config.py` (`UPLOAD_DIR =
./data/modeles`) et la réalité du déploiement (`./storage/modeles`) — à
clarifier dans la refonte (cf. section 8).

### 1.6 Stack Python (backend)

Source : `backend/requirements.txt`. Versions pinnées.

| Paquet | Version | Rôle |
| --- | --- | --- |
| `fastapi` | 0.115.0 | Framework HTTP/REST |
| `uvicorn[standard]` | 0.30.0 | Serveur ASGI |
| `sqlalchemy` | 2.0.35 | ORM |
| `psycopg2-binary` | 2.9.9 | Driver Postgres |
| `pydantic` / `pydantic-settings` | 2.9.2 / 2.5.2 | Validation + chargement `.env` |
| `httpx` | 0.27.2 | Client HTTP async (Karlia, PISTE) |
| `python-jose[cryptography]` | 3.3.0 | Signature JWT |
| `passlib[bcrypt]` | 1.7.4 | Hachage mot de passe |
| `python-multipart` | 0.0.12 | Upload de fichiers |
| `python-dateutil` | 2.9.0 | Manipulation de dates |
| `alembic` | 1.13.3 | **Présent dans `requirements.txt` mais inutilisé** — aucun dossier `alembic/`, aucune commande dans le projet. Les modifs de schéma se font via `Base.metadata.create_all()` au démarrage (ne fait QUE des CREATE — les ALTER doivent être appliqués manuellement en SQL). |
| `apscheduler` | 3.10.4 | Scheduler interne (cron nocturne 2h00) |
| `python-docx` | 1.1.2 | Génération de documents Word |
| `email-validator` | (non pinné) | Validation EmailStr Pydantic |

### 1.7 Stack frontend

Source : `contrats-ui-src/package.json`.

| Paquet | Version | Rôle |
| --- | --- | --- |
| `react` / `react-dom` | 19.2.4 | UI |
| `react-router-dom` | 7.13.1 | Routing |
| `axios` | 1.13.6 | Client HTTP |
| `date-fns` | 4.1.0 | Formatage de dates (locale `fr`) |
| `react-datepicker` | 9.1.0 | Sélecteur de date |
| `react-hot-toast` | 2.6.0 | Notifications |
| `lucide-react` | 0.576.0 | Icônes (sur les pages Tailwind) |
| `react-select` | 5.10.2 | Selects avancés |
| `tailwindcss` | 3.4.19 | Utilitaires CSS (devDep) |
| `react-scripts` | 5.0.1 | Toolchain CRA |

**Absent du `package.json` mais utilisé dans le code** : Material-UI (`@mui/material`, `@mui/icons-material`). Les pages `ChorusProPage.js`, `Dashboard.js`, plusieurs pages de commandes, etc. importent MUI. La dépendance doit donc être installée dans `node_modules` (à confirmer côté `~/contrats-ui/`) sans être déclarée dans le `package.json` du dossier versionné, ce qui est une source potentielle de fragilité du build (cf. section 8).

### 1.8 Topologie de scheduling

`AsyncIOScheduler` initialisé dans `backend/app/main.py` :

- **Au démarrage** : recharge `karlia.api_key` depuis `parametres.karlia_api_key` et exécute une synchro Karlia immédiate (`synchro_karlia()`).
- **Cron quotidien** : `CronTrigger(hour=2, minute=0)` → `synchro_karlia()` chaque nuit à 02h00 locale (TZ Europe/Paris).
- Aucun autre job planifié dans le code.

### 1.9 Arbre des dossiers (2 niveaux)

```
~/contrats/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env / .env.example
│   ├── scripts/                    # scripts hors-app (gen_modeles.py, export_clients_karlia.py)
│   └── app/
│       ├── __init__.py
│       ├── main.py                 # Point d'entrée FastAPI + scheduler
│       ├── api/                    # 15 routers (auth, clients, contrats, chorus, ...)
│       ├── core/                   # config.py + database.py
│       ├── models/                 # models.py (SQLAlchemy)
│       ├── services/               # 8 services métier (Karlia, Chorus, Syntec, ...)
│       └── scripts/                # Seeds + migrations one-shot
├── contrats-ui/                    # Image binaire du frontend (build copié, non versionné sauf build/)
├── contrats-ui-src/                # Sources React versionnées (source de vérité git)
│   └── src/
│       ├── App.js
│       ├── pages/                  # 21 pages
│       ├── components/             # Composants partagés (Layout, PrivateRoute, ...)
│       ├── context/                # AuthContext
│       └── services/               # api.js (instance axios + helpers)
├── docs/
│   └── CHORUS_PRO_RACCORDEMENT.md  # Diagnostic Chorus 2026-05-18
├── storage/
│   ├── modeles/                    # Modèles Word .docx
│   └── documents_generes/          # Sorties générées (gitignored)
├── docker-compose.yml
├── Dockerfile.frontend
├── nginx.conf
├── .env                            # gitignored
├── CLAUDE.md
├── CODING_RULES.md
├── PROJECT_CONTEXT.md
├── GUIDE_DEMARRAGE.md
├── README.md
└── AUDIT_MODULE_v2.3.0.md          # (ce fichier)
```

### 1.10 Historique Git récent et tags

Tag courant le plus récent : **`v2.4.0`** (`a8690b7`, `feat: accès externe via
Cloudflare Tunnel - CORS ajouté`). L'étiquette `v2.3.0` mentionnée dans le
prompt d'audit correspond au commit `ad36a41` (`Rôles: suppression
CONSULTANT, ajout TECHNICIEN, verrouillage accès`) — c'est le tag formel
juste avant l'ouverture externe.

Tags chronologiques (les plus récents en haut) :

| Tag | Commit | Sujet |
| --- | --- | --- |
| `v2.4.0` | `a8690b7` | Cloudflare Tunnel + CORS étendu |
| `v2.3.0` | `ad36a41` | Rôles : suppression CONSULTANT, ajout TECHNICIEN, verrouillage |
| `v2.2.1` | `512411f` | Suppression onglet `a_commander` |
| `v2.2.0` | `b2dc457` | Filtrage devis par opportunité Traité |
| `v2.1.0` | `5195778` | Fix Chorus Pro : URLs API + instance Karlia globale |
| `v1.5.0` | `d129acd` | Module gestion des commandes (devis acceptés Karlia) |
| `v2-stable` | `b676b68` | Fix tunnel renouvellement |
| `v2-seed-mairies` | `983c678` | Script seed 1000 mairies |
| `v2-migration-clients-karlia` | `7a9af6d` | Migration clients fictifs vers Karlia |
| `v1.3.1` | `5ea6c56` | Génération contrats Word |

Commits récents sur la branche actuelle (avant audit) :

| Commit | Sujet |
| --- | --- |
| `71f2547` | Fix Chorus Pro payload conformity to spec V5.01 + structured logging (HEAD audit) |
| `da41747` | Add CLAUDE.md with project working rules and conventions |
| `4c1614e` | Improve Chorus Pro service tracing and add dry-run mode |
| `bbe09a6` | Fix Karlia invoice workflow with net discounted prices |
| `3560834` | Refine dashboards and contract filters for formateur and technicien |
| `cfe6a13` | Prepare Google Calendar sync status for prestation planning |
| `b54aab5` | Prepare agenda target planning and restore dashboard stats |
| `35d5acf` | Hide contract and index actions for formateurs on dashboard |
| `ae14c7f` | Restrict formateur access to contract and command modules |

Lecture : depuis v2.4.0, les chantiers en cours sont (i) le module Google
Agenda pour les prestations (branche `feature/google-agenda-planning`,
mergée dans l'historique linéaire des derniers commits), (ii) la
restriction d'accès du rôle FORMATEUR, (iii) la fiabilisation du workflow
Karlia (`bbe09a6`), et (iv) la mise en conformité du payload Chorus Pro
(`71f2547`, livré sur `fix/chorus-payload-v5-01`).

### 1.11 Documents complémentaires versionnés à la racine

- `CLAUDE.md` — guide de collaboration agent IA (Tutoiement, double dossier React, etc.)
- `CODING_RULES.md` — règles obligatoires (imports, dates, FK, Karlia, clé en base)
- `PROJECT_CONTEXT.md` — résumé technique
- `GUIDE_DEMARRAGE.md` — onboarding nouveau dev
- `README.md` — vue d'ensemble (stack, tables, droits, commandes)

---


## 2. Modèle de données PostgreSQL

Source SQLAlchemy : `backend/app/models/models.py` (501 lignes).
Source DB live : conteneur `db` (Postgres 16), 17 tables dans le schéma
`public`.

### 2.1 Vue d'ensemble — les 17 tables groupées par domaine

| Domaine | Tables |
| --- | --- |
| Référentiel Karlia (caches) | `clients_cache`, `articles_cache` |
| Contrats pluriannuels | `contrats`, `contrat_articles`, `plan_facturation`, `lots_facturation`, `indices_revision` |
| Documents | `documents_generes`, `modeles_documents` |
| Devis → commandes → prestations | `commandes`, `commande_lignes`, `prestations`, `formateurs` |
| Chorus Pro | `factures_karlia`, `transmissions_chorus` |
| Système | `utilisateurs`, `parametres` |

Particularité de typage : **mix UUID / Integer** selon les tables. Le bloc
"historique" (contrats, plans, lots, indices, factures Chorus, clients/articles
cache) utilise des PK `uuid` ; le bloc "commandes/formateurs/utilisateurs"
(plus récent, ajouté avec le module commandes en v1.5.0) utilise des PK
`integer` à séquence. Les deux conventions cohabitent et créent des points
de jonction inattendus (`utilisateurs.id` UUID mais `utilisateurs.formateur_id`
INTEGER, `commandes.contrat_id` UUID mais `commandes.id` INTEGER).

### 2.2 `clients_cache` — Cache local des clients Karlia

**Classe SQLAlchemy** : `ClientCache` (`models.py:20-48`).
**Rôle métier** : copie locale des clients Karlia pour fonctionner sans
requête API (synchro nocturne). C'est la source de tous les `client_nom` et
`client_siret` historisés sur les contrats et factures.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | côté Python `uuid.uuid4` | PK |
| `karlia_id` | varchar(100) | NOT NULL | | UNIQUE (`clients_cache_karlia_id_key`) |
| `numero_client` | varchar(20) | NOT NULL | | Modèle déclare `unique=True` mais **la contrainte UNIQUE n'existe pas en DB** (divergence — cf. 2.18) |
| `nom` | varchar(255) | NOT NULL | | |
| `adresse_ligne1` / `adresse_ligne2` | varchar(255) | | | |
| `code_postal` | varchar(10) | | | |
| `ville` | varchar(100) | | | |
| `pays` | varchar(100) | | côté Python `"France"` | |
| `email` | varchar(255) | | | |
| `telephone`, `mobile` | varchar(30) | | | |
| `siret` | varchar(14) | | | Utilisé pour Chorus Pro |
| `tva_intracom` | varchar(20) | | | |
| `forme_juridique` | varchar(100) | | | |
| `contact_nom`, `contact_prenom`, `contact_fonction` | varchar(150) | | | |
| `notes` | text | | | |
| `synchro_at` | timestamptz | | | Dernière synchro Karlia |
| `created_at` / `updated_at` | timestamptz | | `now()` | |

**Relations** : `relationship("Contrat")` côté SQLAlchemy avec une jointure
non-FK : `primaryjoin="ClientCache.karlia_id == Contrat.client_karlia_id"`.
Pas de FK en DB côté `contrats` (couplage faible — cf. 2.7).

### 2.3 `articles_cache` — Cache local des articles Karlia

**Classe** : `ArticleCache` (`models.py:51-65`).
**Rôle métier** : référentiel produits Karlia (désignation, prix HT,
unité, taux TVA), copié en local pour proposer un autocomplete sur le tunnel
contrat.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `karlia_id` | varchar(100) | NOT NULL | | UNIQUE |
| `reference` | varchar(100) | | | |
| `designation` | varchar(500) | NOT NULL | | |
| `prix_unitaire_ht` | numeric(12,4) | | | 4 décimales (prix unitaires fins) |
| `unite` | varchar(50) | | | |
| `taux_tva` | numeric(5,2) | | côté Python `20.00` | |
| `actif` | boolean | | côté Python `True` | |
| `synchro_at` | timestamptz | | | |
| `created_at` | timestamptz | | `now()` | |

Pas de relations SQLAlchemy déclarées.

### 2.4 `indices_revision` — Historique des indices Syntec

**Classe** : `IndiceRevision` (`models.py:68-83`).
**Rôle métier** : référentiel des publications d'indices (Syntec, et
potentiellement d'autres familles via `famille`). Source des calculs de
révision annuelle.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `date_publication` | date | NOT NULL | | UNIQUE (`indices_revision_date_publication_key`) |
| `annee` | integer | | | |
| `mois` | varchar(10) | | `'AOUT'` | Valeurs typiques : `AOUT`, `OCTOBRE`, `AUTRE` (libre) |
| `famille` | varchar(50) | | `'SYNTEC'` | Famille d'indice |
| `valeur` | numeric(10,4) | NOT NULL | | Valeur publiée |
| `commentaire` | text | | | |
| `source_url` | varchar(500) | | | |
| `created_by` | varchar(100) | | | |
| `created_at` | timestamptz | | `now()` | |

**Référencé par** : `contrats.indice_reference_id`, `plan_facturation.indice_calcul_id`, `lots_facturation.indice_utilise_id`.

### 2.5 `contrats` — Contrats pluriannuels (table centrale)

**Classe** : `Contrat` (`models.py:86-151`).
**Rôle métier** : entité principale du module. Représente un engagement
pluriannuel client, avec dates, montant annuel HT, famille (Cosoluce, Cantine,
Maintenance, etc.), et chaîne d'avenants/renouvellements via auto-référence.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `numero_contrat` | varchar(100) | NOT NULL | | UNIQUE |
| `client_karlia_id` | varchar(100) | | | Pas de FK formelle vers `clients_cache.karlia_id` |
| `client_numero`, `client_nom` | varchar(20/255) | | | Snapshot dénormalisé |
| `date_debut`, `date_fin` | date | NOT NULL | | CHECK `date_fin > date_debut` (`ck_dates_coherentes`) |
| `nombre_annees` | integer | NOT NULL | | |
| `montant_annuel_ht` | numeric(12,2) | NOT NULL | | |
| `indice_reference_id` | uuid | | | FK → `indices_revision.id` (indice de référence à la signature) |
| `prorate_annee1` | boolean | | | |
| `prorate_nb_mois` | numeric(4,1) | | | Décimal pour gérer les demi-mois |
| `prorate_montant_ht` | numeric(12,2) | | | |
| `prorate_validated` | boolean | | | |
| `prorate_note` | text | | | |
| `prorate_demi_mois` | boolean | | `false` | |
| `notes_internes` | text | | | |
| `famille_contrat` | varchar(50) | | `'COSOLUCE'` | Détermine la règle de révision et le modèle Word |
| `contrat_parent_id` | uuid | | | FK auto → `contrats.id` (chaîne avenants/renouvellements) |
| `type_contrat` | varchar(30) | | côté Python `'CONTRAT'` | CHECK ∈ {CONTRAT, AVENANT, RENOUVELLEMENT} (`ck_type_contrat`) |
| `numero_avenant` | integer | | | Pour les enfants de type AVENANT |
| `statut` | varchar(30) | | côté Python `'BROUILLON'` | CHECK ∈ {EN_COURS, A_RENOUVELER, TERMINE, BROUILLON} (`ck_statut`) |
| `date_statut_change` | date | | | |
| `motif_fin` | text | | | |
| `avenants_fusionnes` | boolean | | | |
| `created_by` | varchar(100) | | | login de l'utilisateur |
| `created_at`, `updated_at`, `validated_at` | timestamptz | | `now()` (sauf validated_at) | |

**Relations SQLAlchemy** :
- `articles` ← `contrat_articles` (cascade delete, order_by `rang`)
- `plan_facturation` ← `plan_facturation` (cascade delete, order_by
  `numero_facture`)
- `documents` ← `documents_generes`
- `factures_karlia` ← `factures_karlia`
- `enfants` ← `contrats` (self-referential)
- `client` ← `ClientCache` (join custom sur `karlia_id`)
- `indice_reference` ← `IndiceRevision`

**Référencé par** : `contrat_articles.contrat_id`, `plan_facturation.contrat_id`, `documents_generes.contrat_id`, `factures_karlia.contrat_id` (SET NULL), `commandes.contrat_id` (SET NULL), `contrats.contrat_parent_id` (auto).

### 2.6 `contrat_articles` — Lignes article d'un contrat

**Classe** : `ContratArticle` (`models.py:154-174`).
**Rôle métier** : jusqu'à 8 lignes par contrat (rang 0 = principal, 1-7 =
annexes). Chaque ligne est un article de prestation avec quantité, prix HT,
TVA.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `contrat_id` | uuid | NOT NULL | | FK → `contrats.id` ON DELETE CASCADE |
| `rang` | integer | NOT NULL | | CHECK `rang BETWEEN 0 AND 7` (`ck_rang_valide`) |
| `article_karlia_id` | varchar(100) | | | Référence vers article Karlia |
| `designation` | varchar(500) | NOT NULL | | |
| `reference` | varchar(100) | | | |
| `prix_unitaire_ht` | numeric(12,4) | | | |
| `quantite` | numeric(10,3) | | côté Python `1` | |
| `unite` | varchar(50) | | | |
| `taux_tva` | numeric(5,2) | | côté Python `20.00` | |

Contrainte unique : `(contrat_id, rang)` (`uq_contrat_rang`).

### 2.7 `plan_facturation` — Plan prévisionnel de factures par contrat

**Classe** : `PlanFacturation` (`models.py:177-215`).
**Rôle métier** : décomposition année par année (et prorata éventuel) du
plan de facturation d'un contrat. Pivot entre la planification (montants
prévus) et la réalisation (montants révisés, émissions Karlia).

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `contrat_id` | uuid | NOT NULL | | FK → `contrats.id` ON DELETE CASCADE |
| `numero_facture` | integer | NOT NULL | | Ordre dans le plan |
| `annee_facturation` | integer | NOT NULL | | |
| `date_echeance` | date | NOT NULL | | |
| `type_facture` | varchar(20) | | côté Python `'ANNUELLE'` | CHECK ∈ {PRORATE, ANNUELLE} (`ck_type_facture`) |
| `montant_ht_prevu` | numeric(12,2) | | | Avant révision |
| `montant_annuel_precedent` | numeric(12,2) | | | Base de calcul |
| `taux_revision` | numeric(8,6) | | | Coefficient appliqué |
| `montant_revise_ht` | numeric(12,2) | | | Après révision |
| `indice_calcul_id` | uuid | | | FK → `indices_revision.id` |
| `montant_ht_facture` | numeric(12,2) | | | Effectivement facturé |
| `facture_karlia_id`, `facture_karlia_ref` | varchar(100) | | | Lien post-émission |
| `karlia_synchro_at` | timestamptz | | | |
| `karlia_statut` | varchar(50) | | | |
| `statut` | varchar(30) | | côté Python `'PLANIFIEE'` | CHECK ∈ {PLANIFIEE, CALCULEE, EMISE, ERREUR} (`ck_statut_facture`) |
| `erreur_message` | text | | | |
| `created_at` / `updated_at` | timestamptz | | `now()` | |

Contrainte unique : `(contrat_id, numero_facture)` (`uq_contrat_facture`).

### 2.8 `lots_facturation` — Historique des traitements en lot

**Classe** : `LotFacturation` (`models.py:218-232`).
**Rôle métier** : trace chaque exécution de la révision Syntec annuelle (qui
indice utilisé, combien de contrats, combien d'erreurs, rapport JSON détaillé).

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `annee_traitement` | integer | NOT NULL | | |
| `indice_utilise_id` | uuid | | | FK → `indices_revision.id` |
| `declenche_par` | varchar(100) | | | Login utilisateur |
| `declenche_at` | timestamptz | | `now()` | |
| `nb_contrats_traites` | integer | | côté Python `0` | |
| `nb_factures_emises` | integer | | côté Python `0` | |
| `nb_erreurs` | integer | | côté Python `0` | |
| `statut` | varchar(20) | | côté Python `'EN_COURS'` | Valeurs libres en DB (pas de CHECK) |
| `termine_at` | timestamptz | | | |
| `rapport_json` | json | | | Rapport détaillé du lot |

Pas de relation `relationship` côté SQLAlchemy.

### 2.9 `documents_generes` — Documents Word/PDF produits

**Classe** : `DocumentGenere` (`models.py:235-251`).
**Rôle métier** : journal des fichiers générés (un par génération), chemin
des fichiers `.docx` et `.pdf`, variables utilisées.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `contrat_id` | uuid | NOT NULL | | FK → `contrats.id` (pas de ON DELETE — risque d'orphelins, cf. 2.18) |
| `type_document` | varchar(50) | NOT NULL | | Ex. `CONTRAT_COSOLUCE`, `CONTRAT_MAINTENANCE` |
| `nom_fichier` | varchar(500) | NOT NULL | | |
| `chemin_docx` | varchar(1000) | | | Chemin relatif dans `./storage/documents_generes/` |
| `chemin_pdf` | varchar(1000) | | | |
| `modele_utilise` | varchar(200) | | | |
| `variables_json` | json | | | Dictionnaire des variables substituées dans le template |
| `generated_by` | varchar(100) | | | |
| `generated_at` | timestamptz | | `now()` | |

### 2.10 `modeles_documents` — Modèles Word uploadés

**Classe** : `ModeleDocument` (`models.py:254-265`).
**Rôle métier** : modèles `.docx` versionnés (un par type de contrat) avec
toggle `actif`.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `type_document` | varchar(50) | NOT NULL | | Ex. `CONTRAT_COSOLUCE` |
| `nom` | varchar(200) | NOT NULL | | |
| `version` | varchar(20) | | | |
| `chemin_fichier` | varchar(1000) | NOT NULL | | Chemin dans `./storage/modeles/` |
| `actif` | boolean | | côté Python `True` | Un seul `actif=true` par `type_document` (règle métier, non contrainte DB) |
| `uploaded_by` | varchar(100) | | | |
| `uploaded_at` | timestamptz | | `now()` | |
| `description` | text | | | |

Pas d'index unique partiel sur `(type_document) WHERE actif = TRUE` — la
règle "un seul modèle actif par type" est appliquée applicativement
seulement.

### 2.11 `utilisateurs` — Comptes du module

**Classe** : `Utilisateur` (`models.py:268-281`).
**Rôle métier** : authentification interne (JWT). Distinct des clients
Karlia.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | | PK |
| `login` | varchar(100) | NOT NULL | | UNIQUE |
| `email` | varchar(255) | NOT NULL | | UNIQUE |
| `nom_complet` | varchar(200) | | | |
| `password_hash` | varchar(500) | NOT NULL | | bcrypt via passlib |
| `role` | varchar(30) | | côté Python `'UTILISATEUR'` | Valeurs lues dans le code : `ADMIN`, `GESTIONNAIRE`, `FORMATEUR`, `TECHNICIEN` (cf. section 6.11). Aucune CHECK en DB. |
| `actif` | boolean | | côté Python `True` | |
| `derniere_connexion` | timestamptz | | | |
| `formateur_id` | integer | | | FK → `formateurs.id` (lie un compte au formateur correspondant) |
| `created_at` | timestamptz | | `now()` | |

### 2.12 `parametres` — Configuration globale clé/valeur

**Classe** : `Parametre` (`models.py:284-291`).
**Rôle métier** : magasin clé/valeur pour la configuration applicative
(clés Karlia, credentials Chorus, état de synchro, etc.). PK = `cle`
(varchar). Pas d'ID UUID.

| Colonne | Type | Nullable | Défaut |
| --- | --- | --- | --- |
| `cle` | varchar(100) | NOT NULL | PK |
| `valeur` | text | | |
| `description` | text | | |
| `updated_at` | timestamptz | | `now()` |

Clés effectivement utilisées (lues dans le code) :

| Clé | Source de lecture |
| --- | --- |
| `karlia_api_key` | `main.py` au startup + `parametres.py` (PUT) |
| `derniere_synchro` | `main.py` `synchro_karlia()` |
| `synchro_stats` | idem |
| `chorus_client_id`, `chorus_client_secret` | `chorus_service.get_chorus_service_from_params()` |
| `chorus_tech_username`, `chorus_tech_password` | idem |
| `chorus_siret_emetteur` | idem |
| `chorus_code_service`, `chorus_code_banque` | idem (optionnels) |
| `chorus_id_fournisseur`, `chorus_id_utilisateur_courant` | idem (auto-config) |
| `chorus_mode_qualification` | idem (`'true'`/`'false'`) |

### 2.13 `commandes` — Devis acceptés Karlia importés

**Classe** : `Commande` (`models.py:298-341`).
**Rôle métier** : représente un devis Karlia accepté à transformer en
prestation. Si la commande débouche sur un engagement pluriannuel, elle est
liée à un `contrat_id`.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | integer | NOT NULL | sequence | PK (séquence `commandes_id_seq`) |
| `karlia_document_id` | integer | NOT NULL | | UNIQUE (`commandes_karlia_document_id_key`) |
| `karlia_customer_id` | integer | | | |
| `karlia_opportunity_id` | integer | | | Commentaire DB : "ID de l opportunité Karlia liée au devis" |
| `reference_devis` | varchar(100) | | | |
| `client_nom`, `client_email`, `client_telephone`, `client_adresse`, `client_siret` | varchar/text | | | Snapshot dénormalisé |
| `montant_ht`, `montant_tva`, `montant_ttc` | numeric(15,2) | | | |
| `date_devis`, `date_acceptation` | date | | | |
| `date_import` | timestamp (sans TZ) | | `CURRENT_TIMESTAMP` | **Divergence** : modèle déclare `DateTime(timezone=True)` mais DB est `timestamp without time zone` (cf. 2.18) |
| `date_validation` | timestamp (sans TZ) | | | |
| `statut` | varchar(50) | | `'nouvelle'` | Valeurs lues dans le code : `nouvelle`, `validee`, `sans_planification`, `deployee`, `facturee`, `archivee`. Pas de CHECK en DB. |
| `type_traitement` | varchar(50) | | | |
| `necessite_contrat` | boolean | | `false` | |
| `date_planifiee` | date | | | |
| `intervenant_id` | integer | | | **Legacy** : pas de FK, cohabite avec `formateur_id`. Cf. 2.18. |
| `intervenant_nom` | varchar(255) | | | Snapshot legacy |
| `notes_planification` | text | | | |
| `contrat_id` | uuid | | | FK → `contrats.id` ON DELETE SET NULL |
| `pdf_devis` | bytea | | | **Divergence** : modèle déclare `Column(Text)` avec commentaire "Base64 encoded" mais DB est `bytea` (cf. 2.18) |
| `pdf_devis_nom` | varchar(255) | | | |
| `pdf_url` | text | | | |
| `created_at`, `updated_at` | timestamp (sans TZ) | | `CURRENT_TIMESTAMP` | Idem 2.18 |
| `created_by`, `updated_by` | integer | | | Pas de FK vers `utilisateurs.id` (qui est UUID, incompatible) |
| `formateur_id` | integer | | | FK → `formateurs.id` |
| `facture_karlia_id`, `facture_karlia_ref` | varchar(50) | | | Lien post-facturation |

Index : `idx_commandes_formateur`, `idx_commandes_karlia_id`, `idx_commandes_necessite_contrat`, `idx_commandes_statut`.

### 2.14 `commande_lignes` — Lignes d'une commande

**Classe** : `CommandeLigne` (`models.py:344-367`).

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | integer | NOT NULL | sequence | PK |
| `commande_id` | integer | | | FK → `commandes.id` ON DELETE CASCADE |
| `karlia_product_id` | varchar(50) | | | |
| `designation` | varchar(500) | | | |
| `description` | text | | | |
| `quantite` | numeric(10,3) | | `1` | |
| `unite` | varchar(50) | | | |
| `prix_unitaire_ht` | numeric(15,2) | | | |
| `taux_tva` | numeric(5,2) | | | |
| `montant_ht`, `montant_tva`, `montant_ttc` | numeric(15,2) | | | |
| `discount_type` | varchar(20) | | | `PERCENT` ou `AMOUNT` (libre) |
| `discount_value` | numeric(15,6) | | | |
| `discount_percent` | numeric(15,6) | | | |
| `ordre` | integer | | `0` | |
| `created_at` | timestamp (sans TZ) | | `CURRENT_TIMESTAMP` | |

### 2.15 `prestations` — Prestations à planifier (issues des lignes de commande)

**Classe** : `Prestation` (`models.py:472-501`).
**Rôle métier** : chaque ligne de commande peut générer une ou plusieurs
prestations à planifier dans un agenda (formateur, dates, lieu, Google
Calendar).

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | integer | NOT NULL | sequence | PK |
| `commande_id` | integer | NOT NULL | | FK → `commandes.id` ON DELETE CASCADE |
| `commande_ligne_id` | integer | | | FK → `commande_lignes.id` ON DELETE SET NULL |
| `formateur_id` | integer | | | FK → `formateurs.id` |
| `agenda_formateur_id` | integer | | | FK → `formateurs.id` (formateur dont on utilise l'agenda Google) |
| `google_calendar_id` | varchar(255) | | | |
| `google_event_id` | varchar(255) | | | |
| `google_sync_status` | varchar(50) | | côté Python `'pending'` | |
| `google_sync_error` | text | | | |
| `google_synced_at` | timestamptz | | | |
| `designation` | varchar(500) | NOT NULL | | |
| `description` | text | | | |
| `duree_jours` | numeric(5,2) | | `1` | Demi-journées possibles |
| `date_prevue` | date | | | |
| `date_planifiee` | date | | | |
| `heure_debut`, `heure_fin` | time (sans TZ) | | | |
| `lieu` | varchar(500) | | | |
| `statut` | varchar(50) | | `'a_planifier'` | Valeurs : `a_planifier`, `planifiee`, `realisee`, `annulee` |
| `notes` | text | | | |
| `created_at`, `updated_at` | timestamptz | | `now()` | |

Index : `idx_prestations_commande`, `idx_prestations_formateur`, `idx_prestations_statut`.

### 2.16 `formateurs` — Référentiel des formateurs

**Classe** : `Formateur` (`models.py:451-468`).
**Rôle métier** : référentiel des intervenants assignables aux commandes
et prestations.

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | integer | NOT NULL | sequence | PK |
| `nom` | varchar(255) | NOT NULL | | |
| `prenom` | varchar(255) | | | |
| `email` | varchar(255) | NOT NULL | | UNIQUE |
| `email_google` | varchar(255) | | | Email du compte Google séparé (pour partage d'agenda) |
| `telephone` | varchar(50) | | | |
| `actif` | boolean | | `true` | |
| `couleur` | varchar(7) | | `'#3788d8'` | Couleur hex pour l'agenda |
| `created_at`, `updated_at` | timestamptz | | `now()` | |

### 2.17 `factures_karlia` et `transmissions_chorus`

#### 2.17.1 `factures_karlia` — Cache local des factures Karlia pour transmission Chorus Pro

**Classe** : `FactureKarlia` (`models.py:374-415`).

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | `gen_random_uuid()` | PK |
| `karlia_document_id` | integer | NOT NULL | | UNIQUE |
| `numero_facture` | varchar(100) | NOT NULL | | |
| `reference` | varchar(200) | | | |
| `client_karlia_id` | integer | NOT NULL | | Pas de FK formelle vers `clients_cache` (types incompatibles : `clients_cache.karlia_id` est varchar) |
| `client_nom` | varchar(255) | | | |
| `client_siret` | varchar(14) | | | |
| `client_code_service` | varchar(100) | | | Code service exécutant Chorus Pro |
| `montant_ht` | numeric(15,2) | NOT NULL | | |
| `montant_tva` | numeric(15,2) | | | |
| `montant_ttc` | numeric(15,2) | | | |
| `date_facture` | date | NOT NULL | | |
| `date_echeance` | date | | | |
| `statut_chorus` | varchar(50) | | `'NON_TRANSMISE'` | CHECK ∈ {NON_TRANSMISE, EN_COURS, TRANSMISE, ACCEPTEE, REJETEE, ERREUR} (`ck_statut_chorus`) |
| `date_transmission` | timestamptz | | | |
| `chorus_numero_flux` | varchar(100) | | | |
| `chorus_statut_technique` | varchar(100) | | | |
| `chorus_date_statut` | timestamptz | | | |
| `chorus_message_erreur` | text | | | |
| `contrat_id` | uuid | | | FK → `contrats.id` ON DELETE SET NULL |
| `imported_at`, `updated_at` | timestamptz | | `now()` | |

Index : `idx_factures_karlia_client`, `idx_factures_karlia_date`, `idx_factures_karlia_statut`.

#### 2.17.2 `transmissions_chorus` — Journal des envois Chorus Pro

**Classe** : `TransmissionChorus` (`models.py:418-443`).

| Colonne | Type | Nullable | Défaut | Notes |
| --- | --- | --- | --- | --- |
| `id` | uuid | NOT NULL | `gen_random_uuid()` | PK |
| `facture_id` | uuid | NOT NULL | | FK → `factures_karlia.id` ON DELETE CASCADE |
| `chorus_id_flux` | varchar(100) | | | `numeroFluxDepot` retourné par PISTE |
| `chorus_id_facture` | varchar(100) | | | `identifiantFactureCPP` |
| `statut` | varchar(50) | NOT NULL | `'EN_ATTENTE'` | CHECK ∈ {EN_ATTENTE, EN_COURS, SUCCES, ECHEC, ANNULE} (`ck_statut_transmission`) |
| `code_retour` | varchar(50) | | | HTTP status |
| `message_retour` | text | | | |
| `payload_json` | jsonb | | | `service.last_request` (vrai body envoyé à PISTE) |
| `reponse_json` | jsonb | | | `service.last_response` structurée (`status_code`, `headers`, `body_text`, `body_json`, `x_correlation_id`) |
| `is_test` | boolean | | `false` | Ajouté lors du fix `fix/chorus-payload-v5-01` |
| `transmis_par` | varchar(100) | | | |
| `transmis_at` | timestamptz | | `now()` | |

Index : `idx_transmissions_facture`, `idx_transmissions_statut`.

### 2.18 Divergences `models.py` ↔ schéma DB live

Les incohérences identifiées (à corriger lors de la refonte) :

| Ligne `models.py` | Modèle déclare | DB réelle | Impact |
| --- | --- | --- | --- |
| `ClientCache.numero_client` (ligne 26) | `unique=True` | Pas d'index UNIQUE | Permet des doublons silencieux ; à corriger après dédoublonnage |
| `Commande.created_at` / `updated_at` / `date_import` / `date_validation` (lignes 317, 318, 330, 331) | `DateTime(timezone=True)` | `timestamp without time zone` | Lecture/écriture sans TZ — pas bloquant mais incohérent avec `Contrat` |
| `CommandeLigne.created_at` (ligne 364) | `DateTime(timezone=True)` | `timestamp without time zone` | Idem |
| `Commande.pdf_devis` (ligne 327) | `Column(Text)` # "Base64 encoded" | `bytea` | Sérialisation binaire en réalité, le code Python doit gérer le décodage. **À vérifier dans les routes qui lisent `pdf_devis`** |
| `Commande.intervenant_id` (ligne 323) | Pas de FK | Pas de FK non plus | Legacy avant `formateur_id`, devrait être supprimé après vérification que personne ne l'utilise |
| `DocumentGenere.contrat_id` (ligne 240) | `ForeignKey("contrats.id")` sans `ondelete` | FK sans ON DELETE | Risque d'orphelins si un contrat est supprimé (pas observé en pratique car la suppression de contrat n'est pas exposée à l'UI) |
| `Utilisateur.created_by` / `updated_by` sur `Commande` (intégers) | aucun FK | aucun FK | `commandes.created_by` est un INTEGER, mais `utilisateurs.id` est un UUID — incompatible. Probablement vide ou rempli avec un ID legacy. |

### 2.19 Diagramme des relations

Légende : `→` FK simple, `⇉` FK cascade, `↔` jointure non-FK (matching par
clé fonctionnelle).

```
                     ┌─────────────┐
                     │ utilisateurs│
                     │   (uuid)    │
                     └──────┬──────┘
                            │ formateur_id (int)
                            ▼
                     ┌─────────────┐
              ┌──────│ formateurs  │──────┐
              │      │   (int)     │      │
              │      └─────────────┘      │
              │            ▲              │
              │            │              │
              │ formateur_id            agenda_formateur_id
              │            │              │
   ┌──────────▼─┐    ┌─────┴─────┐ ┌──────▼──────────┐
   │ commandes  │ ──►│prestations│◄┘                 │
   │   (int)    │⇉   │   (int)   │                   │
   └────┬───────┘    └────┬──────┘                   │
        │ ⇉ (cascade)     │ FK SET NULL              │
        ▼                 ▼                          │
  ┌─────────────────┐  ┌──────────────┐              │
  │ commande_lignes │  │              │              │
  │     (int)       │  │              │              │
  └─────────────────┘  │              │              │
        │              │              │              │
        │ contrat_id (uuid, SET NULL) │              │
        ▼              ▼              ▼              │
                ┌──────────────┐                     │
                │   contrats   │◄───────┐            │
                │    (uuid)    │        │ parent     │
                └──┬───┬───┬───┘────────┘            │
                   │   │   │                         │
                   │   │   │                         │
        ⇉(cascade) │   │   │ SET NULL                │
                   ▼   │   ▼                         │
       ┌───────────────┴┐  ┌──────────────────┐      │
       │contrat_articles│  │ factures_karlia  │      │
       │    (uuid)      │  │     (uuid)       │      │
       └────────────────┘  └────────┬─────────┘      │
                                    │                │
                                    │ ⇉(cascade)     │
                                    ▼                │
                          ┌──────────────────┐       │
                          │transmissions_    │       │
                          │   chorus (uuid)  │       │
                          └──────────────────┘       │
                                                     │
                   │ ⇉(cascade)                      │
                   ▼                                 │
       ┌───────────────────┐                         │
       │ plan_facturation  │                         │
       │     (uuid)        │                         │
       └────┬──────────────┘                         │
            │ indice_calcul_id                       │
            ▼                                        │
   ┌──────────────────┐                              │
   │ indices_revision │◄──── lots_facturation.indice_utilise_id
   │     (uuid)       │◄──── contrats.indice_reference_id
   └──────────────────┘

   ┌─────────────┐
   │ clients_    │  ↔ contrats.client_karlia_id (matching par karlia_id, pas de FK)
   │ cache (uuid)│  ↔ factures_karlia.client_karlia_id (idem)
   └─────────────┘

   ┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
   │ articles_   │    │ documents_       │    │  modeles_    │
   │ cache (uuid)│    │ generes (uuid)   │    │  documents   │
   └─────────────┘    │                  │    │   (uuid)     │
                      │  contrat_id FK   │    └──────────────┘
                      └──────────────────┘

   ┌─────────────┐
   │ parametres  │  (clé/valeur, autonome)
   │   (string)  │
   └─────────────┘
```

### 2.20 Notes sur les cascades de suppression

Cascades définies (DB) :
- `contrats` → `contrat_articles` (CASCADE)
- `contrats` → `plan_facturation` (CASCADE)
- `commandes` → `commande_lignes` (CASCADE)
- `commandes` → `prestations` (CASCADE)
- `factures_karlia` → `transmissions_chorus` (CASCADE)

SET NULL (l'enfant survit mais perd le lien) :
- `contrats` → `commandes.contrat_id`
- `contrats` → `factures_karlia.contrat_id`
- `commande_lignes` → `prestations.commande_ligne_id`

Pas de cascade / pas de ON DELETE (risque d'orphelins ou de violation de FK
si suppression sans déliage manuel) :
- `contrats` → `documents_generes` (pas d'ON DELETE déclaré)
- `formateurs` → toutes ses FK (commandes, prestations, utilisateurs)
- `indices_revision` → contrats, plan_facturation, lots_facturation

La règle "délier les FK avant `db.delete()`" évoquée dans `CODING_RULES.md`
trouve sa source ici.

---

## 3. API Backend (FastAPI)

### 3.1 Vue d'ensemble — montage des routers

Source : `backend/app/main.py:21-45`. **15 routers** sont montés, en
combinant le préfixe défini lors de l'`include_router` et le préfixe interne
défini sur l'`APIRouter` du fichier.

| Fichier | `prefix` à `include_router` | Préfixe interne | URL effective | Tag OpenAPI |
| --- | --- | --- | --- | --- |
| `api/auth.py` | `/api/auth` | (none) | `/api/auth/*` | `auth` |
| `api/clients.py` | `/api/clients` | (none) | `/api/clients/*` | `Clients` |
| `api/produits.py` | `/api/produits` | (none) | `/api/produits/*` | `Produits / Articles` |
| `api/contrats.py` | `/api/contrats` | (none) | `/api/contrats/*` | `Contrats` |
| `api/facturation.py` | `/api/facturation` | (none) | `/api/facturation/*` | `Facturation` |
| `api/indices.py` | `/api/indices` | (none) | `/api/indices/*` | `Indices Syntec` |
| `api/utilisateurs.py` | `/api/utilisateurs` | (none) | `/api/utilisateurs/*` | `Utilisateurs` |
| `api/documents.py` | `/api/documents` | (none) | `/api/documents/*` | `Documents` |
| `api/parametres.py` | `/api/parametres` | (none) | `/api/parametres/*` | `Paramètres` |
| `api/audit.py` | `/api/audit` | (none) | `/api/audit/*` | `Audit` |
| `api/commandes.py` | `/api/commandes` | (none) | `/api/commandes/*` | `Commandes` |
| `api/formateurs.py` | `/api/formateurs` | (none) | `/api/formateurs/*` | `Formateurs` |
| `api/prestations.py` | `/api/prestations` | (none) | `/api/prestations/*` | `Prestations` |
| `api/chorus.py` | `/api` | `/chorus` | `/api/chorus/*` | `Chorus Pro` |
| `api/dashboard.py` | `/api/dashboard` | (none) | `/api/dashboard/*` | `Dashboard` |

**Endpoints racine** (définis directement dans `main.py`, hors router) :

| Méthode | Path | Description |
| --- | --- | --- |
| GET | `/api/health` | Healthcheck `{"status":"ok","version":"1.0.0"}` — **le numéro de version est en dur et n'a jamais bougé**, désynchronisé des tags Git (cf. section 1.10). |
| GET | `/api/synchro/statut` | Retourne `derniere_synchro` + `synchro_stats` depuis `parametres`. |
| POST | `/api/synchro/lancer` | Déclenche `synchro_karlia()` (clients + articles, séquentiel) puis renvoie les nouvelles stats. |

CORS configuré via `settings.CORS_ORIGINS` (liste explicite, pas wildcard).

### 3.2 Authentification, JWT et droits

Sources : `api/auth.py`, `api/utilisateurs.py`, `core/config.py`.

#### 3.2.1 Endpoints d'authentification

| Méthode | Path | Fonction (`auth.py`) | Rôle requis | Notes |
| --- | --- | --- | --- | --- |
| POST | `/api/auth/login` | `login` | aucun | OAuth2PasswordRequestForm (`username`+`password`). Vérifie bcrypt. Renvoie `access_token`, `token_type=bearer`, `nom_complet`, `role`, `formateur_id`. |
| GET | `/api/auth/me` | `get_me` | tout connecté | Renvoie le profil du JWT actuel. |
| GET | `/api/utilisateurs/droits` | `get_droits` (`utilisateurs.py`) | tout connecté | Renvoie `{role, droits, roles_disponibles, formateur_id}` — pivot pour piloter l'UI selon le rôle. |

**Divergence importante (`auth.py:23`)** : `creer_token` met `expire = datetime.utcnow() + timedelta(hours=24)` (24h en dur). Or `config.py` déclare `ACCESS_TOKEN_EXPIRE_MINUTES = 480` (8h). Le setting n'est jamais utilisé — le token vit 24h.

#### 3.2.2 Rôles et matrice de droits

Source : `api/utilisateurs.py:14-21`. Le mapping rôle → droits est **codé en dur** dans `DROITS` (Python dict) — pas en base.

| Rôle | contrats_lecture | contrats_ecriture | facturation | indices | commandes | parametres | utilisateurs | formateurs | toutes_prestations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADMIN | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| GESTIONNAIRE | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ |
| FORMATEUR | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| TECHNICIEN | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

Note : aucune CHECK constraint en DB ne valide la valeur de `utilisateurs.role` — un `INSERT` direct avec un rôle inconnu serait accepté et tomberait sur le fallback "FORMATEUR" côté `get_droits`.

#### 3.2.3 Garde d'accès

- `Depends(get_current_user)` est utilisé sur la majorité des endpoints **sauf** `auth/login`, `dashboard/stats`, certains GET de `contrats` et `indices`, et les endpoints `/api/synchro/*` racine. À noter : **`api/contrats.py` n'utilise PAS `get_current_user`** — les routes de modification de contrats sont accessibles à toute origine atteignant le backend, ce qui n'est protégé que par le fait que nginx n'expose pas `/api` sans auth applicative côté frontend. Trou de sécurité potentiel si un endpoint contourne nginx. À traiter en refonte.
- `Depends(require_admin)` dans `utilisateurs.py:23-26` et plusieurs PUT/DELETE dans `parametres.py` (vérification de `role == "ADMIN"` en dur).

### 3.3 Module Contrats — `api/contrats.py`

Tous les endpoints sous `/api/contrats`. **Aucun ne fait `Depends(get_current_user)`** (cf. 3.2.3).

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `` | `lister_contrats` | Filtres : `statut`, `recherche` (numéro/nom/numéro client, ilike), `annee` (fenêtre `date_debut ≤ 31/12/annee` AND `date_fin ≥ 01/01/annee`), `familles` (liste CSV, uppercased), `limit` (≤200), `offset`. Tri `date_fin ASC`. Renvoie `{total, data}`. |
| GET | `/renouvellements` | `contrats_a_renouveler` | Fenêtre mois/année (défauts = courant), filtre `famille`, ne renvoie que `statut IN (EN_COURS, A_RENOUVELER)`. |
| POST | `` | `creer_contrat` | Création BROUILLON. Vérifie unicité `numero_contrat`, cohérence dates. **Calcule** prorata + nombre années + génère le plan de facturation. Crée `Contrat`, `ContratArticle[]`, `PlanFacturation[]` dans une seule transaction. |
| GET | `/{contrat_id}` | `obtenir_contrat` | Détail complet (champs + articles ordonnés + plan_facturation). |
| POST | `/{contrat_id}/valider` | `valider_contrat` | BROUILLON → EN_COURS. Garde : doit avoir au moins 1 article, prorata validé si applicable. Set `validated_at`. **Le commentaire docstring dit "Déclenche la génération des documents (asynchrone)" mais ce n'est pas implémenté** — aucune logique post-validation autre que le passage de statut. À considérer comme un hook futur. |
| PUT | `/{contrat_id}` | `modifier_contrat` | BROUILLON uniquement. Met à jour champs simples + dates + articles (replace all) + regénère plan si dates/montant changent. Imports locaux dans le corps (style "lazy"). |
| DELETE | `/{contrat_id}` | `supprimer_contrat` | BROUILLON uniquement. Cascade DB : `contrat_articles`, `plan_facturation`. |
| POST | `/{contrat_id}/terminer` | `terminer_contrat` | Force `statut=TERMINE`. Champ `motif_fin` accepte une query string `motif`. |
| POST | `/{contrat_id}/renouveler` | `renouveler_contrat` | **Cœur métier**, 3 branches : `FIN` (TERMINE), `SPONTANE` (prolonge `date_fin` +1 an + ajoute une ligne au plan), `NOUVEAU_CONTRAT` (archive l'ancien, copie articles + intègre articles d'avenants enfants si rang ≤7, génère un nouveau plan, statut BROUILLON). Le `numero_contrat` du nouveau doit être fourni explicitement. |
| POST | `/renouveler-lot` | `renouveler_lot` | Bulk pour `SPONTANE` et `FIN` uniquement (pas `NOUVEAU_CONTRAT`). Boucle Python, commit par contrat, capture les erreurs individuellement. |

**Effets de bord** dans `creer_contrat` :
- Trois INSERTs (Contrat + ContratArticle[] + PlanFacturation[]) en un commit
- Calculs déterministes : `calculer_prorata`, `calculer_nombre_annees`, `generer_plan_facturation` (services)
- Pas d'appel externe

**Effets de bord** dans `renouveler_contrat` mode `NOUVEAU_CONTRAT` :
- Mute l'ancien contrat (TERMINE)
- Crée un nouveau contrat BROUILLON
- **Met aussi à jour le statut des avenants enfants** (`avenant.statut = "TERMINE"`)
- Pas d'appel externe

### 3.4 Module Commandes — `api/commandes.py`

Tous les endpoints sous `/api/commandes`. Les routes de listing utilisent `joinedload` pour éviter les N+1 sur lignes/prestations/formateur.

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| POST | `/sync` | `sync_devis_karlia` | Appelle `karlia_devis_service.sync_devis_acceptes()`. Query param `force_full` pour ignorer la dernière date de synchro. |
| GET | `/stats` | `get_commandes_stats` | 5 counts : `nouvelles`, `a_planifier`, `planifiees`, `contrats_a_creer` (`necessite_contrat=TRUE AND contrat_id IS NULL`), `total`. |
| GET | `/nouvelles`, `/a-planifier`, `/planifiees`, `/terminees` | `_get_commandes_by_statut` | Pagination + filtre `search` (client_nom OR reference_devis, ilike). `terminees` → `statut="deployee"` (subtilité métier : "deployee" = prestations réalisées). |
| GET | `/contrats-a-creer` | `get_contrats_a_creer` | Filtre `necessite_contrat=TRUE AND contrat_id IS NULL`. |
| GET | `/{commande_id}` | `get_commande` | Détail. |
| POST | `/{commande_id}/valider` | `valider_commande` | `statut: nouvelle → a_planifier OU deployee` selon `type_traitement` (`a_planifier` ou `sans_planification`). Met `necessite_contrat`. |
| POST | `/{commande_id}/planifier` | `planifier_commande` | `a_planifier → planifiee`. Met `date_planifiee`, `intervenant_id`, `intervenant_nom`, `notes_planification`. **Note** : utilise les colonnes legacy `intervenant_*` (cf. 2.18), pas `formateur_id`. |
| POST | `/{commande_id}/terminer` | `terminer_commande` | `* → terminee` sans garde. **Mais** la sémantique métier de "terminée" est portée par `deployee` (voir `/terminees` ci-dessus). Statut `terminee` cohabite avec `deployee` — incohérence. |
| POST | `/{commande_id}/lier-contrat/{contrat_id}` | `lier_contrat_commande` | Met `contrat_id` sur la commande. Pas de validation que `necessite_contrat=TRUE` au préalable. |
| GET | `/{commande_id}/pdf` | `get_commande_pdf` | **Redirige** vers `commande.pdf_url` (Karlia direct). Le code de fallback `StreamingResponse` lit `pdf_devis` (bytea) avec base64 decode — **mais le `raise HTTPException` ligne 411 est exécuté avant**, rendant tout le code en dessous (lignes 413-426) **inateignable**. Vestige d'un refactor. |
| POST | `/{commande_id}/facturer` | `facturer_commande` | Émet une facture Karlia depuis une commande `deployee`. Calcule `unit_price` avec gestion des remises (PERCENT/AMOUNT). Appelle `karlia.creer_facture()`. Met à jour `commande.statut = "facturee"`, `facture_karlia_id`, `facture_karlia_ref`. **Effet de bord externe** : POST sur Karlia. |

**Statuts effectifs de `commandes.statut` (lus dans le code)** : `nouvelle`, `a_planifier`, `planifiee`, `sans_planification` (jamais mis directement, le code passe `deployee`), `deployee`, `terminee` (legacy), `facturee`, `archivee` (jamais set dans le code lu). **Aucune CHECK en DB** → cohabitation possible de statuts incohérents.

### 3.5 Module Facturation (révision Syntec) — `api/facturation.py`

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `/apercu/{annee}` | `apercu_facturation` | Liste les plans `PLANIFIEE`/`CALCULEE` de l'année cible avec leur contrat `EN_COURS`, filtrable par `famille`. Calcule à la volée la règle de révision applicable (`get_regle_revision`) et vérifie la disponibilité des indices (`verifier_indices_disponibles`). Champ `facturable = annee <= annee_courante`. |
| POST | `/calculer` | `calculer_factures` | Pour chaque `plan_id`, calcule le `montant_revise_ht` selon la famille (Cosoluce/Cantine/Maintenance/Digitech/etc.). Pour **Digitech**, requiert un `nouveaux_montants[plan_id]` (saisie manuelle). Première année du contrat = pas de révision (taux 1.0). **Garde pré-calcul** via `validation_service.valider_pre_calcul`. Statut → `CALCULEE`. |
| POST | `/lancer` | `lancer_facturation` | Émet les factures Karlia pour les plans `PLANIFIEE`/`CALCULEE` listés. Construit une ligne Karlia **par article du contrat**, applique le `taux_revision`, ajuste l'arrondi sur la dernière ligne pour coller au total HT exact. Appelle `karlia.traitement_lot_factures()` (rate-limité). **Garde post-émission** via `validation_service.valider_post_emission`. Renvoie un `lot_id` (UUID jeté, non persisté). |
| GET | `/lot/{lot_id}` | `statut_lot` | **Stub** : renvoie toujours `{statut: "TERMINE"}`. Pas de persistance du lot — incohérent avec la table `lots_facturation` qui existe en DB mais n'est jamais alimentée par cet endpoint. |

**Effets de bord critiques** :
- `/lancer` envoie N requêtes Karlia (`POST /documents`) avec rate-limit interne 80 req/min
- Met à jour `PlanFacturation.statut`, `.facture_karlia_id`, `.facture_karlia_ref`, `.montant_annuel_precedent`
- **Aucune ligne dans `lots_facturation`** alors que la table existe (cf. table 2.8)

### 3.6 Module Chorus Pro — `api/chorus.py`

Détaillé dans la branche `fix/chorus-payload-v5-01` (doc `docs/CHORUS_PRO_RACCORDEMENT.md`). Récapitulatif des endpoints :

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `/api/chorus/test-connexion` | `tester_connexion_chorus` | Ping OAuth PISTE — n'appelle PAS Chorus, valide juste `client_id`/`client_secret`. |
| POST | `/api/chorus/auto-config` | `auto_config_chorus` | Appelle `recuperer_utilisateur_courant()` puis persiste `chorus_id_fournisseur` + `chorus_id_utilisateur_courant`. **KO actuellement** — URL `/recuperer/utilisateurCourant` retourne 403 (n'existe pas dans la spec V5.01 ; à remplacer par `recupererStructuresActivesPourFournisseur`). |
| POST | `/api/chorus/synchro-factures` | `synchroniser_factures_karlia` | Importe les factures Karlia (`type=4`, `status=1`) vers `factures_karlia`. |
| GET | `/api/chorus/factures` | `lister_factures` | Filtres `statut`, `date_debut`, `date_fin`, `search`. |
| GET | `/api/chorus/factures/{id}` | `obtenir_facture` | Détail. |
| PUT | `/api/chorus/factures/{id}/siret` | `mettre_a_jour_siret` | Setter SIRET destinataire + `client_code_service` (NON_TRANSMISE/ERREUR/REJETEE uniquement). |
| POST | `/api/chorus/transmettre` | `transmettre_factures` | Boucle `facture_ids`, appelle `service.soumettre_facture()`, persiste `TransmissionChorus` + statut sur facture. Mode `dry_run` disponible (renvoie le payload sans envoyer). |
| POST | `/api/chorus/test-soumission` | `test_soumission_chorus` | Soumission de validation avec facture fictive. Crée un `FactureKarlia` synthétique (`karlia_document_id = -int(timestamp)`) + `TransmissionChorus` avec `is_test=TRUE`. |
| GET | `/api/chorus/factures/{id}/transmissions` | `historique_transmissions` | Liste les tentatives pour une facture. |
| POST | `/api/chorus/rechercher-structure` | `rechercher_structure` | Cherche une structure Chorus par SIRET. |
| GET | `/api/chorus/statistiques` | `statistiques_chorus` | Groupe par `statut_chorus` avec count + somme HT. |

### 3.7 Module Paramètres — `api/parametres.py`

| Méthode | Path | Fonction | Rôle requis | Description |
| --- | --- | --- | --- | --- |
| GET | `/api/parametres/` | `get_parametres` | tout connecté | Renvoie toutes les clés/valeurs + `karlia_api_key_apercu` (8 premiers chars) + `derniere_synchro` + `synchro_stats`. **Note** : ne masque PAS les credentials Chorus (cf. 3.7 — un GET séparé existe pour ça). |
| PUT | `/api/parametres/karlia-api-key` | `update_karlia_api_key` | ADMIN | Met à jour la clé + recharge `karlia.api_key` (instance globale) à chaud. |
| POST | `/api/parametres/tester-connexion` | `tester_connexion` | tout connecté | Appelle `karlia.tester_connexion()`, extrait company/siret/expiration. |
| POST | `/api/parametres/vider-cache` | `vider_cache` | ADMIN | DELETE `clients_cache` + `articles_cache` + supprime les params `derniere_synchro` et `synchro_stats`. **N'efface PAS** les contrats / factures / commandes — c'est bien un cache au sens strict. |
| GET | `/api/parametres/chorus` | `get_chorus_params` | tout connecté | Liste les 10 clés Chorus, **masque** `chorus_client_secret` et `chorus_tech_password` avec `'••••••••'`. |
| PUT | `/api/parametres/chorus` | `update_chorus_params` | ADMIN | Met à jour les params Chorus. **Skip** les champs égaux à `'••••••••'` (préservation du secret existant). |

### 3.8 Module Utilisateurs — `api/utilisateurs.py`

| Méthode | Path | Fonction | Rôle requis | Description |
| --- | --- | --- | --- | --- |
| GET | `/api/utilisateurs/droits` | `get_droits` | tout connecté | Cf. 3.2.2. |
| GET | `/api/utilisateurs` | `lister_utilisateurs` | ADMIN | Liste avec nom du formateur associé. |
| POST | `/api/utilisateurs` | `creer_utilisateur` | ADMIN | Crée un compte. FORMATEUR et TECHNICIEN exigent un `formateur_id`. Hashage bcrypt. |
| PUT | `/api/utilisateurs/{user_id}` | `modifier_utilisateur` | ADMIN | Met à jour. **Garde** : un admin ne peut pas se rétrograder lui-même. |
| DELETE | `/api/utilisateurs/{user_id}` | `supprimer_utilisateur` | ADMIN | **Garde** : un utilisateur ne peut pas se supprimer lui-même. Hard delete (pas de soft-delete via `actif=False`). |

### 3.9 Module Clients — `api/clients.py`

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `` | `lister_clients` | Liste les clients du cache local. |
| GET | `/search` | `rechercher_clients_cache` | Recherche par nom/siret/numéro (local, sans appel Karlia). |
| GET | `/numero-suivant` | `prochain_numero_client` | Renvoie le prochain numéro disponible (basé sur `MAX(numero_client)`). |
| POST | `` | `creer_client` | Crée un client **directement dans Karlia** via `karlia.creer_client()` + le rapatrie en cache local. Effet de bord externe. |
| GET | `/{karlia_id}/fiche` | `fiche_client` | Vue complète d'un client + ses contrats + factures (vue détail UI). |
| GET | `/{karlia_id}` | `obtenir_client` | Détail simple. |
| POST | `/synchro` | `synchroniser_clients` | Force une synchro Karlia → cache. |

### 3.10 Module Produits — `api/produits.py`

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `` | `lister_produits` | Liste depuis cache local. |
| POST | `/synchro` | `synchroniser_produits` | Re-synchronise depuis Karlia. |

### 3.11 Module Indices Syntec — `api/indices.py`

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `/familles` | `lister_familles` | Liste les familles disponibles (depuis `revision_service.FAMILLES_CONTRAT`). |
| GET | `` | `lister_indices` | Filtres `famille`, `annee`. |
| GET | `/courant` | `indice_courant` | Indice actif courant. |
| POST | `` | `creer_indice` | Crée une publication d'indice. |
| PUT | `/{indice_id}` | `modifier_indice` | |
| DELETE | `/{indice_id}` | `supprimer_indice` | |
| GET | `/verifier/{famille}/{annee}` | `verifier_indices` | Renvoie OK/KO + message selon que les indices nécessaires pour la révision sont en base. |

### 3.12 Module Formateurs — `api/formateurs.py`

CRUD complet protégé par `Depends(get_current_user)`.

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `` | `list_formateurs` | Liste paginée. |
| POST | `` | `create_formateur` | |
| GET | `/{formateur_id}` | `get_formateur` | |
| PUT | `/{formateur_id}` | `update_formateur` | |
| DELETE | `/{formateur_id}` | `delete_formateur` | Doit délier les FK avant suppression (cf. 2.20). |

### 3.13 Module Prestations — `api/prestations.py`

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `` | `list_prestations` | Filtres : statut, formateur, dates. |
| GET | `/formateur/{formateur_id}` | `list_prestations_formateur` | Vue formateur (pour l'écran "Mes Prestations"). |
| POST | `` | `create_prestation` | Création manuelle. |
| POST | `/from-commande/{commande_id}` | `create_prestations_from_commande` | Génère N prestations à partir des lignes de commande (une par ligne). |
| GET | `/{prestation_id}` | `get_prestation` | |
| PUT | `/{prestation_id}` | `update_prestation` | |
| POST | `/{prestation_id}/planifier` | `planifier_prestation` | Définit `date_planifiee`, `heure_*`, `lieu`, et **synchronise Google Calendar** (effet de bord externe — cf. `google_calendar_service`). |
| POST | `/{prestation_id}/realiser` | `realiser_prestation` | Marque `statut='realisee'`. |
| DELETE | `/{prestation_id}` | `delete_prestation` | |
| POST | `/reattribuer-commande/{commande_id}` | `reattribuer_prestations_commande` | Reassigne toutes les prestations d'une commande à un autre formateur. |

### 3.14 Module Documents — `api/documents.py`

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `/contrat/{contrat_id}` | `liste_documents` | Liste les fichiers générés pour un contrat. |
| POST | `/generer/{contrat_id}` | `generer_contrat` | **Effet de bord** : utilise `document_service` pour produire un `.docx` à partir du modèle actif (selon `famille_contrat`), écrit dans `./storage/documents_generes/`, INSERT dans `documents_generes`. |
| GET | `/telecharger/{doc_id}` | `telecharger_document` | StreamingResponse du fichier. |
| GET | `/modeles` | `liste_modeles` | Liste des modèles uploadés. |
| POST | `/modeles/upload` | `uploader_modele` | Upload `.docx`, écrit dans `./storage/modeles/`, INSERT dans `modeles_documents`. Active automatiquement le modèle (et désactive les autres du même type). |
| PATCH | `/modeles/{modele_id}/activer` | `activer_modele` | Désactive les autres du même `type_document` et active celui-ci. |
| DELETE | `/modeles/{modele_id}` | `supprimer_modele` | Supprime le fichier + la ligne en base. |

### 3.15 Module Audit — `api/audit.py`

3 endpoints d'audit lecture seule. Pas de modification de base.

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `/contrat/{contrat_id}` | `audit_contrat` | Audit d'un contrat : vérifie cohérence des dates, montants, plan, articles. |
| GET | `/facturation/{annee}` | `audit_facturation` | Audit du plan de facturation pour une année (vérifie indices manquants, plans bloqués). |
| GET | `/global` | `audit_global` | Audit global du module (compte de chaque table, anomalies détectées). |

### 3.16 Module Dashboard — `api/dashboard.py`

Un seul endpoint :

| Méthode | Path | Fonction | Description |
| --- | --- | --- | --- |
| GET | `/api/dashboard/stats` | `dashboard_stats` | Agrégats : contrats actifs par famille (mapping `FAMILLES_CONTRAT` du `revision_service`), commandes par statut (`nouvelles`, `a_planifier`, `planifiees`, `terminees=deployee+terminee`, `total`). **Pas de filtrage par rôle** : un FORMATEUR voit les mêmes chiffres qu'un ADMIN. |

### 3.17 Effets de bord critiques (synthèse transverse)

Liste des endpoints qui dépassent la simple persistance locale :

| Endpoint | Effet de bord externe |
| --- | --- |
| `POST /api/synchro/lancer` | Pull complet Karlia (clients + articles) |
| `POST /api/clients` | POST Karlia `/customers` (créer client) |
| `POST /api/clients/synchro` | Pull Karlia `/customers` |
| `POST /api/produits/synchro` | Pull Karlia `/products` |
| `POST /api/commandes/sync` | Pull Karlia `/documents` (devis acceptés) |
| `POST /api/commandes/{id}/facturer` | POST Karlia `/documents` (créer facture) |
| `POST /api/facturation/lancer` | Batch POST Karlia `/documents` (N factures, rate-limité) |
| `POST /api/prestations/{id}/planifier` | Appel Google Calendar API (création/MAJ événement) |
| `POST /api/chorus/auto-config` | POST PISTE `/transverses/v1/recuperer/utilisateurCourant` (KO) |
| `POST /api/chorus/transmettre` | POST PISTE `/cpro/factures/v1/soumettre` (par facture, séquentiel) |
| `POST /api/chorus/test-soumission` | Idem (avec facture fictive `is_test=TRUE`) |
| `POST /api/chorus/synchro-factures` | Pull Karlia `/documents` filtré type=4 |
| `POST /api/documents/generer/{id}` | Lecture modèle Word + génération `.docx` + écriture disque dans `./storage/documents_generes/` |
| `POST /api/documents/modeles/upload` | Écriture disque dans `./storage/modeles/` |

Tous ces appels sont **bloquants** côté HTTP (sauf si rate-limited en interne par `karlia_service` — cf. section 4). Pas de file de tâches ni de queue asynchrone : la réponse HTTP attend la fin du traitement complet.

---

## 4. Services métier backend

Source : `backend/app/services/*.py`. **8 modules**, totalisant ~2100 lignes
de Python.

| Fichier | Lignes | Rôle | Instance globale ? |
| --- | --- | --- | --- |
| `karlia_service.py` | 308 | Client HTTP API Karlia v2 (clients, articles, factures) | Oui — `karlia = KarliaService()` |
| `karlia_devis_service.py` | 395 | Synchronisation devis Karlia → table `commandes`, avec gestion des opportunités "Traité" | Oui — `karlia_devis_service = KarliaDevisService()` |
| `chorus_service.py` | 495 | Client HTTP PISTE/Chorus Pro (OAuth + soumission factures) | Non — instancié à la demande via `get_chorus_service_from_params(params)` |
| `contrat_service.py` | 193 | Calculs métier : prorata, nombre d'années, plan de facturation, numéro client | Module de fonctions pures (pas de classe) |
| `revision_service.py` | 162 | Calculs de révision Syntec, mapping famille → règle, vérification disponibilité indices | Module de fonctions pures |
| `validation_service.py` | 268 | Garde-fous pré/post calcul/émission factures (niveaux ERREUR/WARNING/INFO) | Module de fonctions pures |
| `document_service.py` | 251 | Génération de contrats Word par publipostage (python-docx) | Module de fonctions pures |
| `google_calendar_service.py` | 44 | **Stub non implémenté** — toutes méthodes renvoient `pending_google_integration` | `google_calendar_service = GoogleCalendarService()` |

### 4.1 `karlia_service.py` — Client Karlia v2

**Classe** : `KarliaService`. **Instance globale** : `karlia` (singleton du module).

#### 4.1.1 Authentification et headers

- Clé lue à l'instanciation depuis `settings.KARLIA_API_KEY` (fallback `.env`).
- **Mise à jour dynamique** : `main.py` au startup remplace `karlia.api_key` par la valeur de `parametres.karlia_api_key` ; `api/parametres.py:update_karlia_api_key` fait pareil après PUT. **Subtilité** : `self.headers` est calculé dans `__init__` et n'est jamais relu — donc `_client()` reconstruit les headers à chaque appel à partir de `self.api_key`, ce qui rend la mise à jour effective.
- Pas de retry, pas de circuit-breaker. Timeout 30s.

#### 4.1.2 Gestion d'erreur

`_handle_response()` distingue :
- `200` → `response.json()`
- `401` → `KarliaError(401, "Clé API Karlia invalide ou expirée")`
- `429` → `KarliaError(429, "Quota API Karlia dépassé (100 req/min)")` (sans backoff automatique)
- autre → `KarliaError(status, "Erreur Karlia sur {endpoint}", detail=response.json() ou response.text)`

#### 4.1.3 Endpoints Karlia consommés

| Méthode service | Endpoint Karlia | Verb | Usage |
| --- | --- | --- | --- |
| `lister_clients(recherche, limit, offset)` | `/customers` | GET | Listing + recherche `quick_search` |
| `obtenir_client(karlia_id)` | `/customers/{id}` | GET | Détail |
| `creer_client(data)` | `/customers` | POST | Création |
| `dernier_numero_client()` | `/customers` | GET (deux fois) | **Inefficient** : fait un GET limit=1 pour ordonner puis un GET limit=500 et calcule MAX en Python. À optimiser. |
| `lister_produits(recherche, limit)` | `/products` | GET | Catalogue |
| `obtenir_produit(karlia_id)` | `/products/{id}` | GET | Détail |
| `obtenir_prix_vente(karlia_id)` | `/products/{id}/sell-price` | GET | |
| `lister_types_documents()` | `/documents?limit=1` | GET | Probe pour identifier types |
| `creer_facture(...)` | `/documents` | POST | **Émet une facture** (id_type=4, id_status=0=Brouillon). Convertit les lignes en `products_list` avec mapping TVA → id_vat. |
| `obtenir_document(doc_id)` | `/documents/{id}` | GET | |
| `lister_templates_documents()` | `/documents/templates` | GET | |
| `marquer_facture_envoyee(doc_id)` | `/documents/{id}` | POST | `{id_status: 2}` = facture envoyée |
| `tester_connexion()` | `/company` | GET | Probe + extraction infos abonnement |

#### 4.1.4 Mapping TVA Karlia (`creer_facture`)

| Taux TVA | `id_vat` |
| --- | --- |
| ≥ 20 % | `"1"` |
| ≥ 10 % | `"2"` |
| ≥ 5 % | `"3"` (5,5 %) |
| < 5 % | `"4"` (0 %) |

Le mapping est dans `karlia_service.py:191-195`. Pas d'autre cas (10,5 %, etc.).

#### 4.1.5 Gestion du quota et batch

`traitement_lot_factures(factures, delai_entre_requetes=0.8)` : boucle sur les factures, `await asyncio.sleep(0.8)` entre chaque appel **sauf le dernier**, capture les `KarliaError` individuellement. Le rythme effectif est ~75 req/min (sous le quota de 100 req/min). **Note** : le `KARLIA_MAX_REQUESTS_PER_MINUTE = 80` de `config.py` n'est jamais utilisé — la valeur 0.8s est en dur dans la signature.

#### 4.1.6 Subtilité `id_product` vs `description`

`creer_facture` (`karlia_service.py:201-207`) : si `id_product` est présent dans la ligne, **on n'envoie pas** `description` (Karlia affiche le nom du produit du catalogue, et envoyer `description` créerait un doublon d'intitulé). Si `id_product` est vide, on envoie `description`.

### 4.2 `karlia_devis_service.py` — Synchronisation devis Karlia

**Classe** : `KarliaDevisService`. **Instance globale** : `karlia_devis_service`.

#### 4.2.1 Constantes Karlia

```python
KARLIA_TYPE_DEVIS = 1
KARLIA_STATUS_DEVIS_ACCEPTE = 2
KARLIA_FIELD_TRAITE_ID = "66505"   # Custom field "Traité" sur les opportunités
```

#### 4.2.2 Récupération de la clé API

`_get_api_key_from_db()` ouvre une nouvelle `SessionLocal()` à l'instanciation du service. **Conséquence** : si la clé Karlia change après le démarrage, ce service ne le sait pas (contrairement à l'instance `karlia` qui est rechargée par `parametres.py:update_karlia_api_key`). À corriger dans la refonte.

#### 4.2.3 Workflow `sync_devis_acceptes(db, force_full=False)`

1. Détermine `depuis_date` = `parametres.derniere_synchro_devis` (ou None si `force_full`).
2. Récupère tous les devis acceptés Karlia via `GET /documents?id_type=1&id_status=2&update_date_min={depuis_date}`, paginés (limit=100, pause 0.8s entre pages).
3. Pour chaque devis :
   - Si `id_opportunity` présent et l'opportunité a déjà le champ custom "Traité" = 1 → **skip** (sauf si déjà en base, alors update).
   - Si déjà en base → `_update_commande()` (met à jour montants + pdf_url).
   - Sinon → `_create_commande()` qui appelle `GET /documents/{id}` pour le détail + `GET /customers/{customer_id}` pour les infos client, puis INSERT `Commande` + `CommandeLigne[]`.
   - Après création d'un nouveau, **marque l'opportunité comme traitée** côté Karlia via `POST /opportunities/{id}/custom-fields/66505 {field_value: 1}`.
4. Met à jour `parametres.derniere_synchro_devis` = `datetime.utcnow()`.

#### 4.2.4 Endpoints Karlia consommés (en plus de ceux de `karlia_service`)

| Endpoint Karlia | Verb | Usage |
| --- | --- | --- |
| `/documents?id_type=1&id_status=2&...` | GET | Listing devis acceptés |
| `/documents/{id}` | GET | Détail d'un devis |
| `/customers/{id}` | GET | Détail client |
| `/opportunities/{id}` | GET | Vérifier si "Traité" |
| `/opportunities/{id}/custom-fields/66505` | POST | Marquer "Traité" |

#### 4.2.5 Parsing dates et TVA

- `_parse_karlia_date()` accepte `dd/mm/YYYY` ou `YYYY-mm-dd`.
- `_parse_tva()` : mapping inverse `id_vat → taux` (1→20, 2→10, 3→5.5, 4→0). Si l'API renvoie déjà un float, le passe tel quel.

#### 4.2.6 Anti-pattern relevé

`_create_commande` (`karlia_devis_service.py:259-266`) utilise `db.execute(text("UPDATE commandes SET karlia_opportunity_id..."))` au lieu de simplement passer `karlia_opportunity_id=` au constructeur. Vestige d'un état où la colonne n'existait pas dans `models.py`. La colonne existe désormais (cf. § 2.13) — à nettoyer.

### 4.3 `chorus_service.py` — Client PISTE / Chorus Pro

Documenté en détail dans `docs/CHORUS_PRO_RACCORDEMENT.md` (audit Chorus
2026-05-18). Résumé :

#### 4.3.1 Caractéristiques

- **Pas d'instance globale** — instancié par `chorus.py:_get_chorus_service(db)` qui lit les paramètres `chorus_*` de la table `parametres` à chaque requête.
- Deux URLs distinctes (factures + transverses), selon `mode_qualification` (sandbox vs prod).
- OAuth2 client credentials (token cached 1h moins 5 min de marge).
- `cpro-account` = base64 de `username:password` du compte technique.

#### 4.3.2 Méthodes publiques

| Méthode | Endpoint PISTE | Note |
| --- | --- | --- |
| `tester_connexion()` | OAuth seul | Ne touche pas Chorus, valide juste les credentials. |
| `rechercher_structure_destinataire(siret)` | `POST /cpro/factures/v1/rechercher/structures` | |
| `consulter_structure(id_structure)` | `POST /cpro/factures/v1/consulter/structure` | |
| `rechercher_services_structure(id_structure)` | `POST /cpro/factures/v1/rechercher/services` | |
| `soumettre_facture(...)` | `POST /cpro/factures/v1/soumettre` | Payload V5.01 conforme (cf. doc Chorus). Supporte `dry_run`. |
| `recuperer_utilisateur_courant()` | `POST /cpro/transverses/v1/recuperer/utilisateurCourant` | **URL fantôme** — 403 systématique. À remplacer par `recupererStructuresActivesPourFournisseur`. |
| `consulter_statut_facture(id_facture)` | `POST /cpro/factures/v1/consulter/facture` | |
| `rechercher_factures_emises(date_debut, date_fin, statut)` | `POST /cpro/factures/v1/rechercher/factures/fournisseur` | |

#### 4.3.3 Traçage des échanges

`_record_exchange(method, url, headers, body, response)` est appelé dans tous les `_post()` (et dans `recuperer_utilisateur_courant()`). Capture :
- `last_request` : `{method, url, headers (secrets masqués), body}`
- `last_response` : `{status_code, reason, headers (complets), body_text, body_json, x_correlation_id}`

Ces deux dicts sont stockés dans `transmissions_chorus.payload_json` et `transmissions_chorus.reponse_json` par l'endpoint `/transmettre`. **Critique pour le diagnostic.**

### 4.4 `contrat_service.py` — Logique métier contrats

Module de **fonctions pures**, pas de classe ni d'instance.

| Fonction | Signature | Rôle |
| --- | --- | --- |
| `calculer_prorata(date_debut, montant_annuel_ht, demi_mois=False)` | → dict `{prorate, nb_mois, montant_ht, detail}` | Règle métier : si jour ≤ 15 → facturer dès ce mois, sinon dès le mois suivant. Option `demi_mois` ajoute 1/24ème du montant annuel. Si 1er janvier sans option → pas de prorata. |
| `calculer_nombre_annees(date_debut, date_fin)` | → int | `date_fin.year - date_debut.year + 1` (compte des années civiles, pas calendaires). |
| `generer_plan_facturation(contrat_id, date_debut, date_fin, montant_annuel_ht, prorata)` | → list of dicts | Une ligne par année civile. Année 1 prorata→`type_facture=PRORATE`, date_echeance = `date_debut` (si pas 1er janvier) ou `01/01/annee`. Suivantes : `type_facture=ANNUELLE`, date_echeance = `01/01/annee`. Statut initial : `PLANIFIEE`. |
| `calculer_montant_revise(montant_an1, indice_recent, indice_ancien)` | → Decimal | Formule Syntec : `montant × indice_recent / indice_ancien`, arrondi 2 décimales `ROUND_HALF_UP`. Lève `ValueError` si `indice_ancien == 0`. **Note** : non utilisée par `revision_service` qui fait le calcul lui-même. Probablement legacy. |
| `generer_numero_client(nom, dernier_numero)` | → str | Génère un numéro client style `DUM048` : 3 premiers chars alphanumériques (sans accents, sans articles/formes juridiques) + incrément 3 chiffres. Padding `X` si moins de 3 chars. |
| `calculer_statut_renouvellement(contrats_actifs, mois_alerte=1)` | → list | Ajoute `jours_avant_echeance` et `a_renouveler` (True si fin entre 0 et `mois_alerte` mois). |

**Dépendances** : aucune (pas d'I/O, pas de DB, pur Python avec `decimal` et `datetime`).

### 4.5 `revision_service.py` — Calculs Syntec et règles de famille

Module de **fonctions pures**.

#### 4.5.1 Référentiel `FAMILLES_CONTRAT`

Source : `revision_service.py:26-34`. **7 familles définies** :

| Code | Label | Règle de révision | Description |
| --- | --- | --- | --- |
| `COSOLUCE` | Cosoluce | `SYNTEC_AOUT` | Indice Syntec d'août |
| `CANTINE` | Cantine de France | `SYNTEC_OCTOBRE` | Indice Syntec d'octobre |
| `DIGITECH` | Digitech | `MANUELLE` | Saisie utilisateur |
| `MAINTENANCE` | Maintenance matériel | `SYNTEC_AOUT` | |
| `ASSISTANCE_TEL` | Assistance Téléphonique | `SYNTEC_AOUT` | |
| `KIWI_BACKUP` | Kiwi Backup | `AUCUNE` | Prix fixe |
| `AUTRE` | Autre | `AUCUNE` | |

#### 4.5.2 Formule Syntec

Pour facturer l'**année N** :
- `indice_ref` = indice mois M de l'année **N-2**
- `indice_new` = indice mois M de l'année **N-1**
- `taux = indice_new / indice_ref` (arrondi 6 décimales)
- `montant_revise = montant_precedent × taux` (arrondi 2 décimales, ROUND_HALF_UP)

(Le décalage N-2/N-1 est documenté dans le code lignes 73-94 comme une correction explicite — auparavant le code utilisait N-1/N.)

#### 4.5.3 Fonctions

| Fonction | Rôle |
| --- | --- |
| `get_regle_revision(famille_contrat)` | Retourne `"SYNTEC_AOUT"` (défaut), `"SYNTEC_OCTOBRE"`, `"MANUELLE"`, ou `"AUCUNE"`. |
| `get_indice(db, annee, mois)` | Requête `IndiceRevision` filtrée annee+mois. |
| `verifier_indices_disponibles(db, famille, annee_facturation)` | Vérifie que `indice_ref` et `indice_new` existent. Retourne `{ok, indice_ref, indice_new}` ou `{ok=False, message}`. |
| `calculer_revision(db, famille, annee_facturation, montant_precedent, nouveau_montant_manuel=None)` | Calcule selon la règle. Pour DIGITECH (MANUELLE), exige `nouveau_montant_manuel`. Retourne `{ok, montant_revise, taux_revision, message, indice_ref, indice_new}`. |

### 4.6 `validation_service.py` — Garde-fous métier

Module de **fonctions pures**. Quatre niveaux de garde sur le cycle de facturation.

#### 4.6.1 Modèle d'alerte

Chaque garde retourne une liste de dicts `{niveau, code, message, detail}`. Niveaux :
- `ERREUR` — bloque l'opération
- `WARNING` — alerte mais autorise
- `INFO` — informatif (succès)

#### 4.6.2 Fonctions

| Fonction | Quand l'appeler | Codes d'erreur principaux |
| --- | --- | --- |
| `valider_contrat(db, contrat)` | À la validation manuelle d'un contrat | `ARTICLE_PRINCIPAL_MANQUANT`, `ID_PRODUCT_MANQUANT`, `PLAN_VIDE`, `PLAN_INCOMPLET`, `DOUBLON_ANNEE_PLAN`, `EMISE_SANS_KARLIA_ID`, `TAUX_REVISION_INCOHERENT`, `MONTANT_PRECEDENT_INCOHERENT` |
| `valider_pre_calcul(db, plan, nouveau_montant_manuel)` | **Appelée par `POST /api/facturation/calculer`** | `DEJA_EMISE`, `INDICES_MANQUANTS`, `MONTANT_MANUEL_REQUIS`, `MONTANT_REFERENCE_NUL` |
| `valider_pre_emission(db, plan)` | Avant l'envoi Karlia (**non câblée** dans `facturation.py:lancer_facturation` actuellement !) | `DEJA_EMISE`, `NON_CALCULEE`, `MONTANT_NUL`, `ARTICLE_PRINCIPAL_MANQUANT`, `ID_PRODUCT_MANQUANT`, `CLIENT_KARLIA_MANQUANT`, `TAUX_REVISION_ANORMAL` (taux <0.5 ou >2.0) |
| `valider_post_emission(plan, resultat_karlia)` | **Appelée par `POST /api/facturation/lancer`** | `KARLIA_ECHEC`, `KARLIA_ID_ABSENT`, `STATUT_NON_MIS_A_JOUR`, `KARLIA_ID_NON_PERSISTE` |
| `auditer_annee_facturation(db, annee)` | Endpoint `/api/audit/facturation/{annee}` | Compose `valider_pre_emission` pour les plans non émis + checks supplémentaires sur les plans émis |

**Trou identifié** : `valider_pre_emission` n'est jamais appelé par le code de production. C'est une dead branch utilisée uniquement par l'audit. L'émission réelle (`facturation.py:lancer_facturation`) n'a donc PAS de garde "client_karlia_id manquant" ou "article principal sans id_product" — ces vérifications ne tournent qu'en `valider_pre_calcul`. Or l'utilisateur peut sauter le calcul (statut `PLANIFIEE` → `EMISE`) si le plan a déjà un `montant_ht_prevu`.

### 4.7 `document_service.py` — Génération de contrats Word

Module de fonctions, génération par publipostage `python-docx`.

#### 4.7.1 Constantes

```python
STORAGE_DIR   = Path("/app/storage")          # Volume monté
MODELES_DIR   = STORAGE_DIR / "modeles"        # Modèles uploadés
DOCUMENTS_DIR = STORAGE_DIR / "documents_generes"  # Sortie
```

#### 4.7.2 Mapping famille → modèle

| Famille | Fichier modèle attendu |
| --- | --- |
| `COSOLUCE` | `Modele_Contrat_Cosoluce_et_Annexes.docx` |
| `CANTINE` | `Modele_Contrat_Cantine_de_France.docx` |
| `MAINTENANCE` | `Modele_Contrat_Maintenance_Systeme.docx` |
| `ASSISTANCE_TEL` | `Modele_Contrat_Assistance_Cityweb.docx` |

**Note** : `DIGITECH` et `KIWI_BACKUP` apparaissent dans `FAMILLE_LABEL` mais pas dans `FAMILLE_MODELE`. Ces familles ne génèrent pas de contrat Word.

#### 4.7.3 Algorithme de publipostage

Les modèles Word utilisent les **guillemets français doubles** `«ChampNom»` comme placeholders (caractères Unicode `\xab` et `\xbb`).

`_remplacer_texte()` :
1. Pour chaque champ canon dans `CHAMPS` (28 champs définis), essaie tous les alias possibles (ex. `NomClient` ou `NomSite`).
2. Supprime les placeholders `«COL1IdSite»`, `«COL2NomSite»` (regex `_RE_COL`).
3. Supprime tout autre placeholder restant (regex `_RE_REST`).

`_traiter_paragraphe()` gère la subtilité Word qui découpe un texte en plusieurs "runs" avec mise en forme différente : il essaie d'abord le remplacement run-par-run, et si le placeholder traverse plusieurs runs (texte recomposé), il remplace tout dans le premier run et vide les autres.

`_traiter_document()` parcourt paragraphes, tableaux (récursivement pour sous-tableaux), et headers de section.

#### 4.7.4 Variables substituées

28 champs canoniques (cf. `CHAMPS` dict, `document_service.py:38-67`). Calculés par `_construire_variables(contrat, client)` à partir de l'objet `Contrat`, du `ClientCache` lié, et de l'article rang 0 (article principal) et rang 1 (annexe).

#### 4.7.5 Résolution du modèle

`_trouver_modele(famille, db)` :
1. Cherche un `ModeleDocument` actif (`type_document = CONTRAT_{famille}`, `actif=True`, le plus récent). Si son `chemin_fichier` existe sur disque → retourne.
2. Sinon fallback : cherche le fichier par nom dans `MODELES_DIR` (`/app/storage/modeles/`).
3. Sinon retourne `None` → erreur.

#### 4.7.6 Effets de bord

- Lit le `.docx` modèle.
- Écrit un nouveau `.docx` dans `/app/storage/documents_generes/Contrat_{numero}_{nom_client_safe}_{YYYYMMDD}.docx`.
- INSERT dans `documents_generes` avec `variables_json` = snapshot des valeurs utilisées.

#### 4.7.7 Limites identifiées

- **Pas de conversion PDF** : le service ne génère QUE du `.docx`. La colonne `documents_generes.chemin_pdf` existe mais n'est jamais alimentée.
- **Pas de regénération** : si le modèle change, les documents déjà générés ne sont pas re-produits.

### 4.8 `google_calendar_service.py` — Stub Google Calendar

**Statut : non implémenté.** Le fichier fait 44 lignes et toutes les méthodes
renvoient `{success: False, status: "pending_google_integration", error:
"Google Calendar non encore branché"}`.

```python
class GoogleCalendarService:
    def create_or_update_event(self, *, prestation_id, title, agenda_email, ...): ...
    def delete_event(self, *, agenda_email, event_id): ...

google_calendar_service = GoogleCalendarService()
```

**Conséquences** :
- `api/prestations.py:planifier_prestation()` (cf. § 3.13) appelle ce stub et met `prestations.google_sync_status` à `pending`/`error` selon le retour.
- Les colonnes `prestations.google_calendar_id`, `google_event_id`, `google_synced_at` ne sont **jamais** alimentées en production.
- Le tag git `cfe6a13` (`Prepare Google Calendar sync status for prestation planning`) confirme que c'est une préparation d'infrastructure, l'intégration réelle est encore à faire (probable chantier `feature/google-agenda-planning` en cours).

### 4.9 Synthèse — Dépendances externes par service

| Service | API tierces appelées | Fichiers locaux | Tables DB lues / écrites |
| --- | --- | --- | --- |
| `karlia_service` | Karlia v2 (`/customers`, `/products`, `/documents`, `/company`) | aucun | aucun direct (consommé par les routers) |
| `karlia_devis_service` | Karlia v2 (`/documents`, `/customers`, `/opportunities`) | aucun | lit/écrit `parametres` (clé API + derniere_synchro_devis), écrit `commandes` et `commande_lignes` |
| `chorus_service` | PISTE OAuth + Chorus Pro factures + transverses | aucun | aucun direct (consommé par `api/chorus.py`) |
| `contrat_service` | aucune | aucun | aucun (fonctions pures) |
| `revision_service` | aucune | aucun | lit `indices_revision` |
| `validation_service` | aucune | aucun | lit `IndiceRevision`, `Contrat`, `PlanFacturation` |
| `document_service` | aucune | lit `/app/storage/modeles/*.docx`, écrit `/app/storage/documents_generes/*.docx` | lit `ModeleDocument`, `Contrat`, `ClientCache` ; écrit `DocumentGenere` |
| `google_calendar_service` | (stub — devrait appeler Google Calendar API) | aucun | aucun |

### 4.10 Anti-patterns et redondances entre services

1. **Deux services Karlia** (`karlia_service` + `karlia_devis_service`) qui font tous les deux des requêtes HTTP vers la même API avec des conventions différentes (`_get`/`_post` génériques d'un côté, `httpx.AsyncClient` ad-hoc de l'autre). Devrait être consolidé.
2. **Récupération de la clé API divergente** : `karlia_service.karlia` est rechargé dynamiquement, `karlia_devis_service.karlia_devis_service` capture la clé une seule fois à l'instanciation (cf. § 4.2.2).
3. **`calculer_montant_revise` (`contrat_service`) duplique la logique de `calculer_revision` (`revision_service`)** sans l'utiliser. Probablement legacy.
4. **`google_calendar_service` est un stub** alors que des colonnes DB existent déjà pour persister son résultat (cf. § 4.8).
5. **`validation_service.valider_pre_emission`** n'est pas câblé dans le flux d'émission réel (cf. § 4.6 trou identifié).

---

## 5. Frontend React

Source de vérité versionnée : `~/contrats/contrats-ui-src/src/`. Source de
build (hors-repo, copiée à la main avant `docker compose build`) :
`~/contrats-ui/src/`. Voir § 1.2 pour le mécanisme de double localisation.

### 5.1 Structure du dossier `src/`

```
contrats-ui-src/src/
├── App.js                        # 92 lignes — BrowserRouter + AuthProvider + Toaster + Routes
├── components/
│   └── Layout.js                 # 128 lignes — Sidebar + zone main, gestion menu par rôle
├── context/
│   └── AuthContext.js            # 88 lignes — Provider + getDroitsByRole + login/logout
├── services/
│   └── api.js                    # 44 lignes — Axios + helpers groupés (auth, clients, contrats, ...)
├── pages/
│   └── (21 fichiers)             # Pages route-targetées
├── index.js / index.css          # Entrée CRA standard
└── (config Tailwind + setupTests à la racine du projet, hors src/)
```

Aucun `components/` partagé au-delà de `Layout.js` — chaque page contient son
propre code, ses propres modales (`Dialog` MUI), ses propres tableaux. Pas de
factorisation `DataTable`, `Modal`, ou `FormField`.

### 5.2 Routes — `App.js`

15 routes principales (hors `*` catch-all), toutes encapsulées dans `PrivateRoute` sauf `/login`. Le rôle `FORMATEUR` est restreint via le helper `isNotFormateur` qui rejette l'accès aux 19 routes administratives ; il a accès à `/` (Dashboard) et `/mes-prestations` uniquement.

| Path | Composant | Garde `allow` | Accessible aux rôles |
| --- | --- | --- | --- |
| `/login` | `Login` | (publique) | tous (redirige `/` si déjà connecté) |
| `/` | `Dashboard` | (aucune) | ADMIN, GESTIONNAIRE, TECHNICIEN, FORMATEUR |
| `/contrats` | `Contrats` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/contrats/nouveau` | `NouveauContrat` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/contrats/tunnel` | `TunnelContrat` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/contrats/:id` | `DetailContrat` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/contrats/:id/modifier` | `ModifierContrat` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/renouvellements` | `Renouvellements` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/facturation` | `Facturation` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/indices` | `Indices` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/clients` | `Clients` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/parametres` | `Parametres` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN (filtré par `droits.parametres`) |
| `/utilisateurs` | `Utilisateurs` | `isNotFormateur` | ADMIN seul (filtré par `droits.utilisateurs`) |
| `/commandes/nouvelles` | `NouvellesCommandes` | `isNotFormateur` | ADMIN, GESTIONNAIRE, TECHNICIEN |
| `/commandes/a-planifier` | `CommandesAPlanifier` | `isNotFormateur` | idem |
| `/commandes/planifiees` | `CommandesPlanifiees` | `isNotFormateur` | idem |
| `/commandes/terminees` | `CommandesTerminees` | `isNotFormateur` | idem |
| `/contrats-a-creer` | `ContratsACreer` | `isNotFormateur` | idem |
| `/formateurs` | `Formateurs` | `isNotFormateur` | idem |
| `/mes-prestations` | `MesPrestations` | (aucune) | tous |
| `/chorus-pro` | `ChorusProPage` | `isNotFormateur` | idem |
| `*` | (Navigate) | — | redirige vers `/` |

Helper de redirection : `getForbiddenRedirect(user)` renvoie `/mes-prestations` pour `FORMATEUR`, `/` sinon.

### 5.3 Contexte d'authentification — `context/AuthContext.js`

Provider unique exposant via `useAuth()` :

| Variable | Type | Source |
| --- | --- | --- |
| `user` | `{login, nom_complet, role, formateur_id}` ou `null` | Réponse `GET /api/auth/me` au reload, `POST /api/auth/login` au login |
| `droits` | dict booléen (9 clés) | `getDroitsByRole(role)` côté frontend |
| `loading` | bool | `true` pendant la résolution initiale du token |
| `login(username, password)` | fn async | POST `/api/auth/login`, stocke token, set `user` + `droits` |
| `logout()` | fn | Vide `localStorage.token`, redirige `/login` (via `window.location.href`) |

#### 5.3.1 Matrice `getDroitsByRole` côté frontend

**Important** : la matrice est **dupliquée du backend** (`utilisateurs.py:14-21`). Elle est identique aujourd'hui, mais toute évolution doit être faite des deux côtés. Cf. § 8.3 (dette technique).

Les 9 droits exposés : `contrats_lecture`, `contrats_ecriture`, `facturation`, `indices`, `commandes`, `parametres`, `utilisateurs`, `formateurs`, `toutes_prestations`.

#### 5.3.2 Race condition au démarrage

`AuthProvider` initialise `droits` à **tout `true`** (`AuthContext.js:39-42`) avant que `setDroits(getDroitsByRole(...))` ne soit appelé après la résolution de `/api/auth/me`. Pendant cette fenêtre (~quelques centaines de millisecondes), un FORMATEUR aurait théoriquement accès à tout l'UI. C'est masqué par le test `loading` dans `PrivateRoute` qui affiche un splash "Chargement..." — cette protection dépend uniquement du fait que `loading=true` jusqu'à la résolution. Documenté dans `CLAUDE.md:36` (« `droits` initialisé à `true` partout par défaut »).

### 5.4 Couche réseau — `services/api.js`

Instance Axios unique (`baseURL: ''` — chemins absolus `/api/...` qui passent par nginx).

**Intercepteurs** :
- Request : ajoute `Authorization: Bearer <token>` si présent dans `localStorage`.
- Response : sur `401`, vide le token et redirige `/login` via `window.location.href` (sans utiliser React Router — full page reload).

**Helpers groupés exportés** :

| Export | Méthodes | Couvre |
| --- | --- | --- |
| `authAPI` | `login(username, password)`, `me()` | `POST /api/auth/login` (form-urlencoded), `GET /api/auth/me` |
| `clientsAPI` | `liste(params)`, `recherche(q)`, `creer(data)`, `synchro()` | `/api/clients` |
| `contratsAPI` | `liste(params)`, `detail(id)`, `creer(data)`, `valider(id)`, `terminer(id, motif)`, `renouveler(id, data)`, `renouvelerLot(data)`, `renouvellements(params)` | `/api/contrats` |
| `produitsAPI` | `liste(params)` | `/api/produits` |
| `indicesAPI` | `liste()`, `creer(data)`, `courant()`, `supprimer(id)` | `/api/indices` |
| `facturationAPI` | `apercu(annee)`, `lancer(data)`, `lotStatut(id)` | `/api/facturation` |

**Limitation** : ce helper est **incomplet**. La majorité des pages utilisent `api.get('/api/...')` / `api.post(...)` directement en passant l'instance par défaut (cf. § 5.5). Pas de helper pour `/api/commandes/*`, `/api/chorus/*`, `/api/dashboard/*`, `/api/formateurs/*`, `/api/prestations/*`, `/api/utilisateurs/*`, `/api/parametres/*`, `/api/documents/*`. Dette de modularisation.

### 5.5 Pages — inventaire (21 fichiers)

Légende de la colonne "UI" : **T** = Tailwind, **M** = Material-UI (`@mui/material`).

| Page | Path | UI | Endpoints appelés | Rôle métier |
| --- | --- | --- | --- | --- |
| `Login.js` | `/login` | T | `POST /api/auth/login` (via `useAuth().login`) | Formulaire login + redirection vers `/` |
| `Dashboard.js` | `/` | T | `/api/dashboard/stats`, `/api/synchro/lancer`, `/api/synchro/statut` | KPI contrats par famille, commandes par statut, bouton synchro manuelle Karlia |
| `Contrats.js` | `/contrats` | T | `contratsAPI.liste` (`/api/contrats`) | Liste paginée des contrats avec onglets par statut, filtres `recherche`/`famille`, recherche par numéro/client |
| `NouveauContrat.js` | `/contrats/nouveau` | T | `/api/indices/familles`, `contratsAPI.creer`, `clientsAPI`, `produitsAPI`, `indicesAPI` | Formulaire long (probablement supplanté par TunnelContrat) |
| `TunnelContrat.js` | `/contrats/tunnel` | T | `/api/contrats/${id}`, `/api/facturation/calculer`, `/api/facturation/lancer`, `contratsAPI`, `clientsAPI`, `produitsAPI` | **Tunnel de saisie en 4 étapes** (client → articles → planning/prorata → validation). Mode `nouveau`/`renouvellement` via querystring. |
| `DetailContrat.js` | `/contrats/:id` | T | `/api/contrats/${id}`, `/api/documents/contrat/${id}`, `/api/documents/generer/${id}`, `/api/documents/telecharger/${docId}` | Vue détail + génération Word + téléchargement fichiers |
| `ModifierContrat.js` | `/contrats/:id/modifier` | T | `/api/contrats/${id}` (PUT), `/api/indices/familles`, `contratsAPI`, `clientsAPI`, `produitsAPI`, `indicesAPI` | Édition d'un BROUILLON (réutilise une grande partie de TunnelContrat) |
| `Renouvellements.js` | `/renouvellements` | T | `contratsAPI.renouvellements`, `contratsAPI.renouveler`, `contratsAPI.renouvelerLot`, `/api/indices/familles` | Liste des contrats à renouveler dans le mois + actions SPONTANE/FIN en multi-sélection ou NOUVEAU_CONTRAT individuel |
| `Facturation.js` | `/facturation` | T | `/api/facturation/apercu/${annee}`, `/api/facturation/calculer`, `/api/facturation/lancer`, `/api/indices/familles` | Tableau des plans année par année, déclenchement calcul puis émission |
| `Indices.js` | `/indices` | T | `/api/indices`, `/api/indices?${params}`, `/api/indices/${id}` (DELETE) | CRUD indices Syntec (filtrable par famille/année) |
| `Clients.js` | `/clients` | T | `/api/clients/search`, `/api/clients/${karlia_id}/fiche` | Recherche client + fiche détail (contrats actifs + historique + factures) |
| `Parametres.js` | `/parametres` | T | `/api/parametres/`, `/api/parametres/karlia-api-key`, `/api/parametres/tester-connexion`, `/api/parametres/vider-cache`, `/api/parametres/chorus`, `/api/chorus/test-connexion`, `/api/chorus/auto-config`, `/api/documents/modeles`, `/api/documents/modeles/upload`, `/api/documents/modeles/...`, `/api/synchro/lancer` | Page admin : Karlia, Chorus Pro, modèles Word, cache/synchro |
| `Utilisateurs.js` | `/utilisateurs` | T | `/api/utilisateurs`, `/api/utilisateurs/${user}` (PUT/DELETE), `/api/formateurs?actif_only` | CRUD utilisateurs (ADMIN seul) |
| `NouvellesCommandes.js` | `/commandes/nouvelles` | M | `/api/commandes/nouvelles`, `/api/commandes/stats`, `/api/commandes/sync?force_full`, `/api/commandes/${id}` (valider) | Liste des devis Karlia importés en attente de validation. Bouton "Synchroniser" → `sync_devis_karlia`. Action : valider avec choix `a_planifier` vs `sans_planification`. |
| `CommandesAPlanifier.js` | `/commandes/a-planifier` | M | `/api/commandes/a-planifier`, `/api/formateurs?actif_only`, `/api/prestations?commande_id`, `/api/prestations/from-commande/${id}`, `/api/prestations/reattribuer-commande/${id}` | Commandes à planifier : génère les prestations, attribue les formateurs, planifie ou réattribue |
| `CommandesPlanifiees.js` | `/commandes/planifiees` | M | `/api/commandes/planifiees`, `/api/commandes/${id}` | Suivi commandes planifiées (lecture seule essentiellement) |
| `CommandesTerminees.js` | `/commandes/terminees` | M | `/api/commandes/terminees`, `/api/commandes/${id}` | Commandes "deployees" (prestations finies) à facturer. Action : `POST /api/commandes/${id}/facturer` |
| `ContratsACreer.js` | `/contrats-a-creer` | M | `/api/commandes/contrats-a-creer`, `/api/commandes/${id}` | Commandes flaggées `necessite_contrat` sans contrat — porte d'entrée vers la création de contrat |
| `Formateurs.js` | `/formateurs` | M | `/api/formateurs`, `/api/formateurs/${id}` (PUT/DELETE), `/api/formateurs?actif_only` | CRUD formateurs |
| `MesPrestations.js` | `/mes-prestations` | M+`@mui/x-date-pickers` | `/api/formateurs/${user_formateur_id}`, `/api/formateurs?actif_only`, `/api/prestations/formateur/${id}`, `/api/prestations/${id}/realiser`, `/api/prestations/${id}` (PUT) | Page formateur : ses prestations à planifier/réaliser. Pour ADMIN/GESTIONNAIRE, peut afficher les prestations d'un autre formateur (toggle). |
| `ChorusProPage.js` | `/chorus-pro` | M | `/api/chorus/factures`, `/api/chorus/factures/${id}` (PUT siret), `/api/chorus/statistiques`, `/api/chorus/synchro-factures`, `/api/chorus/test-connexion`, `/api/chorus/test-soumission`, `/api/chorus/transmettre` | Liste des factures à transmettre Chorus Pro, statuts, transmission, bouton "Test soumission" (`fix/chorus-payload-v5-01`) |

### 5.6 Menus latéraux — `components/Layout.js`

Trois menus codés en dur, sélectionnés selon `user.role` :

| Rôle | Source | Items |
| --- | --- | --- |
| `ADMIN`, `GESTIONNAIRE`, `TECHNICIEN` (sauf TECHNICIEN qui a son menu propre) | `MENU_COMPLET` | 17 items + 4 séparateurs (Commandes, Contrats, Gestion, Administration) |
| `FORMATEUR` | `MENU_FORMATEUR` | Tableau de bord + "Mes prestations" |
| `TECHNICIEN` | `MENU_TECHNICIEN` | Tableau de bord + "Mes prestations" + "Contrats techniques" |

#### 5.6.1 `MENU_COMPLET` — items et droits requis

| Item | Path | Droit requis |
| --- | --- | --- |
| Tableau de bord | `/` | (aucun) |
| *(separator)* Commandes | | |
| Nouvelles commandes | `/commandes/nouvelles` | `commandes` |
| À planifier | `/commandes/a-planifier` | `formateurs` |
| Planifiées | `/commandes/planifiees` | `commandes` |
| Terminées | `/commandes/terminees` | `commandes` |
| Mes prestations | `/mes-prestations` | (aucun) + flag `forFormateur` |
| *(separator)* Contrats | | |
| Liste des contrats | `/contrats` | `contrats_lecture` |
| Nouveau contrat | `/contrats/tunnel?mode=nouveau` | `contrats_ecriture` |
| Contrats à créer | `/contrats-a-creer` | `commandes` |
| Renouvellements | `/renouvellements` | `contrats_ecriture` |
| *(separator)* Gestion | | |
| Clients | `/clients` | `contrats_ecriture` |
| Facturation | `/facturation` | `facturation` |
| Indices Syntec | `/indices` | `indices` |
| Chorus Pro | `/chorus-pro` | `facturation` |
| *(separator)* Administration | | |
| Paramètres | `/parametres` | `parametres` |
| Formateurs | `/formateurs` | `utilisateurs` |
| Utilisateurs | `/utilisateurs` | `utilisateurs` |

Le filtre `cleanMenu` (lignes 67-73) supprime les séparateurs consécutifs ou orphelins après l'application des droits.

#### 5.6.2 Particularité "Mes prestations" dans `MENU_COMPLET`

L'item `forFormateur: true` (ligne 12) est masqué pour les utilisateurs `ADMIN`/`GESTIONNAIRE` qui n'ont pas de `formateur_id` rattaché — pratique pour ne pas polluer le menu d'un admin pur. Mais s'il a un `formateur_id`, l'item apparaît : un ADMIN peut donc se voir comme formateur dans la même UI.

### 5.7 Bibliothèques UI mélangées

Trois familles cohabitent :

| Famille | Pages | Effet |
| --- | --- | --- |
| **Tailwind seul** | Login, Dashboard, Contrats, NouveauContrat, TunnelContrat, DetailContrat, ModifierContrat, Renouvellements, Facturation, Indices, Clients, Parametres, Utilisateurs | Style "carte + bouton" custom, classes Tailwind appliquées |
| **Material-UI** | ChorusProPage, NouvellesCommandes, CommandesAPlanifier, CommandesPlanifiees, CommandesTerminees, ContratsACreer, Formateurs, MesPrestations | `Box`, `Paper`, `Table*`, `Dialog`, `Button`, `Chip`, `Snackbar` — composants MUI v5/v6 |
| **MUI X Date Pickers** | MesPrestations seul | `@mui/x-date-pickers/AdapterDateFns` + `DatePicker`/`TimePicker` |

`react-datepicker` est aussi listé dans `package.json` (cf. § 1.7) mais aucune page versionnée ne l'importe — probablement legacy de NouveauContrat ou Renouvellements pré-MUI.

`react-select` est listé mais pareillement non importé. À nettoyer.

`lucide-react` est listé mais aucune page versionnée ne l'importe non plus.

#### 5.7.1 MUI absent du `package.json`

Comme évoqué en § 1.7, ni `@mui/material`, ni `@mui/icons-material`, ni `@mui/x-date-pickers`, ni `@emotion/*` (dépendances peer de MUI) ne sont déclarés dans `contrats-ui-src/package.json`. Le build fonctionne uniquement parce que `~/contrats-ui/node_modules/` les contient (probablement installés à la main). C'est une **fragilité** : un `npm ci` propre échouerait.

### 5.8 Conventions et helpers récurrents

- **Dates côté JS** : `new Date(date + 'T12:00:00')` systématiquement (cf. `CLAUDE.md:33`) pour éviter le décalage TZ Paris (UTC midi → midi local). Vu dans `formatDate` de `ChorusProPage.js:38-45` et d'autres.
- **Notifications** : `react-hot-toast` côté Tailwind, `Snackbar` MUI côté MUI. Deux mécanismes parallèles.
- **Auth header** : géré centralement par l'intercepteur Axios (cf. § 5.4). Aucune page ne pose explicitement `Authorization`.
- **Pas de state management global** au-delà d'`AuthContext`. Chaque page gère son propre fetching avec `useEffect` + `useState`.
- **Pas de cache HTTP côté client** (ni `react-query`, ni `swr`). Chaque navigation refait les appels.

### 5.9 Points d'observation pour la refonte

| Point | Observation |
| --- | --- |
| Helpers `api.js` incomplets | 6 helpers exportés couvrent ~30 % des routes ; le reste est en `api.get('...')` direct |
| Matrice de droits dupliquée | `AuthContext.getDroitsByRole` = `utilisateurs.py:DROITS` — divergence possible |
| Mélange Tailwind / MUI | Coût de maintenance des deux design systems en parallèle |
| Dépendances non déclarées | MUI, @emotion installés mais absents du `package.json` |
| Race au boot | `droits` initialisé à `true` (cf. § 5.3.2), protégé seulement par le splash `loading` |
| Pas de cache HTTP | `react-query`/`swr` absents — tout fetch est refait à chaque navigation |
| Pas de composants partagés | Pas de `DataTable`/`Modal`/`Form*` factorisés ; les Dialog MUI sont recopiés dans chaque page commandes/Chorus |
| Stub Google Calendar | Affiche `google_sync_status` mais l'intégration backend est un no-op (cf. § 4.8) |

---

## 6. Workflows métier de bout en bout

Section orientée parcours utilisateur. Chaque workflow décrit le
déclencheur, le chemin frontend → backend → base, les effets de bord
externes, et les frictions identifiées (à transformer en lots de refonte).

### Workflow 1 — Création d'un contrat (tunnel 4 étapes)

**Déclencheur** : utilisateur (ADMIN ou GESTIONNAIRE) clique « Nouveau contrat » dans le menu, atterrit sur `/contrats/tunnel?mode=nouveau`. Peut aussi être déclenché depuis « Contrats à créer » (liens depuis `ContratsACreer.js`) ou depuis le workflow Renouvellement (mode `renouvellement`).

**Pages frontend impliquées** : `TunnelContrat.js` exclusivement.

**Les 4 étapes du tunnel** (`ETAPES = ['Informations', 'Articles', 'Récapitulatif', 'Première facture']`) :

| Étape | Contenu | Endpoints appelés (lecture) |
| --- | --- | --- |
| 0 — Informations | Sélection du client (recherche `clientsAPI.liste(recherche=...)` avec debounce 300 ms), saisie du numéro de contrat, de la famille (`COSOLUCE`/`CANTINE`/`DIGITECH`/`MAINTENANCE`/`ASSISTANCE_TEL`/`KIWI_BACKUP`), dates début/fin, montant annuel HT, option `prorate_demi_mois`, choix de l'indice de référence | `/api/clients?recherche=...` |
| 1 — Articles | Saisie de l'article principal (rang 0, **id_product Karlia obligatoire** pour facturation) + jusqu'à 7 annexes (rang 1-7). Recherche d'article via `produitsAPI.liste` | `/api/produits?recherche=...` |
| 2 — Récapitulatif | Visualisation du prorata calculé côté frontend (fonction `calculerProrata` qui réplique la logique de `contrat_service.calculer_prorata`), du plan prévisionnel, des montants. Validation du prorata (`prorate_validated`). | aucun |
| 3 — Première facture | Affichage de la première facture (ou prorata) avec possibilité de la pousser immédiatement vers Karlia | `/api/facturation/calculer`, `/api/facturation/lancer` |

**Endpoints backend appelés (à la création)** :
1. `POST /api/contrats` — crée Contrat (BROUILLON) + N `ContratArticle` (rang 0-7) + N `PlanFacturation` (une par année civile, statut `PLANIFIEE`) en **un seul commit**.
2. Optionnel à l'étape 3 : `POST /api/facturation/calculer` puis `POST /api/facturation/lancer` pour émettre la première facture.

Après la création, l'utilisateur est généralement redirigé vers `DetailContrat.js` pour valider le contrat (passage en EN_COURS) :

3. `POST /api/contrats/{id}/valider` — checks (article rang 0 présent, prorata validé) puis `statut = EN_COURS`.

**Tables modifiées** :
- `contrats` (INSERT, statut BROUILLON puis EN_COURS)
- `contrat_articles` (INSERT × N)
- `plan_facturation` (INSERT × nombre_annees, statut PLANIFIEE)

**Appels externes** : aucun à la création. Karlia/PISTE intervient seulement si l'utilisateur déclenche la facturation à l'étape 3.

**Effets de bord** :
- Pas de fichier généré (la génération Word se fait séparément depuis `DetailContrat.js`).
- Pas de mail.

**Points de friction identifiés** :
- **Duplication de logique prorata** : `calculerProrata()` (JS, `TunnelContrat.js:8-22`) et `calculer_prorata()` (Python, `contrat_service.py:11-44`) — toute évolution doit être faite des deux côtés.
- **L'endpoint `/api/contrats` n'utilise pas `Depends(get_current_user)`** (cf. § 3.2.3) — `created_by` n'est jamais rempli sauf si le frontend le passe explicitement, ce qu'il ne fait pas → la colonne `contrats.created_by` reste NULL.
- **Pas de validation que le client a un SIRET** au moment de la création — un contrat peut être créé pour un client sans SIRET puis bloquer Chorus Pro plus tard.
- **`ContratCreate.client_nom` est obligatoire mais redondant** avec `clients_cache.nom` — risque de désynchronisation entre snapshot et source.

### Workflow 2 — Renouvellement d'un contrat

**Déclencheur** : page `Renouvellements.js` (`/renouvellements`) liste les contrats `EN_COURS`/`A_RENOUVELER` dont la `date_fin` tombe dans le mois courant (modifiable). Trois actions possibles par contrat.

**Pages frontend impliquées** : `Renouvellements.js` (sélection + actions), parfois `TunnelContrat.js?mode=renouvellement` pour le cas NOUVEAU_CONTRAT.

**Endpoints backend appelés (selon le type)** :

| Type | Endpoint | Effet |
| --- | --- | --- |
| `SPONTANE` (prolongation 1 an) | `POST /api/contrats/{id}/renouveler` body `{type_renouvellement: "SPONTANE"}` | Mute `date_fin` += 1 an, recalcule `nombre_annees`, statut → `EN_COURS`, ajoute une ligne `PlanFacturation` (numero = max+1, type ANNUELLE) |
| `FIN` (départ client) | idem body `{type_renouvellement: "FIN", notes: "..."}` | `statut=TERMINE`, `motif_fin=notes` |
| `NOUVEAU_CONTRAT` | idem body `{type_renouvellement: "NOUVEAU_CONTRAT", nouveau_numero: "...", nouvelle_date_debut, nouvelle_date_fin}` | Archive l'ancien (TERMINE), copie ses articles, **intègre les articles des avenants enfants si rang ≤7**, génère un nouveau plan, statut BROUILLON. `numero_avenant` non recopié — le nouveau a `type_contrat=RENOUVELLEMENT`, `contrat_parent_id` = ancien. |

**Action en lot** : `POST /api/contrats/renouveler-lot` body `{ids: [...], type_renouvellement: "SPONTANE" | "FIN"}` — ne supporte pas `NOUVEAU_CONTRAT`.

**Tables modifiées** :
- `contrats` : UPDATE de l'ancien + INSERT du nouveau (NOUVEAU_CONTRAT) ; UPDATE seul (SPONTANE/FIN).
- `contrat_articles` : INSERT × N (copie + avenants) en mode NOUVEAU_CONTRAT.
- `plan_facturation` : INSERT × N en NOUVEAU_CONTRAT, INSERT × 1 en SPONTANE.
- Avenants enfants : leur `statut` est forcé à TERMINE en mode NOUVEAU_CONTRAT.

**Appels externes** : aucun.

**Effets de bord** : aucun (pas de doc, pas de facture émise).

**Points de friction identifiés** :
- En mode SPONTANE en lot, le commit est fait **par contrat** dans une boucle Python (`contrats.py:600-633`) — pas de transaction globale, donc si le job crashe au milieu, certains contrats sont prolongés et d'autres non.
- Le **`numero_contrat` du nouveau contrat doit être saisi manuellement** par l'utilisateur (`nouveau_numero` obligatoire) — pas de génération automatique.
- En mode NOUVEAU_CONTRAT, **l'intégration des articles d'avenants est silencieusement plafonnée à 7** ; les articles au-delà sont perdus sans alerte UI.
- Le statut `A_RENOUVELER` est listé dans le filtre (`contrats.py:134`) mais **aucun endpoint ne met ce statut** — il est issu d'un workflow batch hypothétique (probablement legacy).

### Workflow 3 — Révision Syntec annuelle (facturation N)

**Déclencheur** : utilisateur (ADMIN/GESTIONNAIRE) ouvre `/facturation` et sélectionne une année cible.

**Pages frontend impliquées** : `Facturation.js`.

**Étapes backend (séquentielles)** :

1. **`GET /api/facturation/apercu/{annee}` (filtre optionnel `famille`)** — liste les plans `PLANIFIEE`/`CALCULEE` de l'année, sur des contrats EN_COURS. Pour chaque plan, calcule à la volée la règle de révision (`get_regle_revision`) et vérifie la disponibilité des indices nécessaires (`verifier_indices_disponibles` : pour facturer N, il faut indice mois M des années N-2 et N-1). Champ `facturable = annee <= annee_courante` (interdit le futur).

2. **L'utilisateur sélectionne un sous-ensemble de plans et clique "Calculer"** → `POST /api/facturation/calculer` body `{annee, plan_ids: [...], nouveaux_montants: {plan_id: montant}}` (le `nouveaux_montants` n'est requis que pour les contrats DIGITECH). Pour chaque plan :
   - Première année de contrat → pas de révision (taux 1.0, `montant_revise = montant_prevu`).
   - `valider_pre_calcul()` (`validation_service.py:114`) — checks bloquants (statut pas EMISE, indices dispo, montant ref > 0).
   - `calculer_revision()` (`revision_service.py:97`) calcule `taux = indice_new / indice_ref`, `montant_revise = montant_precedent × taux`.
   - UPDATE `plan_facturation` : `montant_annuel_precedent`, `montant_revise_ht`, `taux_revision`, `indice_calcul_id`, `statut = CALCULEE`.

3. **L'utilisateur clique "Lancer la facturation"** → `POST /api/facturation/lancer` body `{annee, plan_ids: [...]}`. Pour chaque plan :
   - Construit une ligne Karlia **par article du contrat** (`sorted(articles, key=rang)`), applique le `taux_revision`, ajuste l'arrondi sur la dernière ligne pour respecter le total HT.
   - Si aucun article → fallback ligne unique avec montant total (probablement déclenché par le `validation_service`).
   - Appelle `karlia.traitement_lot_factures()` (séquentiel, pause 0.8s entre requêtes) → POST `/documents` sur Karlia (`id_type=4`, `id_status=0=Brouillon`).
   - Si succès : UPDATE plan (`statut=EMISE`, `facture_karlia_id`, `facture_karlia_ref`, `montant_annuel_precedent = montant_revise_ht`) + `valider_post_emission()` (warnings sur cohérence).
   - Si échec : `statut=ERREUR`, `erreur_message`.
   - Génère un `lot_id` (UUID) mais **ne le persiste pas** dans `lots_facturation` (cf. § 3.5 trou identifié).

**Tables modifiées** :
- `plan_facturation` (UPDATE statut + montants + IDs Karlia).
- **Pas d'INSERT dans `lots_facturation`** alors que la table existe.

**Appels externes** : POST Karlia `/documents` × N (séquentiel, rate-limité ~75 req/min).

**Effets de bord** :
- Logs Python : `[ERREUR FACTURE] detail=... payload=...` en cas d'erreur (`karlia_service.py:297`).
- Pas de mail.

**Points de friction identifiés** :
- **`valider_pre_emission` non appelée** dans le flux réel (cf. § 4.6) — un plan peut être émis sans `client_karlia_id` ou sans article principal.
- **Aucune transaction globale** : si la moitié des plans échoue, les autres sont émis dans Karlia et marqués EMISE en base. Pas de rollback.
- **`lots_facturation` jamais alimenté** — pas de traçabilité du lot (qui, quand, combien, rapport).
- **Pas de bouton "réémettre"** ni "annuler" une facture en erreur : il faut nettoyer manuellement.
- **Calcul du taux** : `indice_new / indice_ref` arrondi 6 décimales, puis multiplié au montant. Si plusieurs plans utilisent les mêmes indices, le résultat n'est pas mémoizé — recalculé à chaque plan.

### Workflow 4 — Devis → Commande → Prestation → Facture (cycle commandes)

**Déclencheur** : devis Karlia accepté côté CRM → l'opportunité associée doit être marquée "non Traité" pour être pris en compte.

**Pages frontend impliquées** : `NouvellesCommandes.js` → `CommandesAPlanifier.js` → `CommandesPlanifiees.js` → `CommandesTerminees.js` (+ `ContratsACreer.js` pour les commandes flaggées `necessite_contrat`).

**Étapes** :

1. **Synchronisation devis** : `POST /api/commandes/sync` (manuel via le bouton "Synchroniser" sur `NouvellesCommandes.js`).
   - `karlia_devis_service.sync_devis_acceptes(db)` (cf. § 4.2).
   - Pull Karlia `/documents?id_type=1&id_status=2&update_date_min=...` paginé.
   - Pour chaque devis non encore en base et dont l'opportunité n'est PAS marquée "Traité" : INSERT `commandes` (statut `nouvelle`) + INSERT `commande_lignes` × N.
   - Récupère détail client + PDF URL.
   - **Marque l'opportunité comme "Traité"** côté Karlia (`POST /opportunities/{id}/custom-fields/66505 {field_value: 1}`).
   - UPDATE `parametres.derniere_synchro_devis`.

2. **Validation par l'utilisateur** : `POST /api/commandes/{id}/valider` body `{type_traitement: "a_planifier" | "sans_planification", necessite_contrat: bool}`.
   - Si `a_planifier` → statut `a_planifier`.
   - Si `sans_planification` → statut `deployee` directement.
   - Set `necessite_contrat` (flag pour `ContratsACreer.js`).

3a. **Si `a_planifier`** :
   - Page `CommandesAPlanifier.js`.
   - `POST /api/prestations/from-commande/{commande_id}` → génère N `Prestation` (une par `commande_ligne`).
   - L'utilisateur attribue les formateurs : `PUT /api/prestations/{id}` (set `formateur_id`).
   - Planifie : `POST /api/prestations/{id}/planifier` body `{date_planifiee, heure_debut, heure_fin, lieu, agenda_formateur_id}`.
     - **Appel Google Calendar** via `google_calendar_service` — mais c'est un stub (cf. § 4.8), donc `prestations.google_sync_status = "pending"` reste figé.
   - `POST /api/commandes/{id}/planifier` body `{date_planifiee, intervenant_id, intervenant_nom, notes}` — met `commandes.statut=planifiee` (note : utilise les colonnes legacy `intervenant_*`, pas `formateur_id`).
   - Quand toutes les prestations sont marquées `realisee` (via `POST /api/prestations/{id}/realiser` depuis `MesPrestations.js`), la commande passe à `deployee` manuellement (pas d'automatisme observé).

3b. **Si `sans_planification`** : la commande est déjà en `deployee`, on saute l'étape 3a.

4. **Création de contrat (si `necessite_contrat=true`)** :
   - Page `ContratsACreer.js`.
   - Lien vers `TunnelContrat?mode=nouveau` (workflow 1).
   - À la fin : `POST /api/commandes/{id}/lier-contrat/{contrat_id}` — set `commandes.contrat_id`.

5. **Facturation** : page `CommandesTerminees.js`.
   - `POST /api/commandes/{id}/facturer` → émet une facture Karlia (`karlia.creer_facture`) avec gestion des remises PERCENT/AMOUNT.
   - Statut commande → `facturee`, set `facture_karlia_id`, `facture_karlia_ref`.

**Tables modifiées** :
- `commandes` (INSERT à la synchro, UPDATE à chaque transition de statut)
- `commande_lignes` (INSERT à la synchro)
- `prestations` (INSERT via `from-commande`, UPDATE à la planification/réalisation)
- `parametres` (UPDATE `derniere_synchro_devis`)

**Appels externes** :
- Karlia : `/documents` (pull devis), `/documents/{id}` (détail), `/customers/{id}` (client), `/opportunities/{id}` (custom field 66505), `/documents` (POST facture).
- Google Calendar : stub (devrait être appelé en `planifier_prestation`).

**Effets de bord** :
- Le marquage "Traité" côté Karlia est **non réversible** depuis l'app — un devis ignoré reste ignoré.
- Pas de retour en arrière sur le statut commande (la transition `deployee → planifiee` n'existe pas).

**Points de friction identifiés** :
- **Statut `terminee` vs `deployee` ambigu** : la route `/terminees` filtre `deployee`, mais `POST /api/commandes/{id}/terminer` met `terminee`. Deux statuts concurrents (cf. § 3.4).
- **`commandes.formateur_id` et `commandes.intervenant_id` cohabitent** : le second est legacy, mais `planifier_commande` continue de l'écrire (`commandes.py:353-354`).
- **Google Calendar non branché** alors que toute la plomberie front (sync status, error, calendar ID) est en place.
- **Pas de bouton "annuler la facturation"** depuis la commande.
- La transition vers `facturee` met à jour `commande.facture_karlia_id` mais **ne déclenche pas** automatiquement la synchronisation Chorus Pro (workflow 7) — c'est manuel.

### Workflow 5 — Génération du plan de facturation

**Déclencheur** : interne à la création (workflow 1) ou à la modification d'un contrat BROUILLON, ou au renouvellement NOUVEAU_CONTRAT (workflow 2).

**Pages frontend impliquées** : `TunnelContrat.js`, `ModifierContrat.js`, `Renouvellements.js`.

**Endpoints backend** : appelé en interne par `contrats.py` (pas d'endpoint dédié). Logique dans `contrat_service.generer_plan_facturation()`.

**Algorithme** :
1. Calcul de `nombre_annees = date_fin.year - date_debut.year + 1` (années civiles, pas calendaires).
2. Pour chaque année de `date_debut.year` à `date_fin.year` :
   - **Année 1 si prorata** → `type_facture=PRORATE`, `date_echeance = date_debut` si pas 1er janvier, sinon `01/01/annee`, `montant_ht_prevu = prorata.montant_ht`.
   - **Sinon** → `type_facture=ANNUELLE`, `date_echeance = 01/01/annee`, `montant_ht_prevu = montant_annuel_ht` (sera révisé à l'émission).
   - Statut initial : `PLANIFIEE`.

**Tables modifiées** : `plan_facturation` (INSERT × `nombre_annees`).

**Appels externes** : aucun.

**Effets de bord** : aucun.

**Points de friction identifiés** :
- **`generer_plan_facturation` ne nettoie pas les anciens plans** — la responsabilité est laissée au caller (`modifier_contrat` fait `db.query(PlanFacturation).filter(...).delete()` avant, `creer_contrat` n'a pas besoin de nettoyer).
- **La date d'échéance d'une facture PRORATE** = `date_debut` si pas 1er janvier, **mais ce n'est pas toujours souhaitable** (l'utilisateur peut vouloir facturer fin de mois, début d'année suivante, etc.). Pas de paramètre d'override.
- **Pas de gestion des contrats à cheval sur plusieurs périodes de révision** (cas Cosoluce + Maintenance dans un même contrat — théoriquement impossible avec la modélisation actuelle, mais pas verrouillé).

### Workflow 6 — Émission d'une facture vers Karlia

**Déclencheur** : interne au workflow 3 (révision Syntec) ou au workflow 4 (`facturer_commande`).

**Pages frontend impliquées** : `Facturation.js` (lot) ou `CommandesTerminees.js` (ad hoc).

**Endpoints backend** : `POST /api/facturation/lancer` ou `POST /api/commandes/{id}/facturer`.

**Payload Karlia** envoyé à `POST /documents` :

```json
{
  "id_customer": <int karlia_customer_id>,
  "id_type": 4,
  "id_status": 0,
  "reference": "<numero_contrat ou reference_devis>",
  "date": "JJ/MM/AAAA",
  "date_end": "JJ/MM/AAAA",
  "description": "Facturation ...",
  "products_list": [
    {
      "id_product": "<karlia_product_id>",   // si présent → pas de description
      "price_without_tax": 1234.56,
      "quantity": 1.0,
      "id_vat": "1"                          // 1=20%, 2=10%, 3=5.5%, 4=0%
    },
    { "description": "...", "price_without_tax": ..., "quantity": ..., "id_vat": "..." }
  ]
}
```

**Spécificités** :
- `id_status: 0` = Brouillon à la création. Après la transmission Chorus Pro (workflow 8), `marquer_facture_envoyee()` met `id_status: 2` (= Envoyée).
- `id_product` obligatoire sur la ligne principale (rang 0) — sinon la facture Karlia s'enregistre avec montant 0 (documenté dans `CODING_RULES.md` et `validation_service.py:28`).
- Mapping TVA → id_vat (cf. § 4.1.4).

**Tables modifiées** :
- `plan_facturation` : statut → EMISE, `facture_karlia_id`, `facture_karlia_ref`, `montant_annuel_precedent` (workflow 3).
- `commandes` : statut → `facturee`, `facture_karlia_id`, `facture_karlia_ref` (workflow 4).

**Appels externes** : Karlia `/documents` POST (un par facture, séquentiel).

**Effets de bord** :
- Création d'une facture Karlia (visible côté CRM, statut Brouillon).
- Pas d'envoi par mail automatique côté Karlia (statut Brouillon, pas "envoyée").

**Points de friction identifiés** :
- **`id_product` manquant n'est pas bloquant côté serveur** (warning seulement dans `validation_service`) → risque facture à 0 €. Cf. § 4.6.
- **L'ajustement d'arrondi sur la dernière ligne** (cf. `facturation.py:189-197`) peut produire un prix unitaire avec décimales surprenantes côté CRM Karlia.
- **Pas de tentative de re-publish** si Karlia 429 (rate limit) — l'erreur est juste loguée et le plan passe en ERREUR.

### Workflow 7 — Import des factures Karlia → table `factures_karlia` (préparation Chorus Pro)

**Déclencheur** : utilisateur (ADMIN/GESTIONNAIRE) clique « Synchroniser depuis Karlia » sur `ChorusProPage.js`.

**Pages frontend impliquées** : `ChorusProPage.js` exclusivement.

**Endpoints backend** : `POST /api/chorus/synchro-factures` (`api/chorus.py:176-291`).

**Algorithme** :
1. Pull Karlia : `karlia._get("/documents", {type: 4, status: 1, limit: 500, order: "date", direction: "DESC"})`.
2. Filtre Python : ne garde que `id_type==4` ET `canceled==0`.
3. Pour chaque facture :
   - Si déjà en base ET `statut_chorus = NON_TRANSMISE` → UPDATE (rafraîchit montants, SIRET via `clients_cache`, date_echeance).
   - Sinon (nouvelle) → INSERT avec `statut_chorus = NON_TRANSMISE`.
4. Pas de marquage côté Karlia.

**Tables modifiées** :
- `factures_karlia` (INSERT/UPDATE).

**Appels externes** : Karlia `/documents` (un seul appel paginé, limit 500).

**Effets de bord** : aucun.

**Points de friction identifiés** :
- **`status: 1`** correspond à "Acceptée" côté Karlia — c'est curieux pour une facture, mais c'est le statut utilisé par l'app. À clarifier (peut-être un mapping différent côté Karlia entre `id_type`).
- **Pas de pagination explicite** : si plus de 500 factures à synchroniser, on en perd. (Le bon usage serait une boucle avec `offset`.)
- **Pas de gestion des factures annulées en base** : si une facture passe à `canceled=1` côté Karlia après import, l'app ne le sait pas et continuera à la proposer en transmission.
- **Lien `client_karlia_id` (entier dans `factures_karlia`) vs `karlia_id` (varchar dans `clients_cache`)** : type incompatible → le matching SIRET passe par un `db.query(ClientCache).filter(ClientCache.karlia_id == str(client_id))` (cf. `chorus.py:218-220`).

### Workflow 8 — Transmission Chorus Pro (PISTE OAuth)

**Déclencheur** : utilisateur sélectionne des factures dans `ChorusProPage.js` et clique « Transmettre ».

**Pages frontend impliquées** : `ChorusProPage.js`.

**Endpoints backend** : `POST /api/chorus/transmettre` body `{facture_ids: [...], code_service_destinataire?, dry_run?}` (`api/chorus.py:415-575`).

**Pré-requis** : `parametres.chorus_id_fournisseur` rempli (sinon `ChorusError("idFournisseur manquant")`). Voir `docs/CHORUS_PRO_RACCORDEMENT.md` pour le statut actuel (auto-config KO).

**Algorithme par facture** :
1. Vérifications : facture existe, n'est pas déjà TRANSMISE/ACCEPTEE/EN_COURS, a un `client_siret` non vide.
2. Si `dry_run` : construit le payload et retourne sans envoyer.
3. Sinon :
   - INSERT `transmissions_chorus` (statut EN_COURS, `is_test=false`, `transmis_par`).
   - `facture.statut_chorus = EN_COURS`, commit.
   - Construit le payload V5.01 via `ChorusProService.soumettre_facture()` :
     - `fournisseur.idFournisseur` lu depuis `parametres`
     - `destinataire.codeDestinataire = client_siret`
     - `destinataire.codeServiceExecutant` si `code_service_destinataire` ou `facture.client_code_service` fourni
     - `lignePoste[]` (une seule ligne par défaut, montant HT = `montant_ht`)
     - `ligneTva[]` (taux 20% par défaut)
     - `montantTotal.montantHtTotal/montantTVA/montantTtcTotal/montantAPayer`
   - OAuth2 PISTE : `POST oauth.piste.gouv.fr/api/oauth/token` (cached 55 min).
   - POST `api.piste.gouv.fr/cpro/factures/v1/soumettre` (sandbox ou prod selon `chorus_mode_qualification`).
   - Si HTTP 200 : extrait `numeroFluxDepot` + `identifiantFactureCPP`, UPDATE transmission (SUCCES + IDs + `payload_json=last_request` + `reponse_json=last_response`), UPDATE facture (TRANSMISE + `chorus_numero_flux` + `date_transmission`), **appel Karlia `marquer_facture_envoyee()` → `id_status: 2`**.
   - Si erreur (ChorusError ou Exception) : transmission → ECHEC avec détails complets dans `reponse_json` (status_code, headers avec `x-correlationid`, body_text, body_json — cf. travail `fix/chorus-payload-v5-01`).

**Tables modifiées** :
- `transmissions_chorus` (INSERT puis UPDATE)
- `factures_karlia` (UPDATE statut/erreur)

**Appels externes** :
- PISTE OAuth (sandbox-oauth.piste.gouv.fr ou oauth.piste.gouv.fr)
- PISTE Chorus Pro factures (sandbox-api ou api selon `mode_qualification`)
- Karlia `POST /documents/{id}` pour marquer "envoyée" après succès Chorus

**Effets de bord** :
- Facture Karlia passe de "Brouillon" (id_status=0) à "Envoyée" (id_status=2).
- Côté Chorus Pro, la facture est déposée et entre dans le workflow de validation public.

**Points de friction identifiés** :
- **Bloqué actuellement (2026-05-18)** : tous les appels Chorus Pro retournent HTTP 403 — raccordement portail Chorus Pro à finaliser (cf. `docs/CHORUS_PRO_RACCORDEMENT.md`).
- **Pas de polling de statut Chorus Pro** : une facture passe TRANSMISE et y reste. Aucun job ne vient interroger `/consulter/facture` pour passer à ACCEPTEE/REJETEE.
- **L'appel `marquer_facture_envoyee` (Karlia)** n'est pas catché correctement si Karlia rate-limite — il est try/except dans `chorus.py:509-512` mais ne fait que loguer.
- **Pas de transaction Chorus + Karlia** : si la transmission Chorus réussit puis l'appel Karlia échoue, l'état diverge (Chorus reçue mais Karlia toujours en Brouillon).
- **`chorus.py:soumettre_facture()` ne ré-essaye pas** sur 429 ou 503 transient.

### Workflow 9 — Synchronisation Karlia → DB locale (clients + articles)

**Déclencheur** :
- Automatique : cron APScheduler chaque nuit à 02h00 (TZ Europe/Paris), défini dans `main.py:165`.
- Automatique : au démarrage du backend (`main.py:159`).
- Manuel : `POST /api/synchro/lancer` (bouton "Synchroniser" sur `Dashboard.js` et `Parametres.js`).

**Pages frontend impliquées** : `Dashboard.js`, `Parametres.js`.

**Algorithme `synchro_karlia()` (`main.py:48-148`)** :
1. Recharger `karlia.api_key` depuis `parametres.karlia_api_key` (au cas où elle a changé).
2. Si clé vide → skip avec log.
3. **Clients** : boucle `GET /customers?limit=100&offset=N` paginé jusqu'à épuisement.
   - Pour chaque client : extrait adresse "main" (filtre `address_list` par `type==main`), construit le dict, UPDATE si `karlia_id` existant ou INSERT.
   - Si nouveau et `numero_client` déjà pris en base par un autre → fallback `numero = f"K{karlia_id}"`.
4. **Articles** : `GET /products?limit=500` (un seul appel — pas de pagination).
   - INSERT/UPDATE par `karlia_id`.
5. UPDATE `parametres.derniere_synchro` (format `DD/MM/AAAA HH:MM`) et `parametres.synchro_stats` (`"X clients, Y articles"`).

**Tables modifiées** :
- `clients_cache` (INSERT/UPDATE)
- `articles_cache` (INSERT/UPDATE)
- `parametres` (UPDATE)

**Appels externes** : Karlia `/customers` (paginé), `/products` (un seul appel limit=500).

**Effets de bord** :
- Logs Python `[SYNCHRO] Démarrage ...`, `[SYNCHRO] Terminée — X clients, Y articles`.
- En cas d'erreur, le `try/except` global capture mais **commit partiel** : si une page de clients est commitée puis l'étape suivante crashe, les clients déjà importés restent.

**Points de friction identifiés** :
- **Articles limités à 500** : pas de pagination — si > 500 articles, on en perd silencieusement.
- **Pas de soft-delete** : si un client est supprimé côté Karlia, il reste en base locale (zombie). Aucun nettoyage.
- **Si la clé Karlia est révoquée**, la synchro échoue silencieusement (`KarliaError(401)` logué, pas de notification UI).
- **Le bouton "Synchroniser" est synchrone côté HTTP** : `POST /api/synchro/lancer` attend que tout finisse (peut prendre plusieurs minutes pour quelques milliers de clients), bloquant la requête HTTP.
- **`clients_cache.numero_client` UNIQUE n'est pas appliqué en DB** (cf. § 2.18) — le fallback `K{karlia_id}` peut donc lui-même collider silencieusement.

### Workflow 10 — Cycle d'authentification (JWT)

**Déclencheur** : ouverture de l'application sans token, ou navigation après expiration.

**Pages frontend impliquées** : `Login.js`, intercepteur `services/api.js`, `AuthContext.js`.

**Étapes** :

1. **Login** :
   - `Login.js` → `useAuth().login(username, password)`.
   - `AuthContext.login` → `authAPI.login(username, password)` → `POST /api/auth/login` (form-urlencoded `username` + `password`).
   - Backend (`auth.py:27-46`) : vérifie bcrypt, génère JWT HS256 avec payload `{sub: login, role, id, formateur_id, exp: now+24h}`.
   - Réponse : `{access_token, token_type: "bearer", nom_complet, role, formateur_id}`.
   - Frontend : `localStorage.setItem('token', access_token)`, `setUser({...})`, `setDroits(getDroitsByRole(role))`, redirection vers `/`.

2. **Requêtes protégées** :
   - Intercepteur Axios ajoute `Authorization: Bearer <token>` à chaque requête.
   - Backend : `Depends(get_current_user)` décode JWT, vérifie `actif`, retourne `Utilisateur`.

3. **Au reload navigateur** :
   - `AuthProvider` au mount → si `localStorage.token` présent → `authAPI.me()` → `GET /api/auth/me`.
   - Backend renvoie le profil. Frontend repopule `user` + `droits`.
   - Si erreur → `localStorage.removeItem('token')`, `setUser(null)`, redirige `/login`.

4. **Expiration** :
   - Token JWT valide **24h en dur** (`auth.py:23`) — **ignore** le setting `ACCESS_TOKEN_EXPIRE_MINUTES = 480` de `config.py` (cf. § 3.2.1).
   - Pas de refresh token.
   - À expiration, prochain appel retourne 401 → intercepteur Axios vide le token et redirige `/login` (full reload via `window.location.href`).

5. **Logout** :
   - `AuthContext.logout` : `localStorage.removeItem('token')`, `setUser(null)`, `window.location.href = '/login'`.

**Tables modifiées** : aucune (le champ `utilisateurs.derniere_connexion` existe en base mais **n'est jamais mis à jour** par le code).

**Appels externes** : aucun.

**Effets de bord** : `localStorage` du navigateur.

**Points de friction identifiés** :
- **`utilisateurs.derniere_connexion` jamais alimenté** alors que la colonne existe.
- **JWT 24h en dur ignorant le setting** (cf. § 3.2.1).
- **Pas de mécanisme de révocation** : un token volé reste valide 24h, pas de blacklist.
- **`SECRET_KEY` lu une fois au démarrage** : si elle change dans `.env` et qu'on redémarre, tous les tokens en circulation sont invalidés (acceptable, mais non documenté).
- **Pas de rate limit sur `/api/auth/login`** : brute force possible.
- **Pas de captcha / 2FA**.
- **`logout` fait un full reload** au lieu d'utiliser `useNavigate` — pas critique mais inhabituel.

### Workflow 11 — Gestion des rôles et filtres d'affichage

**Déclencheur** : chaque navigation / chaque chargement de page.

**Pages frontend impliquées** : toutes, mais principalement via `Layout.js` (menu) et `App.js` (`PrivateRoute`).

**Modèle** :

Le rôle est posé dans `utilisateurs.role` (varchar, **pas de CHECK constraint** — cf. § 2.11). Quatre rôles définis :

| Rôle | Auteur | Périmètre |
| --- | --- | --- |
| `ADMIN` | Manuel via `/utilisateurs` ou seed | Tout |
| `GESTIONNAIRE` | idem | Tout sauf `parametres` + `utilisateurs` |
| `TECHNICIEN` | idem | Contrats lecture seule + ses prestations |
| `FORMATEUR` | idem | Seulement `/mes-prestations` + Dashboard |

**Filtrage côté frontend** (deux niveaux) :

1. **`PrivateRoute` (`App.js:33-48`)** : si `allow={isNotFormateur}` et `user.role === 'FORMATEUR'` → redirige `/mes-prestations`. Sinon 19 routes accessibles.
2. **`Layout.js` (lignes 49-73)** : choisit `MENU_COMPLET` / `MENU_FORMATEUR` / `MENU_TECHNICIEN` selon `user.role`. Pour `MENU_COMPLET`, filtre chaque item par `droits[item.droit]`.

**Filtrage côté backend** :

- Endpoints `parametres.py` / `utilisateurs.py` : `current_user.role != "ADMIN"` → 403.
- Endpoints `chorus.py`, `commandes.py`, `prestations.py`, `formateurs.py` : utilisent `Depends(get_current_user)` mais **ne vérifient pas le rôle** — un FORMATEUR avec un token valide peut techniquement appeler `POST /api/chorus/transmettre` s'il connaît l'URL.
- Endpoints `contrats.py`, `indices.py`, `facturation.py`, `documents.py` : **pas de `Depends(get_current_user)` du tout** (cf. § 3.2.3) — accessibles à n'importe quel client tant qu'il joint nginx.

**Lien `utilisateur ↔ formateur`** :
- `utilisateurs.formateur_id` (FK → `formateurs.id`).
- Obligatoire pour rôles FORMATEUR et TECHNICIEN (vérification dans `creer_utilisateur`).
- Utilisé par `MesPrestations.js` pour cibler les prestations propres (`GET /api/prestations/formateur/{user.formateur_id}`).
- Un ADMIN avec `formateur_id` rempli voit aussi l'item "Mes prestations" dans son menu (cf. § 5.6.2).

**Filtres `familles` sur les contrats** :
- `lister_contrats(familles="COSOLUCE,CANTINE")` filtre `Contrat.famille_contrat IN (...)`.
- Le frontend ne pose pas systématiquement ce filtre selon le rôle — il est passé manuellement via la querystring depuis l'UI.

**Tables modifiées** : aucune au cours d'une navigation.

**Appels externes** : aucun.

**Effets de bord** : aucun.

**Points de friction identifiés** :
- **Double définition de la matrice de droits** (`backend/utilisateurs.py` + `frontend/AuthContext.js`) — divergence possible.
- **Filtrage backend incomplet** : la majorité des endpoints supposent que le frontend filtre, ce qui est faux dès qu'on contourne le frontend (cf. § 3.2.3).
- **Pas de scope par client / par famille** : un GESTIONNAIRE voit tous les contrats de toutes les familles. Pas de multi-tenant ou de scope géographique.
- **Le rôle `TECHNICIEN`** est jeune (commit `ad36a41`, tag `v2.3.0`) et son menu (`MENU_TECHNICIEN`) inclut "Contrats techniques" qui pointe vers `/contrats` sans filtre métier — c'est la même page que pour un GESTIONNAIRE, juste avec `contrats_ecriture: false`. La sémantique "Contrats techniques" est portée par le label, pas par le code.
- **Pas de soft-delete** sur `utilisateurs` : pour désactiver un compte, il faut soit set `actif=False`, soit le supprimer (hard delete via `DELETE /api/utilisateurs/{id}`).

---

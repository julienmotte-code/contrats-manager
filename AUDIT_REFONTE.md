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

## 2. Modèle de données PostgreSQL

### 2.1 Vue d'ensemble — 17 tables groupées par domaine

`backend/app/models/models.py` (490 lignes) déclare **17 classes SQLAlchemy** ; la DB live confirme **17 tables** dans le schéma `public`. Groupement métier (et volumétrie actuelle au 21/05/2026) :

| Domaine | Tables | Volumétrie (n_live_tup) |
|---|---|---|
| **Référentiels Karlia (cache)** | `clients_cache`, `articles_cache` | 251 + 404 |
| **Configuration et utilisateurs** | `parametres`, `utilisateurs`, `formateurs` | 14 + 8 + 7 |
| **Cœur Contrats** | `contrats`, `contrat_articles`, `indices_revision`, `plan_facturation`, `lots_facturation` | 572 + 572 + 6 + 1150 + 0 |
| **Génération documentaire** | `modeles_documents`, `documents_generes` | 4 + 1 |
| **Cycle Commandes** | `commandes`, `commande_lignes`, `prestations` | 142 + 196 + 11 |
| **Chorus Pro** | `factures_karlia`, `transmissions_chorus` | 15 + 4 |

> **Observation volumétrie** : `documents_generes` n'a qu'**1 ligne** alors que le module a 572 contrats actifs → la génération Word n'est quasiment pas utilisée en production. `lots_facturation` est **vide** → le traitement de facturation en lot n'a jamais tourné en réel. `prestations` n'a que 11 lignes alors que les commandes sont 142 → le workflow prestations est embryonnaire.

### 2.2 `clients_cache` — Cache local des clients Karlia

Source : `models.py:20-49` / DB live : 22 colonnes.

| Colonne | Type | Nullable | Défaut | Rôle |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuid4()` | PK |
| `karlia_id` | `varchar(100)` | NOT NULL | — | ID Karlia (UNIQUE) |
| `numero_client` | `varchar(20)` | NOT NULL | — | numéro client local (ex: `K12345`) |
| `nom` | `varchar(255)` | NOT NULL | — | raison sociale |
| `adresse_ligne1/2`, `code_postal`, `ville`, `pays` | `varchar` | NULL | `pays='France'` (models seulement) | adresse principale |
| `email`, `telephone`, `mobile` | `varchar` | NULL | — | contacts |
| `siret` | `varchar(14)` | NULL | — | identifiant légal |
| `tva_intracom` | `varchar(20)` | NULL | — | |
| `forme_juridique` | `varchar(100)` | NULL | — | |
| `contact_nom/prenom/fonction` | `varchar(150)` | NULL | — | contact principal (jamais peuplé d'après les API explorées) |
| `notes` | `text` | NULL | — | annotations libres |
| `synchro_at`, `created_at`, `updated_at` | `timestamptz` | NULL | `now()` | métadonnées |

**Relations SQLAlchemy** : `clients_cache.karlia_id` ← `contrats.client_karlia_id` (primaryjoin manuel, **pas de FK SQL**).

**Divergence #1** : `models.py:26` déclare `numero_client unique=True`, mais la **DB n'a pas de contrainte UNIQUE** sur cette colonne. Conséquence : possibilité de doublons côté code (la synchro vérifie manuellement et applique un fallback `K{karlia_id}`).

### 2.3 `articles_cache` — Cache local des articles Karlia

Source : `models.py:51-64` / DB live : 10 colonnes.

| Colonne | Type | Nullable | Défaut | Rôle |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuid4()` | PK |
| `karlia_id` | `varchar(100)` | NOT NULL UNIQUE | — | ID Karlia |
| `reference` | `varchar(100)` | NULL | — | réf catalogue |
| `designation` | `varchar(500)` | NOT NULL | — | libellé |
| `prix_unitaire_ht` | `numeric(12,4)` | NULL | — | prix HT |
| `unite` | `varchar(50)` | NULL | — | unité de vente |
| `taux_tva` | `numeric(5,2)` | NULL | `20.00` (models seulement) | TVA défaut |
| `actif` | `boolean` | NULL | `true` (models seulement) | dispo catalogue |
| `synchro_at`, `created_at` | `timestamptz` | NULL | `now()` | |

> **Note** : le défaut `taux_tva=20.00` n'est qu'une valeur Python (`Column(default=20.00)`) — la DB n'a pas de défaut SQL. Pour les lignes insérées hors ORM, la valeur sera NULL.

### 2.4 `indices_revision` — Historique des indices Syntec

Source : `models.py:67-82` / DB live : 10 colonnes.

| Colonne | Type | Nullable | Défaut | Rôle |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuid4()` | PK |
| `date_publication` | `date` | NOT NULL **UNIQUE** | — | date officielle de publication |
| `annee` | `integer` | NULL | — | année de l'indice (redondant avec `date_publication`) |
| `mois` | `varchar(10)` | NULL | `'AOUT'` | `AOUT` / `OCTOBRE` / `AUTRE` |
| `famille` | `varchar(50)` | NULL | `'SYNTEC'` | indice utilisé (seul `SYNTEC` est exploité) |
| `valeur` | `numeric(10,4)` | NOT NULL | — | valeur de l'indice |
| `commentaire` | `text` | NULL | — | |
| `source_url` | `varchar(500)` | NULL | — | URL source (souvent la source INSEE) |
| `created_by`, `created_at` | — | — | — | |

**Divergence #2** : `date_publication` est `UNIQUE` en DB (`indices_revision_date_publication_key`) mais `models.py:72` ne le déclare pas (`nullable=False` uniquement).

**FK entrantes** : `contrats.indice_reference_id`, `plan_facturation.indice_calcul_id`, `lots_facturation.indice_utilise_id`.

### 2.5 `contrats` — Table centrale des contrats pluriannuels

Source : `models.py:85-150` / DB live : 29 colonnes.

| Colonne | Type | Nullable | Défaut | Rôle |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuid4()` | PK |
| `numero_contrat` | `varchar(100)` | NOT NULL UNIQUE | — | numéro métier (ex `CO-XXXX-XXX`) |
| `client_karlia_id` | `varchar(100)` | **NULL (DB)** / NOT NULL (models) | — | ID client Karlia |
| `client_numero`, `client_nom` | `varchar` | NULL | — | dénormalisation |
| `date_debut`, `date_fin` | `date` | NOT NULL | — | bornes contrat |
| `nombre_annees` | `integer` | NOT NULL | — | durée en années |
| `montant_annuel_ht` | `numeric(12,2)` | NOT NULL | — | montant HT annuel de référence |
| `indice_reference_id` | `uuid` | NULL | — | FK `indices_revision` (indice de départ) |
| `prorate_annee1` | `boolean` | NULL | — | active calcul prorata année 1 |
| `prorate_nb_mois` | `numeric(4,1)` | NULL | — | nombre de mois (.5 si demi-mois) |
| `prorate_montant_ht` | `numeric(12,2)` | NULL | — | montant prorata calculé |
| `prorate_validated` | `boolean` | NULL | — | validation manuelle prorata |
| `prorate_note` | `text` | NULL | — | |
| `prorate_demi_mois` | `boolean` | NULL | `false` | active calcul en demi-mois |
| `notes_internes` | `text` | NULL | — | annotations internes |
| `famille_contrat` | `varchar(50)` | NULL | `'COSOLUCE'` | détermine la règle Syntec (AOUT/OCTOBRE) |
| `contrat_parent_id` | `uuid` | NULL | — | FK self (avenants/renouvellements) |
| `type_contrat` | `varchar(30)` | NULL | `'CONTRAT'` (models) | `CONTRAT` / `AVENANT` / `RENOUVELLEMENT` |
| `numero_avenant` | `integer` | NULL | — | rang de l'avenant |
| `statut` | `varchar(30)` | NULL | `'BROUILLON'` (models) | `BROUILLON` / `EN_COURS` / `A_RENOUVELER` / `TERMINE` |
| `date_statut_change` | `date` | NULL | — | |
| `motif_fin` | `text` | NULL | — | |
| `avenants_fusionnes` | `boolean` | NULL | — | fusion des avenants effectuée |
| `created_by`, `created_at`, `updated_at`, `validated_at` | — | — | — | métadonnées |

**Contraintes CHECK** :
- `ck_dates_coherentes`: `date_fin > date_debut`
- `ck_type_contrat`: `IN ('CONTRAT','AVENANT','RENOUVELLEMENT')`
- `ck_statut`: `IN ('EN_COURS','A_RENOUVELER','TERMINE','BROUILLON')`

**Divergence #3** : `models.py:91` déclare `client_karlia_id` `nullable=False`, mais la DB autorise NULL. Risque : insertion sans client passerait côté DB mais échouerait côté ORM.

**FK** :
- sortantes : `indice_reference_id → indices_revision.id`, `contrat_parent_id → contrats.id` (self-ref)
- entrantes : `contrat_articles`, `plan_facturation`, `documents_generes`, `commandes`, `factures_karlia`

**Volumétrie actuelle** : 572 contrats, **tous en `statut='EN_COURS'` et `type_contrat='CONTRAT'`** → aucun avenant, aucun renouvellement, aucun brouillon dans la DB de prod aujourd'hui.

### 2.6 `contrat_articles` — Lignes article d'un contrat

Source : `models.py:153-173` / DB live : 10 colonnes.

| Colonne | Type | Nullable | Défaut | Rôle |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | `uuid4()` | PK |
| `contrat_id` | `uuid` | NOT NULL | — | FK `contrats.id` (CASCADE) |
| `rang` | `integer` | NOT NULL | — | 0 = principal, 1-7 = annexes |
| `article_karlia_id` | `varchar(100)` | NULL | — | référence catalogue |
| `designation` | `varchar(500)` | NOT NULL | — | libellé |
| `reference` | `varchar(100)` | NULL | — | |
| `prix_unitaire_ht` | `numeric(12,4)` | NULL | — | |
| `quantite` | `numeric(10,3)` | NULL | `1` (models seulement) | |
| `unite` | `varchar(50)` | NULL | — | |
| `taux_tva` | `numeric(5,2)` | NULL | `20.00` (models seulement) | |

**Contraintes** : `CHECK (rang BETWEEN 0 AND 7)`, `UNIQUE (contrat_id, rang)`.

> **Limitation structurelle** : un contrat est plafonné à **8 lignes** (1 principale + 7 annexes). Cette contrainte est dure (`ck_rang_valide`) — c'est un choix produit fort qui dictera la refonte si la limite doit être levée.

### 2.7 `plan_facturation` — Plan prévisionnel des factures

Source : `models.py:176-215` / DB live : 21 colonnes.

| Colonne | Type | Nullable | Défaut | Rôle |
|---|---|---|---|---|
| `id` | `uuid` | NOT NULL | — | PK |
| `contrat_id` | `uuid` | NOT NULL | — | FK `contrats.id` (CASCADE) |
| `numero_facture` | `integer` | NOT NULL | — | rang (1, 2, 3…) |
| `annee_facturation` | `integer` | NOT NULL | — | année cible |
| `date_echeance` | `date` | NOT NULL | — | échéance facture |
| `type_facture` | `varchar(20)` | NULL | `'ANNUELLE'` (models) | `PRORATE` / `ANNUELLE` |
| `montant_ht_prevu` | `numeric(12,2)` | NULL | — | montant prévisionnel |
| `montant_annuel_precedent` | `numeric(12,2)` | NULL | — | base de calcul Syntec |
| `taux_revision` | `numeric(8,6)` | NULL | — | coefficient appliqué |
| `montant_revise_ht` | `numeric(12,2)` | NULL | — | montant après révision |
| `indice_calcul_id` | `uuid` | NULL | — | FK `indices_revision.id` |
| `montant_ht_facture` | `numeric(12,2)` | NULL | — | montant retenu pour facturation |
| `facture_karlia_id` | `varchar(100)` | NULL | — | ID document Karlia |
| `facture_karlia_ref` | `varchar(100)` | NULL | — | référence facture Karlia |
| `karlia_synchro_at` | `timestamptz` | NULL | — | dernière sync |
| `karlia_statut` | `varchar(50)` | NULL | — | statut côté Karlia |
| `statut` | `varchar(30)` | NULL | `'PLANIFIEE'` (models) | `PLANIFIEE` / `CALCULEE` / `EMISE` / `ERREUR` |
| `erreur_message` | `text` | NULL | — | |
| `created_at`, `updated_at` | `timestamptz` | NULL | `now()` | |

**Contraintes** : `UNIQUE (contrat_id, numero_facture)`, `CHECK type_facture IN ('PRORATE','ANNUELLE')`, `CHECK statut IN ('PLANIFIEE','CALCULEE','EMISE','ERREUR')`.

### 2.8 `lots_facturation` — Historique des traitements en lot

Source : `models.py:218-232` / DB live : 11 colonnes / **0 ligne**.

| Colonne | Type | Rôle |
|---|---|---|
| `id`, `annee_traitement`, `indice_utilise_id`, `declenche_par`, `declenche_at` | — | identification du lot |
| `nb_contrats_traites`, `nb_factures_emises`, `nb_erreurs` | `integer` | compteurs |
| `statut` | `varchar(20)` | `EN_COURS` par défaut (models) |
| `termine_at` | `timestamptz` | |
| `rapport_json` | `json` | rapport détaillé |

> **Table vide en production** : le mécanisme de lot existe en code mais n'a **jamais été exécuté en réel**. À vérifier si le code reste pertinent dans la refonte ou s'il faut le retirer.

### 2.9 `documents_generes` — Fichiers Word/PDF produits

Source : `models.py:235-250` / DB live : 10 colonnes / **1 ligne**.

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `uuid` | PK |
| `contrat_id` | `uuid` | FK `contrats.id` (pas de CASCADE) |
| `type_document` | `varchar(50)` | nature (`CONTRAT`, `AVENANT`, …) |
| `nom_fichier` | `varchar(500)` | nom déposé sur disque |
| `chemin_docx`, `chemin_pdf` | `varchar(1000)` | chemins relatifs sous `storage/documents_generes/` |
| `modele_utilise` | `varchar(200)` | nom du modèle |
| `variables_json` | `json` | dump des substitutions effectuées |
| `generated_by`, `generated_at` | — | métadonnées |

> **Observation** : seul `chemin_docx` est jamais peuplé (pas de génération PDF en backend). La table ne décrit pas le rendu PDF Karlia (devis/factures) qui passe par `commandes.pdf_url`.

### 2.10 `modeles_documents` — Modèles Word uploadés

Source : `models.py:253-265` / DB live : 9 colonnes / 4 lignes.

Stocke les `.docx` uploadés via l'écran Paramètres. Champ `chemin_fichier` pointe vers `storage/modeles/`. Le filtrage de version repose sur `actif=true`.

### 2.11 `utilisateurs` — Comptes du module

Source : `models.py:268-281` / DB live : 10 colonnes / 8 lignes.

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `uuid` | PK |
| `login` | `varchar(100)` UNIQUE | identifiant de connexion |
| `email` | `varchar(255)` UNIQUE | |
| `nom_complet` | `varchar(200)` | |
| `password_hash` | `varchar(500)` | bcrypt |
| `role` | `varchar(30)` | `ADMIN` / `GESTIONNAIRE` / `FORMATEUR` / `TECHNICIEN` |
| `actif` | `boolean` | |
| `derniere_connexion` | `timestamptz` | |
| `formateur_id` | `integer` FK `formateurs.id` | lien optionnel vers fiche formateur |
| `created_at` | `timestamptz` | |

**Distribution actuelle des rôles** :

```
ADMIN        : 1
GESTIONNAIRE : 2
FORMATEUR    : 4
TECHNICIEN   : 1
```

> **Note** : aucune contrainte CHECK sur `role` — la liste des rôles valides n'est qu'une convention applicative (cf. `backend/app/api/auth.py`). Le rôle `CONSULTANT` a été supprimé en `v2.3.0` (commit `ad36a41`) au profit de `TECHNICIEN`.

### 2.12 `parametres` — Configuration globale clé/valeur

Source : `models.py:284-291` / DB live : 4 colonnes / 14 lignes.

```sql
PRIMARY KEY (cle)
cle         VARCHAR(100)   -- ex 'karlia_api_key'
valeur      TEXT           -- valeur courante (masquée à l'écran si secret)
description TEXT
updated_at  TIMESTAMPTZ
```

**Clés actuellement présentes en DB** (taille en caractères) :

| Clé | Taille | Description |
|---|---|---|
| `chorus_client_id` | 36 | OAuth2 PISTE Client ID |
| `chorus_client_secret` | 36 | OAuth2 PISTE Client Secret |
| `chorus_code_banque` | 0 | Code coordonnées bancaires (vide) |
| `chorus_code_service` | 0 | Code service fournisseur (vide) |
| `chorus_id_fournisseur` | 0 | (vide, jamais peuplé) |
| `chorus_id_utilisateur_courant` | 0 | (vide, jamais peuplé) |
| `chorus_mode_qualification` | 5 | `'true'`/`'false'` — sandbox PISTE actif |
| `chorus_siret_emetteur` | 14 | SIRET émetteur |
| `chorus_tech_password` | 13 | Mot de passe compte technique |
| `chorus_tech_username` | 31 | Login compte technique |
| `derniere_synchro` | 16 | Date dernière sync Karlia |
| `derniere_synchro_devis` | 26 | Date dernière sync devis |
| `karlia_api_key` | 34 | Clé API Karlia v2 |
| `synchro_stats` | 25 | Compteurs dernière sync |

> **Sécurité** : la table `parametres` stocke **en clair** des secrets (`karlia_api_key`, `chorus_client_secret`, `chorus_tech_password`). Ce design devra évoluer pour une migration GCP (Secret Manager) — cf. § 8.

### 2.13 `commandes` — Devis acceptés Karlia importés

Source : `models.py:298-341` / DB live : 36 colonnes / 142 lignes.

Cycle métier représenté : un devis accepté côté Karlia est importé localement, classé, planifié, puis facturé.

**Colonnes-clés** :

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `integer` (séquence) | PK (note : **integer**, pas UUID — incohérent avec les autres tables) |
| `karlia_document_id` | `integer` UNIQUE | ID du devis dans Karlia |
| `karlia_customer_id`, `karlia_opportunity_id` | `integer` | dénormalisation |
| `reference_devis` | `varchar(100)` | référence métier (ex `D2026-XXX`) |
| `client_nom/email/telephone/adresse/siret` | — | snapshot client à l'import |
| `montant_ht/tva/ttc` | `numeric(15,2)` | |
| `date_devis`, `date_acceptation` | `date` | |
| `date_import`, `date_validation` | `timestamp without time zone` | — |
| `statut` | `varchar(50)` | `nouvelle` / `a_planifier` / `planifiee` / `facturee` (valeurs constatées) |
| `type_traitement` | `varchar(50)` | classification métier |
| `necessite_contrat` | `boolean` | indique si la commande crée un contrat |
| `date_planifiee`, `intervenant_id`, `intervenant_nom`, `notes_planification` | — | planification |
| `contrat_id` | `uuid` FK `contrats.id` ON DELETE SET NULL | lien vers contrat éventuel |
| `pdf_devis` | `bytea` | binaire PDF (champ jamais lu : commit `f71d223` a retiré le code mort) |
| `pdf_devis_nom` | `varchar(255)` | nom du PDF |
| `pdf_url` | `text` | URL signée Karlia (utilisée par le frontend) |
| `formateur_id` | `integer` FK `formateurs.id` | |
| `facture_karlia_id`, `facture_karlia_ref` | `varchar(50)` | facture émise pour cette commande |
| `created_at`, `updated_at` | `timestamp without time zone` | — |
| `created_by`, `updated_by` | `integer` | (ID utilisateur, pas FK) |

**Index** : `karlia_document_id` (UNIQUE), `formateur_id`, `necessite_contrat`, `statut`.

**Distribution des statuts actuels** :

```
nouvelle    : 130
a_planifier :   9
facturee    :   2
planifiee   :   1
```

**Divergences majeures avec `models.py`** :
- **#4** `pdf_devis` : models.py:327 déclare `Text  # Base64 encoded` — c'était un héritage. La DB est `bytea` (binaire). Le code de manipulation a été retiré au commit `f71d223`. Le modèle SQLAlchemy n'a pas été mis à jour pour autant : il garde `Text`. **À aligner**.
- **#5** `date_import`, `date_validation`, `created_at`, `updated_at` : models.py utilise `DateTime(timezone=True)`, la DB est `timestamp without time zone`. Conséquence : risque de décalage TZ au moment de lire/écrire si l'app et la DB ne sont pas dans le même fuseau.

### 2.14 `commande_lignes` — Lignes d'une commande

Source : `models.py:344-364` / DB live : **17 colonnes** (models : 14) / 196 lignes.

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `integer` (séquence) | PK |
| `commande_id` | `integer` FK CASCADE | |
| `karlia_product_id`, `designation`, `description` | — | identification article |
| `quantite`, `unite`, `prix_unitaire_ht`, `taux_tva`, `montant_ht`, `montant_tva`, `montant_ttc` | — | montants |
| `ordre` | `integer` | ordonnancement |
| `created_at` | `timestamp without time zone` | — |
| **`discount_type`** | `varchar(20)` | type de remise (DB only) |
| **`discount_value`** | `numeric(15,6)` | valeur remise (DB only) |
| **`discount_percent`** | `numeric(15,6)` | pourcentage remise (DB only) |

**Divergence #6** : la DB a **3 colonnes supplémentaires** (`discount_type`, `discount_value`, `discount_percent`) que `models.py` ne déclare pas. Ces colonnes ont probablement été ajoutées manuellement pour stocker les remises Karlia lors d'évolutions hors Alembic. Conséquence : ces données sont **invisibles depuis SQLAlchemy** (pas lues, pas écrites par l'ORM, mais préservées par la DB).

### 2.15 `prestations` — Prestations à planifier

Source : `models.py:466-490` / DB live : **22 colonnes** (models : 17) / 11 lignes.

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `integer` (séquence) | PK |
| `commande_id` | `integer` FK CASCADE | |
| `commande_ligne_id` | `integer` FK SET NULL | |
| `formateur_id` | `integer` FK | formateur principal |
| `designation` | `varchar(500)` | |
| `description` | `text` | |
| `duree_jours` | `numeric(5,2)` | défaut `1` |
| `date_prevue`, `date_planifiee` | `date` | |
| `heure_debut`, `heure_fin` | `time` | |
| `lieu` | `varchar(500)` | |
| `google_event_id` | `varchar(255)` | ID événement Google Calendar |
| `statut` | `varchar(50)` | `a_planifier` / `planifiee` / `realisee` (valeurs constatées) |
| `notes` | `text` | |
| `created_at`, `updated_at` | `timestamptz` | |
| **`agenda_formateur_id`** | `integer` FK `formateurs.id` (DB only) | formateur cible de l'agenda (distinct du formateur assigné) |
| **`google_calendar_id`** | `varchar(255)` (DB only) | ID du calendrier Google |
| **`google_sync_status`** | `varchar(50)` (DB only) | statut sync |
| **`google_sync_error`** | `text` (DB only) | message d'erreur sync |
| **`google_synced_at`** | `timestamptz` (DB only) | dernière sync réussie |

**Index** : `commande_id`, `formateur_id`, `statut`.

**Divergence #7 (majeure)** : la DB a **5 colonnes supplémentaires** liées à Google Calendar (`agenda_formateur_id`, `google_calendar_id`, `google_sync_status`, `google_sync_error`, `google_synced_at`) absentes de `models.py`. Le service `google_calendar_service.py` (référencé en historique) a été **retiré** dans la période récente (`-44` lignes du diff phase 0). La table garde les colonnes mais sans aucun code applicatif derrière. **À nettoyer ou à réactiver**.

**Distribution des statuts** :

```
a_planifier : 6
planifiee   : 4
realisee    : 1
```

### 2.16 `formateurs` — Référentiel des formateurs

Source : `models.py:447-463` / DB live : 10 colonnes / 7 lignes.

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `integer` (séquence) | PK |
| `nom`, `prenom` | `varchar(255)` | |
| `email` | `varchar(255)` UNIQUE | |
| `email_google` | `varchar(255)` | email du compte Google associé (vestige de la sync calendar) |
| `telephone` | `varchar(50)` | |
| `actif` | `boolean` défaut `true` | |
| `couleur` | `varchar(7)` défaut `'#3788d8'` | code hex pour affichage calendrier |
| `created_at`, `updated_at` | `timestamptz` | |

**FK entrantes** : `commandes.formateur_id`, `prestations.formateur_id`, **`prestations.agenda_formateur_id`** (présent en DB seulement), `utilisateurs.formateur_id`.

### 2.17 `factures_karlia` — Cache local des factures Karlia

Source : `models.py:371-412` / DB live : 22 colonnes / 15 lignes.

| Colonne | Type | Nullable | Rôle |
|---|---|---|---|
| `id` | `uuid` | NOT NULL `gen_random_uuid()` | PK |
| `karlia_document_id` | `integer` UNIQUE | NOT NULL | ID Karlia |
| `numero_facture` | `varchar(100)` | NOT NULL | référence Karlia |
| `reference` | `varchar(200)` | NULL | |
| `client_karlia_id` | `integer` | NOT NULL | ID client Karlia |
| `client_nom`, `client_siret`, `client_code_service` | — | NULL | snapshot |
| `montant_ht/tva/ttc` | `numeric(15,2)` | partiellement NOT NULL | |
| `date_facture` | `date` | NOT NULL | |
| `date_echeance` | `date` | NULL | |
| `statut_chorus` | `varchar(50)` | NULL | `NON_TRANSMISE` par défaut |
| `date_transmission`, `chorus_numero_flux`, `chorus_statut_technique`, `chorus_date_statut`, `chorus_message_erreur` | — | NULL | métadonnées Chorus |
| `contrat_id` | `uuid` FK `contrats.id` ON DELETE SET NULL | NULL | lien éventuel |
| `imported_at`, `updated_at` | `timestamptz` | NULL | |

**Contrainte CHECK** : `statut_chorus IN ('NON_TRANSMISE','EN_COURS','TRANSMISE','ACCEPTEE','REJETEE','ERREUR')`.

**Index** : `client_karlia_id`, `date_facture`, `statut_chorus`.

**Distribution actuelle des statuts** :

```
NON_TRANSMISE : 13
TRANSMISE     :  1
ERREUR        :  1
```

> **Observation** : sur 15 factures importées, **1 seule** a été transmise avec succès via Chorus Pro, **1 a échoué** ; les 13 autres sont en attente. Cohérent avec le blocage Chorus Pro 403 noté en mémoire utilisateur ([[chorus_pro_blocage]]).

### 2.18 `transmissions_chorus` — Journal des transmissions

Source : `models.py:415-440` / DB live : **12 colonnes** (models : 11) / 4 lignes.

| Colonne | Type | Rôle |
|---|---|---|
| `id` | `uuid` `gen_random_uuid()` | PK |
| `facture_id` | `uuid` FK CASCADE | |
| `chorus_id_flux`, `chorus_id_facture` | `varchar(100)` | |
| `statut` | `varchar(50)` | `EN_ATTENTE` / `EN_COURS` / `SUCCES` / `ECHEC` / `ANNULE` (CHECK) |
| `code_retour`, `message_retour` | — | |
| `payload_json` | `jsonb` | payload envoyé |
| `reponse_json` | `jsonb` | réponse PISTE |
| `transmis_par` | `varchar(100)` | utilisateur déclencheur |
| `transmis_at` | `timestamptz` | défaut `now()` |
| **`is_test`** | `boolean` défaut `false` (DB only) | marqueur d'essai |

**Index** : `facture_id`, `statut`.

**Divergence #8** : la DB a une colonne **`is_test boolean DEFAULT false`** absente de `models.py`. Probablement pour distinguer les transmissions de test du mode qualification PISTE.

### 2.19 Synthèse des divergences `models.py` ↔ DB live

| # | Table | Divergence | Sens | Sévérité |
|---|---|---|---|---|
| 1 | `clients_cache` | `numero_client unique=True` en code, **pas** UNIQUE en DB | code stricter | basse |
| 2 | `indices_revision` | DB a UNIQUE sur `date_publication`, models non | DB stricter | basse |
| 3 | `contrats` | `client_karlia_id nullable=False` en code, NULL OK en DB | code stricter | moyenne |
| 4 | `commandes.pdf_devis` | `Text` en code (commentaire base64), **`bytea`** en DB | type mismatch | **élevée** |
| 5 | `commandes` dates | `DateTime(timezone=True)` en code, `timestamp without time zone` en DB | type mismatch | moyenne |
| 6 | `commande_lignes` | DB a **3 colonnes** remise (`discount_*`) absentes du code | colonnes DB orphelines | moyenne |
| 7 | `prestations` | DB a **5 colonnes** Google Calendar absentes du code | colonnes DB orphelines | **élevée** (code retiré, schéma dangling) |
| 8 | `transmissions_chorus` | DB a `is_test boolean` absent du code | colonne DB orpheline | basse |

**Cause racine probable** : `Base.metadata.create_all()` (`main.py:16`) ne fait **que créer** les tables manquantes ; il ne modifie jamais les colonnes existantes. Toutes les évolutions de schéma se sont faites manuellement sur la DB sans mise à jour du models.py, et inversement (changements de type au niveau ORM sans migration). **Alembic n'a jamais été câblé** alors qu'il est dans les requirements.

### 2.20 Diagramme texte des relations

```
                          ┌──────────────────────┐
                          │   indices_revision   │
                          └──────┬──────┬────────┘
                                 │      │           ┌─────────────────────┐
                                 │      └──────────►│  lots_facturation   │
                                 │                  └─────────────────────┘
              ┌──────────────────┴───┐
              ▼                      ▼
       ┌─────────────┐         ┌─────────────────┐
       │  contrats   │◄────────┤ plan_facturation│
       │ (self-ref)  │  CASCADE└─────────────────┘
       └──┬─────┬────┘
          │     │
          │ CASCADE     ┌──────────────────┐
          ├────────────►│ contrat_articles │
          │             └──────────────────┘
          │             ┌──────────────────┐
          ├────────────►│ documents_generes│
          │             └──────────────────┘
          │             ┌──────────────────┐
          ├SET NULL────►│   commandes      │◄───────┐
          │             └────┬─────┬───────┘        │
          │                  │     │  CASCADE       │FK formateur_id
          │                  │     ▼                │
          │                  │  ┌──────────────────┐│
          │                  │  │ commande_lignes  ││
          │                  │  └────────┬─────────┘│
          │                  │           │SET NULL  │
          │                  ▼           ▼          │
          │             ┌──────────────────────┐    │
          │             │     prestations      │────┘
          │             │  (FK formateur +     │
          │             │   agenda_formateur)  │
          │             └──────────────────────┘
          │                                         ┌──────────────┐
          ├SET NULL────►┌──────────────────┐       │  formateurs  │
                        │ factures_karlia  │       └──────┬───────┘
                        └────┬─────────────┘              │FK
                             │ CASCADE                    │
                             ▼                            ▼
                        ┌──────────────────────┐    ┌──────────────┐
                        │ transmissions_chorus │    │ utilisateurs │
                        └──────────────────────┘    └──────────────┘

       ┌────────────────┐   ┌──────────────────┐    ┌──────────────┐
       │ clients_cache  │   │  articles_cache  │    │  parametres  │
       │ (sync Karlia)  │   │  (sync Karlia)   │    │   (clé/val)  │
       └────────────────┘   └──────────────────┘    └──────────────┘
       
       Note: clients_cache.karlia_id ─── contrats.client_karlia_id
             relation déclarée en SQLAlchemy mais SANS FK SQL.
```

**Cardinalités principales** :
- Un **contrat** a 1-N `contrat_articles` (max 8 dont 1 principal), N `plan_facturation`, N `documents_generes`, N `factures_karlia` (souvent 0), 0-1 `contrat_parent` (avenants), 0-1 `commande`.
- Une **commande** a 1-N `commande_lignes`, 0-N `prestations`, 0-1 `contrat`, 0-1 `formateur`.
- Une **facture Karlia** a 0-N `transmissions_chorus`, 0-1 `contrat`.

### 2.21 Notes sur les cascades de suppression

| Relation | Mode | Conséquence |
|---|---|---|
| `contrat_articles.contrat_id` | CASCADE | suppression contrat = suppression articles |
| `plan_facturation.contrat_id` | CASCADE | idem |
| `documents_generes.contrat_id` | aucune (DEFAULT) | suppression contrat **bloquée** s'il a un document généré (mais en pratique : 1 ligne en prod) |
| `commandes.contrat_id` | SET NULL | suppression contrat ne supprime pas la commande |
| `factures_karlia.contrat_id` | SET NULL | idem |
| `commande_lignes.commande_id` | CASCADE | |
| `prestations.commande_id` | CASCADE | |
| `prestations.commande_ligne_id` | SET NULL | |
| `transmissions_chorus.facture_id` | CASCADE | |
| `utilisateurs.formateur_id` | aucune | suppression formateur **bloquée** si rattaché |

> **Risque opérationnel** : la combinaison `documents_generes` sans CASCADE + `utilisateurs.formateur_id` sans CASCADE = blocages potentiels lors de cleanups manuels.

---

## 3. API Backend (FastAPI)

### 3.1 Vue d'ensemble — montage des routers

`backend/app/main.py:33-46` monte **15 routers** sous le préfixe `/api/*` :

| Router | Préfixe | Fichier | Lignes | Endpoints |
|---|---|---|---|---|
| auth | `/api/auth` | `auth.py` | 70 | 2 |
| clients | `/api/clients` | `clients.py` | 452 | 7 |
| produits | `/api/produits` | `produits.py` | 75 | 2 |
| contrats | `/api/contrats` | `contrats.py` | 644 | 10 |
| facturation | `/api/facturation` | `facturation.py` | 253 | 4 |
| indices | `/api/indices` | `indices.py` | 154 | 7 |
| utilisateurs | `/api/utilisateurs` | `utilisateurs.py` | 166 | 5 |
| documents | `/api/documents` | `documents.py` | 121 | 7 |
| parametres | `/api/parametres` | `parametres.py` | 162 | 6 |
| audit | `/api/audit` | `audit.py` | 84 | 3 |
| commandes | `/api/commandes` | `commandes.py` | 462 | 14 |
| formateurs | `/api/formateurs` | `formateurs.py` | 223 | 5 |
| prestations | `/api/prestations` | `prestations.py` | 385 | 10 |
| chorus | `/api/chorus` (préfixé en interne) | `chorus.py` | 544 | 8 |
| dashboard | `/api/dashboard` | `dashboard.py` | 142 | 1 |
| **(racine main.py)** | `/api/*` | `main.py` | — | 3 (`/health`, `/synchro/statut`, `/synchro/lancer`) |

**Total : 3937 lignes de routers, ~94 endpoints HTTP.**

> **Particularité Chorus** : `chorus.py:22` déclare `router = APIRouter(prefix="/chorus")` **et** `main.py:46` monte `chorus.router` avec `prefix="/api"`. Le résultat final est `/api/chorus/...`. Tous les autres routers exposent leur préfixe via le `include_router(prefix="/api/<nom>")` sans doublon. C'est une incohérence stylistique mineure.

### 3.2 Authentification, JWT et gestion des droits

#### Endpoints

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| POST | `/api/auth/login` | public | login + password → JWT |
| GET | `/api/auth/me` | tout connecté | infos de l'utilisateur connecté |
| GET | `/api/utilisateurs/droits` | tout connecté | rôle + tableau de droits + formateur_id |
| GET | `/api/utilisateurs` | ADMIN | liste des comptes (avec nom_formateur résolu) |
| POST | `/api/utilisateurs` | ADMIN | crée un utilisateur (login/email/password/role) |
| PUT | `/api/utilisateurs/{id}` | ADMIN | modifie un utilisateur (interdit de se rétrograder soi-même) |
| DELETE | `/api/utilisateurs/{id}` | ADMIN | supprime un utilisateur (interdit de se supprimer soi-même) |

#### Mécanique

- **Hash mots de passe** : `bcrypt.checkpw()` côté login, `bcrypt.gensalt()` côté création (`auth.py:20`, `utilisateurs.py:12`).
- **JWT** : `python-jose`, algo HS256, signé avec `SECRET_KEY` du `.env` (`auth.py:24-26`).
- **Durée du token** : **24h codées en dur** dans `creer_token` (`auth.py:24`) ; le `Settings.ACCESS_TOKEN_EXPIRE_MINUTES=480` (8h) **n'est pas utilisé**. C'est une incohérence à corriger.
- **Payload JWT** : `{sub: login, role, id, formateur_id, exp}`.
- **Dépendance d'auth** : `get_current_user()` décode le token, recharge l'utilisateur en DB, vérifie `actif=True`. Réutilisée par tous les routers via `Depends(get_current_user)`.

#### Tableau des droits — `utilisateurs.py:17-22`

| Droit | ADMIN | GESTIONNAIRE | FORMATEUR | TECHNICIEN |
|---|---|---|---|---|
| contrats_ecriture | ✓ | ✓ | ✗ | ✗ |
| contrats_lecture | ✓ | ✓ | ✗ | ✓ |
| facturation | ✓ | ✓ | ✗ | ✗ |
| indices | ✓ | ✓ | ✗ | ✗ |
| commandes | ✓ | ✓ | ✗ | ✗ |
| parametres | ✓ | ✗ | ✗ | ✗ |
| utilisateurs | ✓ | ✗ | ✗ | ✗ |
| formateurs | ✓ | ✓ | ✗ | ✗ |
| toutes_prestations | ✓ | ✓ | ✗ | ✗ |

> **Observations sur les droits** :
> 1. Les droits sont **purement applicatifs** côté frontend (cf. § 5.3). Le backend ne vérifie systématiquement que `require_admin` pour les écritures sensibles (utilisateurs, paramètres). Beaucoup d'endpoints **n'ont aucune vérification de rôle**, par exemple `/api/contrats POST` ou `/api/facturation/lancer`.
> 2. Le rôle `FORMATEUR` n'a aucun droit listé → c'est volontaire (il accède uniquement à ses prestations via filtrage frontend), mais aucun garde-fou backend ne l'empêche d'appeler les endpoints sensibles s'il connaît leurs URLs.
> 3. Le rôle `TECHNICIEN` a `contrats_lecture` mais pas `contrats_ecriture` — pourtant l'endpoint `PUT /api/contrats/{id}` ne contrôle pas le rôle.

### 3.3 Contrats — `api/contrats.py`

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| GET | `/api/contrats` | aucun | liste paginée, filtres `statut`, `recherche`, `annee`, `familles`, `limit`/`offset` |
| GET | `/api/contrats/renouvellements` | aucun | contrats à renouveler dans un mois donné (filtre famille) |
| POST | `/api/contrats` | aucun | crée un contrat en `BROUILLON` + calcule prorata + génère plan de facturation |
| GET | `/api/contrats/{id}` | aucun | détail complet (articles + plan) |
| PUT | `/api/contrats/{id}` | aucun | modifie un contrat uniquement si `BROUILLON` ; remplace les articles, regénère le plan |
| POST | `/api/contrats/{id}/valider` | aucun | passe `BROUILLON → EN_COURS` après contrôles (articles, prorata validé) |
| DELETE | `/api/contrats/{id}` | aucun | supprime uniquement un `BROUILLON` |
| POST | `/api/contrats/{id}/terminer` | aucun | passe en `TERMINE` (motif facultatif) |
| POST | `/api/contrats/{id}/renouveler` | aucun | 3 modes : `SPONTANE` (prolonge 1 an + ajoute ligne plan), `NOUVEAU_CONTRAT` (archive + crée + copie articles + fusionne avenants), `FIN` |
| POST | `/api/contrats/renouveler-lot` | aucun | renouvellement en lot, modes `SPONTANE` ou `FIN` uniquement |

#### Effets de bord critiques

| Endpoint | Tables impactées | Commits DB | Appels externes |
|---|---|---|---|
| `POST /api/contrats` | `contrats`, `contrat_articles` (N), `plan_facturation` (N) | 1 commit final | aucun |
| `PUT /api/contrats/{id}` | `contrats`, `contrat_articles` (DELETE + N INSERT), `plan_facturation` (DELETE + N INSERT) | 1 commit final | aucun |
| `POST /api/contrats/{id}/renouveler` (NOUVEAU_CONTRAT) | crée 1 contrat + N articles + N plan ; archive l'ancien et **tous ses avenants** | 1 commit final | aucun |
| `POST /api/contrats/renouveler-lot` | itère et commit pour **chaque** contrat | 1 commit par contrat → **pas de transaction globale** | aucun |

> **Anti-pattern à noter** : `renouveler-lot` (`contrats.py:600-637`) fait un `db.commit()` par contrat. Si un contrat du lot échoue, ceux déjà traités sont déjà engagés en DB → impossible de retomber dans un état initial. La gestion d'erreur fait `db.rollback()` mais c'est tardif.

### 3.4 Commandes — `api/commandes.py`

| Méthode | Path | Description |
|---|---|---|
| POST | `/api/commandes/sync` | sync devis acceptés Karlia (delta ou full) |
| GET | `/api/commandes/stats` | compteurs (nouvelles, à_planifier, planifiées, contrats_à_créer, total) |
| GET | `/api/commandes/nouvelles` | liste statut `nouvelle` paginée |
| GET | `/api/commandes/a-planifier` | liste statut `a_planifier` paginée |
| GET | `/api/commandes/planifiees` | liste statut `planifiee` paginée |
| GET | `/api/commandes/terminees` | liste statut `deployee` paginée (note : alias backend → "terminées" front) |
| GET | `/api/commandes/contrats-a-creer` | nécessite_contrat=true et contrat_id=null |
| GET | `/api/commandes/{id}` | détail + lignes + formateur + comptes prestations |
| POST | `/api/commandes/{id}/valider` | `nouvelle → a_planifier` (si `type_traitement='a_planifier'`) **ou** `nouvelle → deployee` (si `'sans_planification'`) |
| POST | `/api/commandes/{id}/planifier` | `a_planifier → planifiee` + date/intervenant/notes |
| POST | `/api/commandes/{id}/terminer` | `* → terminee` (note : statut `terminee` jamais en DB actuellement) |
| POST | `/api/commandes/{id}/lier-contrat/{contrat_id}` | renseigne `commandes.contrat_id` |
| GET | `/api/commandes/{id}/pdf` | redirige vers `pdf_url` Karlia |
| POST | `/api/commandes/{id}/facturer` | crée une facture Karlia à partir des lignes de la commande |

#### Effets de bord et état

- Statuts utilisés en code : `nouvelle`, `a_planifier`, `planifiee`, `deployee`, `terminee`, `facturee`. **Pas de contrainte CHECK** côté DB (cf. § 2.13).
- **Incohérence terminologique** : `/terminees` retourne le statut **`deployee`** (code `commandes.py:267`), pas `terminee`. Le frontend appelle `/terminees` ce qui charge en réalité les commandes `deployee`. Le statut `terminee` est isolé (jamais affiché en liste).
- `POST /api/commandes/{id}/facturer` appelle directement `karlia.creer_facture()` et stocke `facture_karlia_id` / `facture_karlia_ref` sur la commande. Le statut Karlia créé est **`Brouillon` (id_status=1)** depuis le fix `34b2991` (puis `id_status=0` sur la branche non-mergée `fix/karlia-facture-brouillon-v2`, cf. § 9).

### 3.5 Facturation (révision Syntec) — `api/facturation.py`

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| GET | `/api/facturation/apercu/{annee}` | aucun | liste les plans `PLANIFIEE`/`CALCULEE` de l'année + indice OK + facturable (booléen "année future") |
| POST | `/api/facturation/calculer` | tout connecté | calcule les montants révisés Syntec (avec garde `valider_pre_calcul`) ; supporte montants manuels pour `DIGITECH` |
| POST | `/api/facturation/lancer` | tout connecté | **émet réellement les factures Karlia** ; supporte révision proportionnelle par article ; ajustement d'arrondi sur la dernière ligne |
| GET | `/api/facturation/lot/{lot_id}` | aucun | endpoint stub — retourne toujours `{statut: "TERMINE"}` |

#### Effets de bord — `POST /api/facturation/lancer`

```
1. lit chaque plan PLANIFIEE/CALCULEE filtré par plan_ids[]
2. récupère les articles du contrat (rang ASC)
3. construit N lignes, applique taux_revision sur unit_price
4. ajustement d'arrondi sur la dernière ligne (cumul == montant_ht_decimal)
5. appelle karlia.traitement_lot_factures(factures_a_emettre)  ← APPEL EXTERNE
6. pour chaque résultat Karlia :
   - succès → plan.statut = "EMISE", maj facture_karlia_id, montant_annuel_precedent
   - échec → plan.statut = "ERREUR", erreur_message
7. lance validation post-émission (valider_post_emission) avec log si ERREUR
8. commit après chaque plan
```

> **Garde-fous métier** : `valider_pre_calcul` bloque le calcul si l'indice n'est pas disponible ou si le contrat est en erreur. `valider_post_emission` ne bloque pas mais log les incohérences (montant Karlia ≠ montant attendu).

> **Anti-pattern** : `lot_id` est un UUID généré localement, **jamais persisté** (la table `lots_facturation` reste vide). Le GET `/lot/{lot_id}` retourne un statut fictif. Le mécanisme de "lot" est incomplet.

### 3.6 Chorus Pro — `api/chorus.py`

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| GET | `/api/chorus/test-connexion` | tout connecté | OAuth2 PISTE → ping company info |
| POST | `/api/chorus/synchro-factures` | tout connecté | importe les factures Karlia (type=4, status=2) dans `factures_karlia` |
| GET | `/api/chorus/factures` | tout connecté | liste paginée (filtres statut, recherche) |
| GET | `/api/chorus/factures/{id}` | tout connecté | détail facture |
| PUT | `/api/chorus/factures/{id}/siret` | tout connecté | met à jour le SIRET destinataire (override avant transmission) |
| POST | `/api/chorus/transmettre` | tout connecté | transmet 1-N factures vers Chorus Pro via PISTE |
| GET | `/api/chorus/factures/{id}/transmissions` | tout connecté | historique des tentatives |
| POST | `/api/chorus/rechercher-structure` | tout connecté | recherche destinataire par SIRET dans Chorus Pro |
| GET | `/api/chorus/statistiques` | tout connecté | comptage par statut + montant total |

#### Effets de bord — `POST /api/chorus/transmettre`

```
1. instancie ChorusProService avec params DB (chorus_*)
2. pour chaque facture_id :
   - vérifie pas déjà transmise
   - vérifie SIRET destinataire renseigné
   - crée TransmissionChorus(statut=EN_COURS)
   - bascule FactureKarlia.statut_chorus = EN_COURS
   - commit
   - appel service.soumettre_facture(...)  ← APPEL EXTERNE PISTE
   - mise à jour transmission + facture selon succès/échec
3. commit par facture (pas de transaction globale)
```

> **Mémoire utilisateur** : ce flux est **bloqué en production** par un 403 PISTE non résolu ([[chorus_pro_blocage]]). Une seule facture a transmis avec succès (cf. § 2.17).

### 3.7 Paramètres — `api/parametres.py`

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| GET | `/api/parametres/` | tout connecté | liste tous les paramètres + masque `karlia_api_key` (8 premiers chars + `...`) |
| PUT | `/api/parametres/karlia-api-key` | ADMIN | met à jour la clé API et l'instance `karlia` en mémoire |
| POST | `/api/parametres/tester-connexion` | tout connecté | teste la clé Karlia courante (`karlia.tester_connexion()`) |
| POST | `/api/parametres/vider-cache` | ADMIN | supprime `clients_cache` + `articles_cache` + reset stats synchro |
| GET | `/api/parametres/chorus` | tout connecté | renvoie les 8 paramètres Chorus, **masque** `chorus_client_secret` et `chorus_tech_password` (`••••••••`) |
| PUT | `/api/parametres/chorus` | ADMIN | met à jour les paramètres Chorus (ignore les valeurs `••••••••`) |

> **Sécurité — masquage** : le masquage est appliqué à la lecture mais le `valeur` brut reste accessible par n'importe quel utilisateur connecté via `GET /api/parametres/` pour les paramètres NON masqués (par exemple `chorus_client_id`). Le pattern n'est pas robuste : tout secret futur devra être explicitement ajouté à la liste de masquage.

### 3.8 Clients — `api/clients.py`

| Méthode | Path | Description |
|---|---|---|
| GET | `/api/clients` | liste cache local (défaut) ou Karlia direct via `source=karlia` |
| GET | `/api/clients/search` | recherche multi-termes dans cache (nom, numéro, ville, SIRET, email) |
| GET | `/api/clients/numero-suivant` | interroge Karlia pour prochain numéro client incrémental |
| POST | `/api/clients` | crée client dans Karlia + cache + tâche de fond `_creer_contact_karlia` |
| GET | `/api/clients/{karlia_id}/fiche` | détail enrichi : contrats actifs, terminés, factures |
| GET | `/api/clients/{karlia_id}` | détail cache local, fallback Karlia si absent |
| POST | `/api/clients/synchro` | resync complet cache depuis Karlia (boucle paginée) |

> **Effet de bord** : `POST /api/clients` lance une `BackgroundTask` qui rappelle l'API Karlia avec une `httpx.AsyncClient()` créée à la volée, **utilisant `settings.KARLIA_API_KEY` du `.env`** (et non la clé courante de l'instance `karlia` global). Si la clé a été modifiée via `PUT /api/parametres/karlia-api-key`, la tâche de fond utilisera quand même la clé du `.env`. C'est une incohérence (cf. § 7.1).

### 3.9 Produits / Articles — `api/produits.py`

| Méthode | Path | Description |
|---|---|---|
| GET | `/api/produits` | liste cache local (filtre actif=true) ou direct Karlia (`source=karlia`) |
| POST | `/api/produits/synchro` | resync complet articles depuis Karlia (jusqu'à 500) |

### 3.10 Indices Syntec — `api/indices.py`

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| GET | `/api/indices/familles` | aucun | renvoie le mapping `FAMILLES_CONTRAT` (cf. revision_service) |
| GET | `/api/indices` | aucun | liste indices (filtre mois, année), ordre annee DESC |
| GET | `/api/indices/courant` | aucun | dernier indice AOUT |
| POST | `/api/indices` | tout connecté | crée un indice (vérif doublon mois+année) |
| PUT | `/api/indices/{id}` | tout connecté | modifie valeur/commentaire |
| DELETE | `/api/indices/{id}` | tout connecté | supprime un indice |
| GET | `/api/indices/verifier/{famille}/{annee}` | aucun | vérifie disponibilité indices pour calcul (`verifier_indices_disponibles`) |

### 3.11 Documents — `api/documents.py`

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| GET | `/api/documents/contrat/{id}` | tout connecté | liste les documents d'un contrat |
| POST | `/api/documents/generer/{id}` | tout connecté | génère le `.docx` via `python-docx` (template de la famille du contrat) |
| GET | `/api/documents/telecharger/{doc_id}` | tout connecté | renvoie le `.docx` en `FileResponse` |
| GET | `/api/documents/modeles` | tout connecté | liste les modèles disponibles |
| POST | `/api/documents/modeles/upload` | ADMIN | upload `.docx` + désactive les modèles précédents du même type |
| PATCH | `/api/documents/modeles/{id}/activer` | ADMIN | bascule l'actif sur ce modèle (un seul actif par type) |
| DELETE | `/api/documents/modeles/{id}` | ADMIN | supprime fichier disque + ligne DB |

> **Effet de bord** : `POST /api/documents/modeles/upload` désactive **tous** les modèles du même `type_document` avant l'insertion. Les fichiers physiques précédents ne sont **pas supprimés** du disque — `storage/modeles/` peut accumuler des versions obsolètes.

### 3.12 Audit (cohérence métier) — `api/audit.py`

| Méthode | Path | Rôle requis | Description |
|---|---|---|---|
| GET | `/api/audit/contrat/{id}` | tout connecté | rapport `valider_contrat` (alertes ERREUR/WARNING/INFO) |
| GET | `/api/audit/facturation/{annee}` | tout connecté | rapport global année (filtre famille) |
| GET | `/api/audit/global` | tout connecté | audit complet des contrats EN_COURS, tri par sévérité |

> **Note** : cet endpoint produit le rapport métier visible dans la page Audit (frontend) ; il n'a pas d'effet de bord.

### 3.13 Dashboard — `api/dashboard.py` (nouveauté)

Un seul endpoint, ajouté au commit `2174640` (tag `v2.4.2`) :

```
GET /api/dashboard/stats
→ {
    total_contrats: int,                          # contrats EN_COURS
    ca_annuel_ht: float,                          # somme montant_annuel_ht
    a_renouveler_ce_mois: int,                    # date_fin dans le mois courant
    contrats_par_famille: [{code, label, total, montant_annuel_ht}],
    commandes_par_statut: {total, nouvelles, a_planifier, planifiees, facturees}
  }
```

> **Avant** : le dashboard appelait **plusieurs endpoints** (`/api/contrats?statut=EN_COURS`, `/api/contrats/renouvellements`, `/api/commandes/stats`) côté frontend. La refonte du commit `2174640` les a unifiés en un seul aller-retour serveur. Le mapping `FAMILLE_LABELS` est **codé en dur** dans `dashboard.py:19-28` — ces libellés devraient venir d'une table ou d'un fichier de config.

### 3.14 Formateurs — `api/formateurs.py`

| Méthode | Path | Description |
|---|---|---|
| GET | `/api/formateurs?actif_only=true` | liste avec compteurs (nb_commandes, nb_prestations_a_planifier) |
| POST | `/api/formateurs` | crée un formateur (email unique) |
| GET | `/api/formateurs/{id}` | détail |
| PUT | `/api/formateurs/{id}` | modifie (tout sauf id) |
| DELETE | `/api/formateurs/{id}` | supprime (cf. § 2.21 sur les FK bloquantes) |

> **Pas de garde-fou rôle** sur ces endpoints — n'importe quel utilisateur connecté peut créer/modifier/supprimer un formateur.

### 3.15 Prestations — `api/prestations.py`

| Méthode | Path | Description |
|---|---|---|
| GET | `/api/prestations` | liste avec filtres formateur_id, commande_id, statut |
| GET | `/api/prestations/formateur/{id}` | prestations d'un formateur (utilisée par les vues "Mes prestations") |
| POST | `/api/prestations` | crée une prestation (commande_id obligatoire) |
| POST | `/api/prestations/from-commande/{id}` | **crée automatiquement** N prestations depuis les lignes de la commande (1 par ligne) |
| GET | `/api/prestations/{id}` | détail |
| PUT | `/api/prestations/{id}` | modification |
| POST | `/api/prestations/{id}/planifier` | passe `a_planifier → planifiee` + date/heures/lieu ; **effet de bord** : passe la commande à `planifiee` si toutes ses prestations le sont |
| POST | `/api/prestations/{id}/realiser` | passe `planifiee → realisee` ; **effet de bord** : passe la commande à `deployee` si toutes ses prestations sont `realisee` |
| DELETE | `/api/prestations/{id}` | supprime |
| POST | `/api/prestations/reattribuer-commande/{commande_id}?formateur_id=X` | réattribue toutes les prestations d'une commande à un autre formateur (+ met à jour `commandes.formateur_id`) |

> **Cascade implicite — sensible** : `planifier_prestation` et `realiser_prestation` ont des effets de cascade sur le statut de la commande mère. Si une seule prestation est créée et planifiée, la commande bascule à `planifiee`. Cette mécanique est documentée nulle part hors du code.

### 3.16 Routes globales — `main.py`

| Méthode | Path | Description |
|---|---|---|
| GET | `/api/health` | `{status: "ok", version: "1.0.0"}` — endpoint de healthcheck |
| GET | `/api/synchro/statut` | lit `derniere_synchro` + `synchro_stats` dans la table `parametres` |
| POST | `/api/synchro/lancer` | déclenche `synchro_karlia()` à la demande |

> **Note de versioning** : `version` du FastAPI est `"1.0.0"` (`main.py:18`) — **pas synchronisée** avec les tags git `v2.4.6`.

### 3.17 Synthèse — effets de bord transverses

| Endpoint | Tables impactées (E = écriture) | Appels externes | Garde-fou métier |
|---|---|---|---|
| `POST /api/contrats` | `contrats` (E), `contrat_articles` (E), `plan_facturation` (E) | — | unicité numéro_contrat, date_fin > date_debut |
| `PUT /api/contrats/{id}` | idem + DELETE total des articles/plan | — | seul `BROUILLON` modifiable |
| `POST /api/contrats/{id}/valider` | `contrats` (E `statut`) | — | articles existent, prorate_validated si annee1 |
| `POST /api/contrats/{id}/renouveler NOUVEAU_CONTRAT` | crée nouveau contrat + articles + plan ; archive ancien + avenants | — | nouveau_numero obligatoire |
| `POST /api/contrats/renouveler-lot` | itère + N commits | — | mode SPONTANE/FIN seulement |
| `POST /api/commandes/sync` | `commandes` (E), `commande_lignes` (E) | **GET Karlia /documents**, **GET /devis_detail** | quota 80 req/min |
| `POST /api/commandes/{id}/facturer` | `commandes` (E facture_karlia_id) | **POST Karlia /documents** | client_karlia_id requis, statut deployee requis |
| `POST /api/facturation/calculer` | `plan_facturation` (E `montant_revise_ht`, `taux_revision`, `statut`) | — | indice disponible, montant_precedent connu |
| `POST /api/facturation/lancer` | `plan_facturation` (E `statut`, `facture_karlia_*`) | **POST Karlia /documents** par contrat | annee ≤ annee_courante |
| `POST /api/chorus/synchro-factures` | `factures_karlia` (E) | **GET Karlia /documents** filtré type=4 | — |
| `POST /api/chorus/transmettre` | `transmissions_chorus` (E), `factures_karlia` (E `statut_chorus`) | **POST PISTE /factures** | SIRET destinataire requis |
| `POST /api/parametres/karlia-api-key` | `parametres` (E) | — | ADMIN |
| `POST /api/parametres/vider-cache` | `clients_cache` (DEL), `articles_cache` (DEL), `parametres` (DEL) | — | ADMIN |
| `POST /api/documents/generer/{id}` | `documents_generes` (E), fichier disque `storage/documents_generes/` | — | client existe |
| `POST /api/documents/modeles/upload` | `modeles_documents` (E), fichier disque `storage/modeles/` | — | ADMIN, `.docx` uniquement |
| `POST /api/clients` | `clients_cache` (E), `parametres` lecture indirecte | **POST Karlia /customer-suppliers**, **POST Karlia /contacts** en background | — |
| `POST /api/synchro/lancer` | `clients_cache` (E), `articles_cache` (E), `parametres` (E `derniere_synchro`) | **GET Karlia paginé (clients + produits)** | — |

> **Observation transverse** : **aucun endpoint d'écriture n'utilise de transaction explicite**. Tous reposent sur les `db.commit()` finaux et la session par requête. En cas d'erreur en milieu d'opération multi-étapes (ex : création contrat avec 8 articles puis échec sur la 6e ligne), la session reste sale jusqu'à un `db.rollback()` qui n'est pas systématique. À durcir dans la refonte.

---

## 4. Services métier backend

`backend/app/services/` contient **7 fichiers actifs** (un huitième, `google_calendar_service.py`, a été supprimé récemment — cf. § 9) pour un total de **2057 lignes** :

| Service | Lignes | Rôle |
|---|---|---|
| `karlia_service.py` | 303 | Client Karlia v2 (clients, produits, factures) |
| `karlia_devis_service.py` | 507 | Synchronisation devis acceptés Karlia (avec rate-limit) |
| `chorus_service.py` | 373 | Client PISTE / Chorus Pro (OAuth2 + soumission facture) |
| `contrat_service.py` | 193 | Calculs métier contrats (prorata, plan, numéro client) |
| `revision_service.py` | 162 | Calculs Syntec et règles de famille |
| `validation_service.py` | 268 | Garde-fous métier (pré-calcul, pré-émission, post-émission, audit) |
| `document_service.py` | 251 | Génération de contrats Word par publipostage |
| ~~`google_calendar_service.py`~~ | — | **Retiré récemment** (-44 lignes diff phase 0) |

### 4.1 `karlia_service.py` — Client Karlia v2

**Singleton global** : `karlia = KarliaService()` (`karlia_service.py:303`). Instance unique réutilisée par tous les routers via `from app.services.karlia_service import karlia`.

#### Méthodes publiques

| Méthode | Endpoint Karlia | Usage |
|---|---|---|
| `tester_connexion()` | `GET /company` | écran Paramètres + `POST /api/parametres/tester-connexion` |
| `lister_clients(recherche, limit, offset)` | `GET /customers` | sync clients + recherche live |
| `obtenir_client(karlia_id)` | `GET /customers/{id}` | fallback fiche client |
| `creer_client(data)` | `POST /customers` | `POST /api/clients` |
| `dernier_numero_client()` | `GET /customers?limit=500` | génération numéro suivant — **récupère 500 clients pour calculer le max** ⚠️ |
| `lister_produits(recherche, limit=200)` | `GET /products` | sync articles + recherche |
| `obtenir_produit(karlia_id)` | `GET /products/{id}` | non-utilisé en pratique |
| `obtenir_prix_vente(karlia_id)` | `GET /products/{id}/sell-price` | non-utilisé en pratique |
| `lister_types_documents()` | `GET /documents?limit=1` | utilitaire de debug |
| `creer_facture(client_karlia_id, lignes, ref, date_echeance, montant_ht, description)` | `POST /documents` | facturation Syntec + facturation commande |
| `obtenir_document(doc_id)` | `GET /documents/{id}` | utilitaire |
| `lister_templates_documents()` | `GET /documents/templates` | utilitaire |
| `traitement_lot_factures(factures, delai=0.8s)` | itère `creer_facture` | exclusivement `POST /api/facturation/lancer` |

#### Configuration et clé API

```python
class KarliaService:
    def __init__(self):
        self.api_key = settings.KARLIA_API_KEY    # depuis .env
        # ...
```

Mais à plusieurs endroits l'instance est **modifiée à chaud** :
- `main.py:163-164` (au startup) : si une clé est trouvée en table `parametres`, surcharge `karlia.api_key`
- `parametres.py:47` (`PUT /api/parametres/karlia-api-key`) : surcharge `karlia.api_key`
- `main.py:60-62` (avant chaque synchro) : recharge depuis la DB

> **Anti-pattern** : la clé est lue à 3 endroits différents (settings, DB via main.py, DB via parametres.py). En outre, `karlia_devis_service.py:45` et `clients.py:438` ne consultent pas l'instance globale `karlia` et lisent la clé séparément. **Une refonte devrait centraliser la lecture en un service d'accès unique** (cf. § 8).

#### Gestion des erreurs

`_handle_response()` (`karlia_service.py:60`) :
- 200 → JSON
- 401 → `KarliaError(401, "Clé API Karlia invalide ou expirée")`
- 429 → `KarliaError(429, "Quota API Karlia dépassé (100 req/min)")` — **sans retry** dans ce service ; le retry n'existe que dans `karlia_devis_service.py`
- autre → `KarliaError(status, "Erreur Karlia sur {endpoint}", detail=…)`

#### Mapping TVA — `creer_facture`

```python
if tva >= 20: id_vat = "1"
elif tva >= 10: id_vat = "2"
elif tva >= 5:  id_vat = "3"
else:           id_vat = "4"   # 0% / exonéré
```

Mapping codé en dur : `1=20%`, `2=10%`, `3=5.5%`, `4=0%`. Pas de TVA intermédiaire (8.5%, 2.1%). Si Karlia ajoute d'autres taux, ce mapping doit être maintenu manuellement.

#### Payload facture Karlia (validé en production)

```json
{
  "id_customer": 123,
  "id_type": 4,
  "id_status": 1,            // Brouillon — à valider manuellement
  "reference": "CO-2025-001",
  "date": "21/05/2026",
  "date_end": "01/06/2026",
  "description": "Facturation annuelle — Contrat CO-2025-001",
  "products_list": [
    {"id_product": "K42", "price_without_tax": 1500.0, "quantity": 1, "id_vat": "1"}
  ]
}
```

> **Évolution récente** (commits `34b2991` et `ed3f9d5`) : le `id_status` est passé de `2` (Envoyée — facturait directement) à `1` (Brouillon — validation manuelle), puis à `0` sur la branche `fix/karlia-facture-brouillon-v2` **non mergée**. La logique courante sur main = `id_status=1`. Cf. § 9.

> **Rate-limit traitement_lot_factures** : `delai_entre_requetes=0.8s` codé en dur (`karlia_service.py:249`), ≈ 75 req/min. Aucune lecture de `settings.KARLIA_MAX_REQUESTS_PER_MINUTE`. **Pas de retry sur 429** — un quota dépassé fait échouer la facture (passée à `statut=ERREUR` côté plan).

### 4.2 `karlia_devis_service.py` — Synchronisation devis Karlia

**Singleton global** : `karlia_devis_service = KarliaDevisService()` (`karlia_devis_service.py:507`).

**Particularité** : ce service **ne s'appuie pas sur `karlia`** (l'instance globale du § 4.1). Il refait sa propre couche HTTP avec retry custom, sa propre lecture de clé API en DB, sa propre instance `httpx.AsyncClient()`. **Duplication de code**.

#### Constantes métier — `karlia_devis_service.py:33-39`

```python
KARLIA_TYPE_DEVIS              = 1   # type document = Devis
KARLIA_TYPE_BON_COMMANDE       = 2   # documentaire (logs uniquement)
KARLIA_STATUS_DEVIS_ACCEPTE    = 2   # status Karlia = Accepté
KARLIA_FIELD_TRAITE_ID         = "66505"  # custom field "Traité" sur opportunité
RATE_LIMIT_RETRY_BACKOFFS      = [5, 15, 30]   # backoffs successifs sur 429
```

#### Méthodes publiques

| Méthode | Description |
|---|---|
| `sync_devis_acceptes(db, force_full=False)` | sync delta (par défaut) ou full ; appelé par `POST /api/commandes/sync` |
| `get_devis_acceptes(depuis_date)` | liste paginée `GET /documents?type=1&id_status=2` |
| `get_devis_detail(document_id)` | `GET /documents/{id}` — récupère le détail (download_url, products_list) |
| `get_customer_detail(customer_id)` | `GET /customers/{id}` — enrichit infos client |
| `_is_opportunity_traitee(client, opportunity_id)` | lit custom field 66505 sur `GET /opportunities/{id}` |
| `_marquer_opportunity_traitee(client, opportunity_id)` | `POST /opportunities/{id}/custom-fields/66505 {field_value: 1}` |
| `_get_with_retry(client, url, params, context)` | helper HTTP avec retry **5s → 15s → 30s** sur 429 |

#### Flow de synchronisation `sync_devis_acceptes`

```
1. Lit derniere_synchro_devis dans parametres (sauf si force_full=True)
2. GET /documents?type=1&id_status=2 paginé (limit=100, sleep 0.8s entre pages)
3. Pour chaque devis :
   a. sleep settings.KARLIA_SYNC_SLEEP_SECONDS (défaut 1.2s) en TÊTE d'itération
   b. Rejeter si id_type != 1 (défense en profondeur)
   c. Si has_opportunity : vérifier si opportunité déjà Traitée (skip si oui + nouveau devis)
   d. Si commande existe en base : MAJ (méthode _update_commande)
   e. Sinon : CRÉATION (méthode _create_commande) + marquer opportunité Traitée
4. Sauve derniere_synchro_devis = now
5. Retourne compteurs : nouveaux_devis, devis_mis_a_jour, devis_ignores, opportunites_marquees,
   pdf_url_renseigne, pdf_url_absent, erreurs[]
```

#### Effets de bord critiques

- **Marquage automatique des opportunités côté Karlia** comme "Traité" après import → évite la réimportation. Effet de bord externe **non réversible** sans intervention manuelle dans Karlia.
- Création de `commandes` + `commande_lignes` (CASCADE) en DB locale.
- Mise à jour de `parametres.derniere_synchro_devis`.

#### Historique (cohérent avec le commit log)

Le module a connu un **incident de production le 2026-05-20** : 108 devis sync en rafale, quota Karlia atteint, les `get_devis_detail()` ont été silencieusement avalés en 429, 106 commandes créées avec `pdf_url=None`. Le rattrapage a été fait via `scripts/rattrapage_pdf_url.py` (commit `8cf0cf3`), puis la prévention via les commits `6e4e714` (sleep 1.2s + retry) et `99c0d9b` (fix nom paramètre `id_type` → `type`). Diagnostic complet dans `docs/DIAGNOSTIC_PDF_COMMANDES.md`.

> **Anti-pattern** : `_create_commande` exécute du SQL brut (`db.execute(text("UPDATE commandes SET karlia_opportunity_id = …"))` `karlia_devis_service.py:350-353`) au lieu de set l'attribut SQLAlchemy. Probablement parce que `karlia_opportunity_id` a été ajouté tardivement à la table sans être déclaré dans le modèle au moment du commit — c'est aujourd'hui dans le modèle (`models.py:305`) donc le raw SQL est devenu inutile. **Code à simplifier**.

> **Lecture seule de la clé API** : `KarliaDevisService.__init__` lit `karlia_api_key` **une seule fois au démarrage** du conteneur (`karlia_devis_service.py:45`). Si l'admin met à jour la clé via `PUT /api/parametres/karlia-api-key`, ce service ne la prendra pas en compte tant que le conteneur n'aura pas redémarré. Bug latent.

### 4.3 `chorus_service.py` — Client PISTE / Chorus Pro

#### URLs hardcodées (`chorus_service.py:15-19`)

```python
PISTE_SANDBOX_OAUTH = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
PISTE_PROD_OAUTH    = "https://oauth.piste.gouv.fr/api/oauth/token"
CHORUS_SANDBOX_API  = "https://sandbox-api.piste.gouv.fr/cpro/factures/v1"
CHORUS_PROD_API     = "https://api.piste.gouv.fr/cpro/factures/v1"
```

Sélection sandbox vs prod via `mode_qualification` (paramètre DB `chorus_mode_qualification`).

#### Méthodes publiques

| Méthode | Endpoint PISTE | Description |
|---|---|---|
| `_get_access_token()` | `POST /api/oauth/token` | OAuth2 client_credentials + Basic Auth |
| `tester_connexion()` | OAuth seul | bool |
| `rechercher_structure_destinataire(siret)` | `POST /rechercher/structures` | recherche par SIRET |
| `consulter_structure(id_structure)` | `POST /consulter/structure` | détails structure |
| `rechercher_services_structure(id_structure)` | `POST /rechercher/services` | services d'une structure |
| `soumettre_facture(destinataire_siret, …, lignes, montant_ht, …)` | `POST /soumettre` | **transmet une facture** |
| `consulter_statut_facture(id_facture)` | `POST /consulter/facture` | suivi statut |
| `rechercher_factures_emises(date_debut, date_fin, statut)` | `POST /rechercher/factures/fournisseur` | liste émises |

#### Mécanique OAuth

```python
async def _get_access_token(self) -> str:
    if self._access_token and self._token_expires:
        if datetime.now() < self._token_expires:
            return self._access_token              # cache mémoire
    credentials = base64.b64encode(f"{tech_username}:{tech_password}".encode()).decode()
    response = await client.post(self.oauth_url,
        data={"grant_type": "client_credentials", "scope": "openid"},
        headers={"Authorization": f"Basic {credentials}"},
        auth=(self.client_id, self.client_secret))
    # expires_in retour - 300s de marge
```

> **Particularité PISTE** : authentification à deux niveaux — `auth=(client_id, client_secret)` (HTTP Basic standard pour OAuth2) **plus** un `Authorization: Basic {tech_username:tech_password}` **dans le header**. Cette combinaison non standard est ce qui distingue PISTE Chorus Pro de l'OAuth2 classique. C'est probablement la source du blocage 403 noté en mémoire utilisateur ([[chorus_pro_blocage]]).

#### Payload facture Chorus Pro

Structure très lourde (`chorus_service.py:264-309`) avec `modeDepot`, `numeroFactureSaisi`, `destinataire`, `fournisseur`, `cadreDeFacturation`, `references`, `lignePoste[]`, `ligneRecapitulatifTVA[]`, `montantTotal`. **Champ `typeTva: "TVA_SUR_DEBIT"` codé en dur** — non configurable, problématique si la société passe en TVA sur encaissements.

#### Factory

```python
def get_chorus_service_from_params(params: dict) -> Optional[ChorusProService]:
    required = ['chorus_client_id', 'chorus_client_secret', 'chorus_tech_username',
                'chorus_tech_password', 'chorus_siret_emetteur']
    ...
```

Retourne `None` si un paramètre obligatoire est manquant ; `_get_chorus_service(db)` côté router lève alors une `HTTPException(400, "Configuration Chorus Pro incomplète…")` (`chorus.py:97`).

### 4.4 `contrat_service.py` — Logique métier contrats

| Fonction | Rôle | Notes |
|---|---|---|
| `calculer_prorata(date_debut, montant_annuel_ht, demi_mois=False)` | calcule prorata an1 selon la règle "≤15 du mois ou >15" | retourne dict `{prorate, nb_mois, montant_ht, detail, …}` |
| `calculer_nombre_annees(date_debut, date_fin)` | `date_fin.year - date_debut.year + 1` | **calcul approximatif** — ne tient pas compte du jour/mois |
| `generer_plan_facturation(contrat_id, date_debut, date_fin, montant_annuel_ht, prorata)` | génère N lignes (1 par année civile) | 1er janvier sauf an1 prorata |
| `calculer_montant_revise(montant_an1, indice_recent, indice_ancien)` | formule simple Syntec ; **non utilisée** (recalcul dupliqué dans `revision_service`) | code mort à supprimer |
| `generer_numero_client(nom, dernier_numero)` | 3 lettres du nom + numéro 3 chiffres (ex `DUM048`) | ignore les mots-clés `LE/LA/SARL/SAS/…` |
| `calculer_statut_renouvellement(contrats_actifs, mois_alerte=1)` | ajoute `jours_avant_echeance` et `a_renouveler` aux contrats | **non utilisée** par le code actif (le router `renouvellements` requête directement) |

#### Règle prorata détaillée

```
date_debut.day ≤ 15  →  facturation dès le mois courant (mois_debut = date_debut.month)
date_debut.day > 15  →  facturation dès le mois suivant (mois_debut = date_debut.month + 1)
nb_mois             =  13 - mois_debut
montant_prorate     =  montant_annuel_ht × nb_mois / 12, arrondi à 0.01
option demi_mois    →  bonus = montant_annuel_ht / 24
cas spécial         →  date_debut == 01/01 ET pas de demi_mois → année complète, pas de prorata
```

> **Anti-pattern** : `calculer_nombre_annees` ne tient pas compte des dates exactes. Un contrat 01/03/2026 → 28/02/2027 retourne **2 années** (2026 et 2027) alors qu'en jours c'est 1 an pile. Le plan de facturation génère 2 lignes (an1 proraté + an2 année pleine). Question ouverte : est-ce bien le comportement attendu ?

### 4.5 `revision_service.py` — Calculs Syntec

#### Familles et règles

```python
FAMILLES_CONTRAT = [
  {"code": "COSOLUCE",       "revision": "SYNTEC_AOUT"},     # Cosoluce
  {"code": "CANTINE",        "revision": "SYNTEC_OCTOBRE"},  # Cantine de France
  {"code": "DIGITECH",       "revision": "MANUELLE"},        # Digitech
  {"code": "MAINTENANCE",    "revision": "SYNTEC_AOUT"},
  {"code": "ASSISTANCE_TEL", "revision": "SYNTEC_AOUT"},
  {"code": "KIWI_BACKUP",    "revision": "AUCUNE"},
  {"code": "AUTRE",          "revision": "AUCUNE"},
]
```

> **Note** : la famille `CITYWEB` apparaît dans `dashboard.py:27` (label) mais **n'est pas dans `FAMILLES_CONTRAT`** ici → incohérence. À vérifier si c'est une famille à supprimer ou à ajouter.

#### Formule Syntec — `calculer_revision`

```
Pour facturer l'année N :
  indice_ref  = indice mois M de l'année N-2     (ex: Août 2024 pour 2026)
  indice_new  = indice mois M de l'année N-1     (ex: Août 2025 pour 2026)
  taux        = indice_new / indice_ref          (arrondi 6 décimales HALF_UP)
  montant_N   = montant_N-1 × taux               (arrondi 0.01 HALF_UP)
```

**Garde-fous** :
- `regle == "AUCUNE"` → retourne `montant_precedent` inchangé, `taux=1.000000`
- `regle == "MANUELLE"` → exige `nouveau_montant_manuel` ; calcule `taux` rétrospectivement
- `indice_ref` ou `indice_new` absent → `{ok: False, message: "Indice Syntec {mois} {annee} manquant"}`

> **Évolution historique** (commentaire `revision_service.py:78`) : la formule a été corrigée d'un usage `N-1 et N` vers `N-2 et N-1`. Avant correction, on facturait 2026 avec `Août 2025 / Août 2026` (incohérent car l'indice 2026 n'existe pas encore au moment de facturer 2026). C'est un bug critique passé silencieusement — voir si des factures émises avant correction sont à recalculer.

### 4.6 `validation_service.py` — Garde-fous métier

Quatre fonctions principales, chacune retourne `{ok: bool, alertes: [_alerte(niveau, code, message, detail)]}` :

| Fonction | Quand l'appeler | Niveaux d'alerte |
|---|---|---|
| `valider_contrat(db, contrat)` | écran Audit | ERREUR si article rang 0 manquant, sans `id_product`, plan vide, doublon année plan, facture EMISE sans karlia_id, taux incohérent |
| `valider_pre_calcul(db, plan, nouveau_montant?)` | avant `POST /api/facturation/calculer` | ERREUR si déjà EMISE, indices manquants, montant manuel requis pour Digitech, montant_référence nul |
| `valider_pre_emission(db, plan)` | avant `POST /api/facturation/lancer` | ERREUR si déjà EMISE, statut PLANIFIEE (non calculée), montant nul, article principal manquant ou sans id_product, client_karlia_id manquant ; WARNING si taux ∉ [0.5, 2.0] |
| `valider_post_emission(plan, resultat_karlia)` | après `karlia.creer_facture()` | ERREUR si Karlia a répondu succès sans id, statut non mis à jour, id Karlia non persisté |
| `auditer_annee_facturation(db, annee)` | écran Audit | rapport global pour une année |

> **Observation** : `valider_pre_emission` n'est **pas appelée** par `POST /api/facturation/lancer` aujourd'hui — seul `valider_pre_calcul` et `valider_post_emission` le sont. Il y a donc un trou : on ne vérifie pas les pré-conditions au moment d'émettre, on suppose qu'elles ont été validées lors du calcul. **Risque** si calcul et émission ne sont pas faits dans la même session.

### 4.7 `document_service.py` — Génération de contrats Word

#### Constantes

```python
STORAGE_DIR   = Path("/app/storage")            # bind-mount hôte
MODELES_DIR   = STORAGE_DIR / "modeles"
DOCUMENTS_DIR = STORAGE_DIR / "documents_generes"

FAMILLE_MODELE = {                              # mapping famille → fichier par défaut
    "COSOLUCE":       "Modele_Contrat_Cosoluce_et_Annexes.docx",
    "CANTINE":        "Modele_Contrat_Cantine_de_France.docx",
    "MAINTENANCE":    "Modele_Contrat_Maintenance_Systeme.docx",
    "ASSISTANCE_TEL": "Modele_Contrat_Assistance_Cityweb.docx",
}
```

> **Familles non couvertes** : `DIGITECH`, `KIWI_BACKUP`, `AUTRE`, `CITYWEB` n'ont **pas de modèle Word défini**. Si on génère un contrat de ces familles sans modèle uploadé en table `modeles_documents`, l'endpoint renvoie `{"success": False, "error": "Aucun modèle disponible…"}`.

#### Mécanique de publipostage

```
1. _trouver_modele(famille, db) :
   - cherche modeles_documents.actif=true le plus récent pour type CONTRAT_{famille}
   - sinon fallback FAMILLE_MODELE[famille] dans /app/storage/modeles/
2. Construit dict variables (27 champs) à partir du contrat + client cache
3. Ouvre le .docx avec python-docx
4. _traiter_document() :
   - pour chaque paragraphe / tableau / cellule / sous-tableau / en-tête
   - remplace «AliasName» (caractères \xab et \xbb = guillemets français) par la valeur
   - 67 alias mappés vers 27 valeurs canoniques (NomClient, AdresseClient, …)
   - regex _RE_REST supprime tout «...» non remplacé (nettoyage placeholders inconnus)
5. Sauve dans /app/storage/documents_generes/ avec nom Contrat_{numero}_{client}_{YYYYMMDD}.docx
6. Insère ligne dans documents_generes avec variables_json (audit)
```

#### Alias supportés

27 champs canoniques, 67 alias au total. Exemples : `NomClient` accepte aussi `NomSite` ; `DateDoc` accepte `DateDuJour` ou `DatduJour` (faute de frappe historique). Cette table d'alias est très spécifique aux modèles Word legacy de l'entreprise — **à figer dans un schéma de modèle moderne** (ex : Jinja2 ou champs de fusion Word standard).

> **Observation** : seul **1 document** est dans `documents_generes` (cf. § 2.9). La fonctionnalité existe mais n'est quasiment pas utilisée. Question ouverte : à conserver, à reprendre, ou à supprimer pour la refonte ?

### 4.8 `google_calendar_service.py` — Service supprimé

Ce fichier **n'existe plus** dans `backend/app/services/` (cf. § 1.9 — l'arbre du projet). Le diff phase 0 montre `-44 lignes`. Il a été retiré dans la période 18/05 → 21/05.

**Conséquences** :
- La table `prestations` garde **5 colonnes orphelines** liées à Google Calendar (§ 2.15).
- La table `formateurs` garde le champ `email_google` (§ 2.16) — initialement pour authentifier vers Google.
- Aucun appel à un quelconque service Google n'est plus présent dans le code backend.

> **Question pour la refonte** : faut-il (a) **purger** les colonnes orphelines en DB, (b) **réactiver** le service avec un nouveau client Google, ou (c) basculer vers un autre fournisseur (Outlook, Apple) ?

### 4.9 Dépendances externes par service

| Service | API externe | Tables DB lues/écrites | Fichiers locaux |
|---|---|---|---|
| `karlia_service` | Karlia v2 (`/customers`, `/products`, `/documents`, `/company`) | — | — |
| `karlia_devis_service` | Karlia v2 (`/documents`, `/customers`, `/opportunities`) | E: `commandes`, `commande_lignes`, `parametres` | — |
| `chorus_service` | PISTE OAuth2 + Chorus Pro `/cpro/factures/v1` | — | — |
| `contrat_service` | — | — | — |
| `revision_service` | — | L: `indices_revision` | — |
| `validation_service` | — | L: `contrats`, `plan_facturation`, `indices_revision` | — |
| `document_service` | — | L: `modeles_documents`, contrats, clients_cache · E: `documents_generes` | R: `storage/modeles/*.docx` · W: `storage/documents_generes/*.docx` |

### 4.10 Anti-patterns et redondances

| # | Anti-pattern | Impact | Priorité refonte |
|---|---|---|---|
| 1 | Clé API Karlia lue à **5 endroits** (`settings`, `karlia.__init__`, `karlia_devis_service.__init__`, `main.py:163`, `parametres.py:47`, `clients.py:438`) | clé désynchronisée → 401/403 silencieux | **élevée** |
| 2 | `karlia_devis_service` lit la clé **une seule fois** au démarrage container | bug latent | élevée |
| 3 | `karlia_service.creer_facture` mappe la TVA à 4 codes uniquement (1/2/3/4) | TVA intermédiaires non couvertes | moyenne |
| 4 | `karlia_service.traitement_lot_factures` : aucun retry sur 429 | quota atteint = échec définitif | moyenne |
| 5 | `karlia_devis_service._create_commande` utilise `db.execute(text("UPDATE …"))` pour `karlia_opportunity_id` alors que la colonne est aujourd'hui dans le modèle | code obsolète | basse |
| 6 | `contrat_service.calculer_montant_revise` et `revision_service.calculer_revision` font le même calcul de manière différente | code dupliqué | basse |
| 7 | `contrat_service.calculer_statut_renouvellement` jamais appelée | code mort | basse |
| 8 | Famille `CITYWEB` dans `dashboard.py` mais pas dans `FAMILLES_CONTRAT` | incohérence visuelle | basse |
| 9 | `validation_service.valider_pre_emission` jamais appelée par `/api/facturation/lancer` | trou de garde-fou | **élevée** |
| 10 | `chorus_service` : `typeTva: "TVA_SUR_DEBIT"` codé en dur | non configurable | moyenne |
| 11 | `chorus_service` : double authentification (Basic + auth=) non documentée → suspect du blocage 403 | bloque la production | **élevée** |
| 12 | Aucune transaction explicite, tous les commits intermédiaires en milieu de boucle | états incohérents possibles | élevée |
| 13 | `google_calendar_service` retiré mais schéma DB intact | confusion | moyenne |

---

## 5. Frontend React

> **Source de référence canonique** : `~/contrats/contrats-ui-src/src/` (versionnée). Le dossier `~/contrats/contrats-ui/build/` est le build embarqué dans l'image nginx via `Dockerfile.frontend`. **Ne pas modifier `~/contrats-ui/`** (en dehors du projet, hérité de l'historique — cf. § 1.9).

### 5.1 Structure du dossier `src/`

```
contrats-ui-src/src/
├── App.js                 (91 lignes)   — routes + auth provider + toaster
├── index.js               — bootstrap React 19
├── index.css              — Tailwind base
├── components/
│   └── Layout.js          (128 lignes)  — sidebar, menu, header utilisateur
├── context/
│   └── AuthContext.js     (87 lignes)   — user, droits, login/logout
├── services/
│   └── api.js             (47 lignes)   — axios instance + helpers typés
└── pages/                 (21 fichiers, 6604 lignes)
    ├── Login.js                        (34)
    ├── Dashboard.js                    (232)  — refonte récente (v2.4.2)
    ├── Contrats.js                     (230)  — liste avec onglets statut + filtre famille
    ├── DetailContrat.js                (254)
    ├── ModifierContrat.js              (219)
    ├── NouveauContrat.js               (207)  — page obsolète remplacée par TunnelContrat ?
    ├── TunnelContrat.js                (608)  — assistant 4 étapes (le plus gros écran)
    ├── Renouvellements.js              (289)
    ├── Facturation.js                  (305)
    ├── Indices.js                      (183)
    ├── Clients.js                      (321)
    ├── Parametres.js                   (377)  — Karlia + Chorus + modèles Word
    ├── Utilisateurs.js                 (264)
    ├── Formateurs.js                   (280)
    ├── MesPrestations.js               (432)  — vue formateur, sélection date + créneaux
    ├── NouvellesCommandes.js           (503)
    ├── CommandesAPlanifier.js          (431)  — affecte les formateurs
    ├── CommandesPlanifiees.js          (308)
    ├── CommandesTerminees.js           (234)
    ├── ContratsACreer.js               (321)  — commandes avec necessite_contrat=true
    └── ChorusProPage.js                (496)
```

**Total** : 6881 lignes JS (sans build). Aucun fichier `.test.js` malgré la présence de `@testing-library/*` dans les deps → **pas de tests frontend en place**.

### 5.2 Routes — `App.js`

22 routes déclarées. Toutes (sauf `/login`) passent par `<PrivateRoute>` qui gère la redirection :
- pas d'utilisateur → `/login`
- prédicat `allow` retournant `false` → `/mes-prestations` (si FORMATEUR) ou `/` (sinon)

| Path | Composant | Restriction `allow` |
|---|---|---|
| `/login` | `Login` | public |
| `/` | `Dashboard` | tout connecté |
| `/contrats` | `Contrats` | `role !== 'FORMATEUR'` |
| `/contrats/nouveau` | `NouveauContrat` | `role !== 'FORMATEUR'` |
| `/contrats/tunnel` | `TunnelContrat` | `role !== 'FORMATEUR'` |
| `/contrats/:id` | `DetailContrat` | `role !== 'FORMATEUR'` |
| `/contrats/:id/modifier` | `ModifierContrat` | `role !== 'FORMATEUR'` |
| `/renouvellements` | `Renouvellements` | `role !== 'FORMATEUR'` |
| `/facturation` | `Facturation` | `role !== 'FORMATEUR'` |
| `/indices` | `Indices` | `role !== 'FORMATEUR'` |
| `/clients` | `Clients` | `role !== 'FORMATEUR'` |
| `/parametres` | `Parametres` | `role !== 'FORMATEUR'` |
| `/utilisateurs` | `Utilisateurs` | `role !== 'FORMATEUR'` |
| `/commandes/nouvelles` | `NouvellesCommandes` | `role !== 'FORMATEUR'` |
| `/commandes/a-planifier` | `CommandesAPlanifier` | `role !== 'FORMATEUR'` |
| `/commandes/planifiees` | `CommandesPlanifiees` | `role !== 'FORMATEUR'` |
| `/commandes/terminees` | `CommandesTerminees` | `role !== 'FORMATEUR'` |
| `/contrats-a-creer` | `ContratsACreer` | `role !== 'FORMATEUR'` |
| `/formateurs` | `Formateurs` | `role !== 'FORMATEUR'` |
| `/mes-prestations` | `MesPrestations` | tout connecté |
| `/chorus-pro` | `ChorusProPage` | `role !== 'FORMATEUR'` |
| `*` (fallback) | `Navigate to="/"` | — |

> **Limite du gating frontend** : seul le rôle `FORMATEUR` est filtré. Tous les autres rôles (`ADMIN`, `GESTIONNAIRE`, `TECHNICIEN`) ont accès à la même surface visuellement, et c'est l'objet `droits` (côté Layout) qui filtre le menu. Mais **les URLs restent atteignables** par saisie directe — le gating effectif dépend du backend, qui (cf. § 3) ne vérifie que rarement le rôle. C'est cohérent avec la limite déjà identifiée.

### 5.3 Contexte d'authentification — `context/AuthContext.js`

#### État exposé

```javascript
<AuthContext.Provider value={{ user, droits, loading, login, logout }}>
```

- `user` : `{ login, nom_complet, role, formateur_id }` ou `null`
- `droits` : objet booléen (9 droits) — **dupliqué côté frontend** par `getDroitsByRole(role)`
- `loading` : true tant que `authAPI.me()` n'a pas répondu au montage
- `login(username, password)` : POST `/api/auth/login` → stocke `token` dans `localStorage`
- `logout()` : `localStorage.removeItem('token')` + `window.location.href = '/login'`

#### Le tableau `getDroitsByRole(role)` — `AuthContext.js:7-35`

Reproduit **à l'identique** le tableau backend (`utilisateurs.py:17-22`). Quatre rôles : `ADMIN`, `GESTIONNAIRE`, `TECHNICIEN`, `FORMATEUR`. Par défaut, tout est `false`.

> **Anti-pattern critique** : double définition des droits (backend Python + frontend JS). Une modification d'un côté sans l'autre désaligne le menu / la sécurité. La refonte devrait exposer un endpoint canonique `GET /api/utilisateurs/droits` (déjà existant côté backend) **comme seule source** — c'est presque le cas (`AuthContext.js:48` appelle `authAPI.me()`) mais le client recalcule localement plutôt que d'utiliser la réponse `/api/utilisateurs/droits`.

#### Token JWT

Stocké dans `localStorage` (vulnérable XSS en théorie, OK pour ce module interne) ; envoyé en `Authorization: Bearer ${token}` via l'intercepteur axios (`api.js:3-7`). En cas de 401, l'intercepteur efface le token et redirige vers `/login` (`api.js:8-11`).

### 5.4 Couche réseau — `services/api.js`

**Toute petite couche** (47 lignes). Une instance axios sans `baseURL` (les chemins commencent tous par `/api/...` et passent par le proxy nginx). 5 namespaces exportés :

| Export | Fonctions | Note |
|---|---|---|
| `authAPI` | `login(username, password)`, `me()` | `login` envoie en `x-www-form-urlencoded` (compat OAuth2PasswordRequestForm) |
| `clientsAPI` | `liste`, `recherche(q)`, `creer`, `synchro` | manque : `fiche`, `obtenir`, `numero-suivant` (appels directs) |
| `contratsAPI` | `liste`, `detail`, `creer`, `valider`, `terminer`, `renouveler`, `renouvelerLot`, `renouvellements` | bien couvert |
| `produitsAPI` | `liste` | minimaliste |
| `indicesAPI` | `liste`, `creer`, `courant`, `supprimer` | manque : `modifier`, `verifier` |
| `facturationAPI` | `apercu`, `lancer`, `lotStatut` | manque : `calculer` |
| `dashboardAPI` | `stats()` | nouveauté v2.4.2 |
| `default` (`api`) | l'instance axios brute | beaucoup de pages l'utilisent en direct |

> **Anti-pattern** : ~50 % des pages utilisent `api.get/post/put/delete('/api/...')` en direct, ~50 % utilisent les helpers typés. **Inconsistant** — la refonte gagnerait à généraliser une approche (idéalement les helpers, ou un client RTK-Query / TanStack Query).

> **Pas de gestion d'erreur transverse** au-delà du 401 dans l'intercepteur. Chaque page traite ses erreurs en local (souvent avec `toast.error`). Pas de telemetry, pas de Sentry.

### 5.5 Pages — inventaire complet

Tableau exhaustif des 21 pages, leur rôle, et les endpoints qu'elles appellent.

| Page | Rôle métier | Endpoints appelés |
|---|---|---|
| `Login` | écran de login | `POST /api/auth/login` (via `useAuth`) |
| `Dashboard` | tableau de bord global | `POST /api/synchro/lancer`, `GET /api/synchro/statut`, `GET /api/dashboard/stats`, `GET /api/indices/courant` |
| `Contrats` | liste filtrable (statut, famille, recherche) | `GET /api/contrats` (via `contratsAPI.liste`) |
| `DetailContrat` | détail contrat + actions | `GET /api/contrats/{id}`, `PUT`/`DELETE /api/contrats/{id}`, `POST /api/contrats/{id}/valider`, `POST /api/contrats/{id}/terminer`, `POST /api/contrats/{id}/renouveler`, `GET /api/documents/contrat/{id}`, `POST /api/documents/generer/{id}` |
| `NouveauContrat` | ancien formulaire de création | `GET /api/indices/familles` — **probablement obsolète**, remplacé par `TunnelContrat` |
| `ModifierContrat` | modification d'un brouillon | `GET /api/indices/familles` + endpoints contrats |
| `TunnelContrat` | **assistant 4 étapes** (création/renouvellement) | `POST /api/contrats`, `POST /api/facturation/calculer`, `POST /api/facturation/lancer`, `GET /api/clients/search`, `GET /api/produits` |
| `Renouvellements` | écran des renouvellements (multi-sélection) | `GET /api/contrats/renouvellements`, `POST /api/contrats/renouveler-lot`, `GET /api/indices/familles` |
| `Facturation` | révision Syntec annuelle | `GET /api/facturation/apercu/{annee}`, `POST /api/facturation/calculer`, `POST /api/facturation/lancer`, `GET /api/indices/familles` |
| `Indices` | gestion indices Syntec | `GET /api/indices`, `POST /api/indices`, `DELETE /api/indices/{id}` |
| `Clients` | annuaire clients | `GET /api/clients/search` |
| `Parametres` | configuration globale | `GET/PUT /api/parametres/*`, `POST /api/parametres/tester-connexion`, `POST /api/parametres/vider-cache`, `GET/PUT /api/parametres/chorus`, `POST /api/chorus/test-connexion`, `GET/POST/DELETE /api/documents/modeles*` |
| `Utilisateurs` | gestion utilisateurs (ADMIN) | `GET/POST/PUT/DELETE /api/utilisateurs`, `GET /api/formateurs?actif_only=true` |
| `Formateurs` | gestion formateurs | `GET/POST/PUT/DELETE /api/formateurs` (actif_only true/false) |
| `MesPrestations` | vue formateur — agenda perso | `GET /api/prestations/formateur/{id}`, `POST /api/prestations/{id}/planifier`, `POST /api/prestations/{id}/realiser`, `GET /api/formateurs?actif_only=true` |
| `NouvellesCommandes` | sync devis + traitement | `POST /api/commandes/sync`, `GET /api/commandes/nouvelles`, `GET /api/commandes/stats`, `POST /api/commandes/{id}/valider`, `GET /api/commandes/{id}/pdf` |
| `CommandesAPlanifier` | affectation formateur + création prestations | `GET /api/commandes/a-planifier`, `GET /api/formateurs?actif_only=true`, `POST /api/prestations/from-commande/{id}` |
| `CommandesPlanifiees` | suivi planifié | `GET /api/commandes/planifiees` |
| `CommandesTerminees` | facturation des prestations terminées | `GET /api/commandes/terminees`, `POST /api/commandes/{id}/facturer` |
| `ContratsACreer` | commandes nécessitant contrat | `GET /api/commandes/contrats-a-creer`, `POST /api/commandes/{id}/lier-contrat/{contrat_id}` |
| `ChorusProPage` | dashboard Chorus | `POST /api/chorus/synchro-factures`, `GET /api/chorus/factures`, `POST /api/chorus/transmettre`, `POST /api/chorus/test-connexion`, `GET /api/chorus/statistiques`, `PUT /api/chorus/factures/{id}/siret` |

#### Particularité — `Dashboard.js` (refonte v2.4.2)

Avant le commit `2174640`, le Dashboard appelait plusieurs endpoints (`/api/contrats?statut=EN_COURS`, `/api/contrats/renouvellements`, `/api/commandes/stats`) puis agrégeait côté client. Désormais, **un seul appel** à `GET /api/dashboard/stats` retourne toutes les KPI.

Composants internes : `KPI`, `FamilleCard`, `CommandeStatutCard`. Le mapping `FAMILLE_META` (icônes + couleurs) est **codé en dur** côté frontend, en plus du mapping `FAMILLE_LABELS` côté backend (`dashboard.py:19-28`) — **double source de vérité** des familles.

> **Code legacy** : la sync Karlia est déclenchée au **montage du Dashboard** (`Dashboard.js:88-94`) via `POST /api/synchro/lancer`. C'est gênant : un utilisateur qui visite la page d'accueil déclenche silencieusement une sync clients + articles complète. À retirer ou rendre explicite.

#### Particularité — `TunnelContrat.js` (608 lignes — le plus gros écran)

Assistant en **4 étapes** (`ETAPES = ['Informations', 'Articles', 'Récapitulatif', 'Première facture']`) :

1. **Informations** : recherche client (cache local), date début/fin, montant annuel HT, famille, prorata + demi-mois
2. **Articles** : 1 article principal (rang 0) + jusqu'à 7 annexes — chaque ligne pointe vers un article Karlia (catalogue depuis `produitsAPI.liste`)
3. **Récapitulatif** : prévisualisation avant POST `/api/contrats`
4. **Première facture** : optionnelle, émet la facture an1 via `POST /api/facturation/calculer` puis `/lancer`

État interne lourd : 18 `useState` indépendants (`form`, `articles`, `clientSelectionne`, `prorata`, `demiMois`, `contratParent`, `contratCree`, `factureCree`, `etape`, etc.) — gestion d'état artisanale qui mériterait un `useReducer` ou un store léger.

#### Particularité — `MesPrestations.js` (vue formateur, 432 lignes)

Page la plus utilisée par les FORMATEUR. Permet :
- visualisation des prestations attribuées (statut, date prévue, planifiée)
- bascule date/heure → `POST /api/prestations/{id}/planifier`
- marquage réalisé → `POST /api/prestations/{id}/realiser`
- changement de formateur visible (sélecteur, si `toutes_prestations=true` côté droits)

> **À noter** : il n'y a aucune intégration calendrier (Google ou autre) malgré les colonnes DB `google_*` (cf. § 2.15). Tout passe par des inputs date/heure HTML natifs.

### 5.6 Menus latéraux — `components/Layout.js`

**3 menus distincts** selon le rôle :

#### `MENU_COMPLET` (ADMIN / GESTIONNAIRE)

23 entrées dont 4 séparateurs : `Tableau de bord` | **Commandes** (Nouvelles, À planifier, Planifiées, Terminées, Mes prestations) | **Contrats** (Liste, Nouveau, Contrats à créer, Renouvellements) | **Gestion** (Clients, Facturation, Indices Syntec, Chorus Pro) | **Administration** (Paramètres, Formateurs, Utilisateurs).

#### `MENU_FORMATEUR`

3 entrées : `Tableau de bord`, `Mes prestations`.

#### `MENU_TECHNICIEN`

5 entrées : `Tableau de bord`, `Mes prestations`, **Contrats** (`Contrats techniques`).

Le filtrage applique `droits[item.droit]` pour le menu complet ; le cleanup retire les séparateurs orphelins.

> **Observation UX** : le menu utilise des **emojis** (`📋`, `🆕`, `📅`, `✅`, `🏁`, `📋`, `🏢`, `💶`, `📈`, `📤`, `⚙️`, `👨‍🏫`, `👥`) comme icônes. C'est pratique en dev mais peu pro pour une production B2B SaaS. La présence de `lucide-react` en deps mais **jamais importée** (cf. § 5.7) suggère qu'un remplacement vers des SVG était prévu mais jamais terminé.

### 5.7 Bibliothèques UI installées vs. utilisées

| Lib | Version | Utilisée ? | Où |
|---|---|---|---|
| `react` + `react-dom` | 19.2.4 | ✓ | partout |
| `react-router-dom` | 7.13.1 | ✓ | `App.js` + 11 pages |
| `axios` | 1.13.6 | ✓ | `api.js` |
| `tailwindcss` | 3.4.19 (dev) | ✓ | toutes les pages |
| `date-fns` | 4.1.0 | ✓ | 11 pages (format `dd/MM/yyyy`) |
| `react-hot-toast` | 2.6.0 | ✓ | 9 pages (`toast.success`, `toast.error`) |
| `lucide-react` | 0.576.0 | **✗** | **jamais importée** |
| `react-select` | 5.10.2 | **✗** | **jamais importée** |
| `react-datepicker` | 9.1.0 | **✗** | **jamais importée** |
| `@testing-library/*` | divers (dev) | **✗** | aucun test |
| `web-vitals` | 2.1.4 | **✗** | aucun import |

> **Conséquence build** : `lucide-react`, `react-select`, `react-datepicker` sont **dans le bundle final** sans servir. Tree-shaking imparfait ⇒ poids additionnel. Total potentiellement économisable : ~300 ko gzippés. À retirer en pré-refonte.

### 5.8 Conventions et helpers récurrents

#### Formatage de date

D'après `CODING_RULES.md:32-39`, la règle est : `new Date(date + 'T12:00:00')` pour éviter les décalages timezone Paris. Vérifié dans plusieurs pages, mais **pas systématiquement appliqué**. Les nouvelles pages (Dashboard, ChorusProPage) utilisent `new Date(...)` sans suffixe → risque de décalage J-1 en timezone Paris.

#### Pagination

Les pages liste paginées (`Contrats`, `NouvellesCommandes`, `Renouvellements`, …) ont chacune leur **propre composant pagination interne** — pas d'helper partagé. Code dupliqué.

#### Toast d'erreur

`toast.error(e.response?.data?.detail || 'Erreur')` — pattern répété ~30 fois. Aucun helper `handleApiError(e)` centralisé.

### 5.9 Points d'observation pour la refonte

| # | Observation | Sévérité |
|---|---|---|
| 1 | CRA (Create React App) en mode maintenance depuis 2024 — migration Vite/Next recommandée | élevée |
| 2 | Pas de tests frontend malgré `@testing-library/*` installé | élevée |
| 3 | 3 bibliothèques UI installées **jamais utilisées** (lucide, react-select, react-datepicker) — ~300 ko inutiles | moyenne |
| 4 | Double source de vérité **droits utilisateur** (backend + AuthContext) | élevée |
| 5 | `Dashboard` lance une sync Karlia silencieuse au montage | moyenne |
| 6 | Mélange `api.get` direct + helpers `xAPI.*` → inconsistance | moyenne |
| 7 | 18 `useState` dans `TunnelContrat` → manque de `useReducer` ou store | moyenne |
| 8 | Mapping famille (icônes/couleurs) dupliqué front + back | basse |
| 9 | Emojis comme icônes — peu pro, prévoir migration `lucide-react` | basse |
| 10 | Aucun composant `Pagination` partagé | basse |
| 11 | `NouveauContrat.js` (207 lignes) probablement obsolète vs `TunnelContrat` | basse |
| 12 | TZ Paris : règle `T12:00:00` documentée mais pas systématique | moyenne |
| 13 | Aucun helper d'erreur API partagé | basse |
| 14 | Pas de TypeScript | élevée si refonte ambitieuse |

---

## 6. Workflows métier de bout en bout

Cette section trace **chaque cas d'usage métier** à travers les couches : déclencheur utilisateur → pages frontend → endpoints backend → tables modifiées → appels externes → effets de bord → points de friction connus.

### Workflow 1 — Création d'un contrat via le tunnel 4 étapes

**Déclencheur** : clic sur "Nouveau contrat" (bouton dashboard ou item menu `/contrats/tunnel?mode=nouveau`).

**Page frontend** : `pages/TunnelContrat.js` (608 lignes) — assistant en 4 étapes.

**Flux détaillé** :

```
ÉTAPE 0 — INFORMATIONS
─────────────────────
Utilisateur saisit : numero_contrat, client (via recherche cache), famille,
date_debut, date_fin, montant_annuel_ht.
Frontend appelle :
  - GET /api/clients (via clientsAPI.liste, recherche debounced 300ms)
Le frontend calcule le prorata localement (fonction calculerProrata) pour preview ;
le calcul officiel est refait côté backend lors du POST /api/contrats.

ÉTAPE 1 — ARTICLES
──────────────────
Utilisateur ajoute jusqu'à 8 articles (1 principal rang 0 + 7 annexes).
Pour chaque article : recherche dans le catalogue produits :
  - GET /api/produits (via produitsAPI.liste, source=cache par défaut)
Validation locale : article rang 0 obligatoire avec id_product Karlia.

ÉTAPE 2 — RÉCAPITULATIF
───────────────────────
Affichage statique du contrat + plan prévisionnel calculé localement.
Bouton "Créer le contrat" :
  1. POST /api/contrats (contrats.py:150)
       └─► INSERT contrats (statut=BROUILLON)
       └─► INSERT N contrat_articles (rang 0..7)
       └─► appelle generer_plan_facturation()
       └─► INSERT N plan_facturation (1 par année civile, statut=PLANIFIEE)
       └─► COMMIT
  2. POST /api/contrats/{id}/valider (contrats.py:272)
       └─► UPDATE contrats SET statut='EN_COURS', validated_at=now()
       └─► COMMIT
  3. GET /api/contrats/{id} (recharge)

ÉTAPE 3 — PREMIÈRE FACTURE
──────────────────────────
Bouton "Émettre la première facture" (optionnel) :
  1. POST /api/facturation/calculer (annee=an1, plan_ids=[premiere_id])
       └─► garde_pre_calcul (validation_service.valider_pre_calcul)
       └─► montant_revise_ht = montant_ht_prevu (an1 = pas de révision)
       └─► UPDATE plan_facturation SET statut='CALCULEE'
  2. POST /api/facturation/lancer (annee=an1, plan_ids=[premiere_id])
       └─► appelle karlia.creer_facture()  ← APPEL KARLIA
       └─► UPDATE plan_facturation SET statut='EMISE', facture_karlia_id=…
       └─► COMMIT
```

**Tables modifiées** : `contrats` (E), `contrat_articles` (E), `plan_facturation` (E), éventuellement `documents_generes` (E si génération Word séparément).

**Appels externes** : `POST Karlia /documents` (id_status=1 Brouillon) si étape 3.

**Effets de bord** :
- Le numéro de contrat doit être unique — saisi manuellement par l'utilisateur (pas de génération automatique).
- L'étape 3 est **optionnelle** — un contrat peut être laissé sans facture an1 (sera émise lors du run de facturation Syntec annuelle).

**Points de friction connus** :
- `client_karlia_id` peut être désynchronisé si le cache local est obsolète (clients récemment créés dans Karlia). Recommandation : utiliser `source=karlia` pour la recherche, mais le code utilise `cache` par défaut.
- L'étape 3 enchaîne `calculer` puis `lancer` dans la même session, mais `valider_pre_emission` n'est pas appelé entre les deux (cf. anti-pattern #9 de la phase 4).

### Workflow 2 — Renouvellement d'un contrat

**Déclencheur** : depuis l'écran `Renouvellements` (filtre par mois/famille), ou depuis le détail d'un contrat dont la date_fin approche.

**Pages frontend** : `pages/Renouvellements.js` (289 lignes) — multi-sélection + traitement en lot, ou `pages/DetailContrat.js` (action individuelle).

**Endpoint principal** : `POST /api/contrats/{id}/renouveler` avec body `{type_renouvellement, …}`. **3 cas** :

```
CAS A — SPONTANE (prolongation 1 an)
─────────────────────────────────────
Frontend choisit type_renouvellement="SPONTANE", aucune autre donnée.
Backend (contrats.py:420-442) :
  - date_fin += 1 an (dateutil.relativedelta)
  - nombre_annees recalculé
  - statut = 'EN_COURS'
  - ajoute 1 ligne plan_facturation pour l'année supplémentaire
  - COMMIT
Tables : UPDATE contrats, INSERT plan_facturation (×1)
Appels externes : aucun.

CAS B — NOUVEAU_CONTRAT (création + archivage)
──────────────────────────────────────────────
Frontend saisit : nouveau_numero, nouvelle_date_debut, nouvelle_date_fin (optionnelles).
Backend (contrats.py:444-541) :
  - Archive l'ancien : statut='TERMINE', motif_fin="Remplacé par nouveau contrat"
  - Trouve les avenants enfants (contrat_parent_id = ancien.id, type='AVENANT')
  - Crée nouveau contrat (type='RENOUVELLEMENT', contrat_parent_id=ancien.id)
  - Copie les articles principaux de l'ancien
  - Fusionne les articles des avenants (avec préfixe "[Avenant N]")
  - Génère le plan_facturation complet
  - COMMIT
Tables : INSERT contrats + N contrat_articles + N plan_facturation,
         UPDATE ancien contrat (TERMINE), UPDATE avenants (TERMINE)
Appels externes : aucun.

CAS C — FIN (arrêt sans suite)
──────────────────────────────
Backend (contrats.py:413-418) :
  - statut='TERMINE', motif_fin=notes ou "Départ client"
  - COMMIT
Tables : UPDATE contrats (×1)
```

**Variante lot** : `POST /api/contrats/renouveler-lot` (contrats.py:585) supporte uniquement `SPONTANE` et `FIN`, **avec 1 COMMIT par contrat** → pas de transaction globale (cf. anti-pattern phase 3).

**Effets de bord NOUVEAU_CONTRAT** :
- Le nouveau contrat naît en `BROUILLON` — il faut ensuite passer par `/valider` pour le faire passer `EN_COURS` (workflow non automatisé par le renouvellement).
- Les avenants sont **automatiquement terminés** mais leurs articles sont **intégrés au nouveau contrat** uniquement si le rang reste ≤ 7 (limite dure). Au-delà, les articles d'avenants sont **silencieusement perdus**.

**Points de friction** :
- Le renouvellement multi-sélection commit par contrat — si une erreur survient à mi-parcours, les contrats déjà renouvelés sont engagés, les autres non.
- Aucun audit-trail dédié n'enregistre qui a renouvelé quoi (juste `motif_fin` en texte libre).

### Workflow 3 — Révision Syntec annuelle (facturation N)

**Déclencheur** : utilisateur ouvre `/facturation` en début d'année N.

**Page frontend** : `pages/Facturation.js` (305 lignes).

**Flux détaillé** :

```
1. APERÇU
─────────
GET /api/facturation/apercu/{annee}?famille=… (facturation.py:18)
   → liste des plans PLANIFIEE/CALCULEE pour l'année
   → indique facturable=true si annee ≤ annee_courante
   → indique indices_ok=false si Syntec N-2 ou N-1 manquant

2. CHOIX UTILISATEUR
────────────────────
Cocher les plans à traiter. Pour les contrats DIGITECH, saisir nouveau_montant.

3. CALCUL
─────────
POST /api/facturation/calculer (facturation.py:56)
  body: { annee, plan_ids:[…], nouveaux_montants: { plan_id: montant } }
  Pour chaque plan :
    a. garde_pre_calcul (validation_service)
       → bloque si déjà EMISE, indice manquant, montant manuel requis, montant_ref nul
    b. Si annee == an1 du contrat : montant_revise = montant_ht_prevu (pas de révision)
    c. Sinon :
       - regle = COSOLUCE/MAINTENANCE/ASSISTANCE_TEL → Syntec AOUT
       - regle = CANTINE → Syntec OCTOBRE
       - regle = DIGITECH → manuel
       - regle = KIWI_BACKUP/AUTRE → AUCUNE
       calcul_revision(famille, annee, montant_precedent, nouveau_montant_manuel)
       → taux = indice(N-1) / indice(N-2), arrondi 6 décimales
       → montant_revise = montant_precedent × taux, arrondi 0.01
    d. UPDATE plan_facturation SET statut='CALCULEE', montant_revise_ht, taux_revision,
                                    indice_calcul_id, montant_annuel_precedent
    e. COMMIT
Retourne { resultats: [{plan_id, ok, montant_revise, taux_revision, message}] }

4. ÉMISSION
───────────
POST /api/facturation/lancer (facturation.py:135)
  body: { annee, plan_ids:[…] }
  Pour chaque plan :
    a. Récupère les articles du contrat (rang ASC)
    b. Construit N lignes Karlia, applique taux_revision sur chaque unit_price
    c. Ajustement d'arrondi sur la dernière ligne (somme == montant_ht_decimal)
  Appelle karlia.traitement_lot_factures(factures_a_emettre, delai=0.8s)
  Pour chaque résultat Karlia :
    - succès : UPDATE plan_facturation SET statut='EMISE', facture_karlia_id,
                                          facture_karlia_ref, montant_annuel_precedent
               (montant_annuel_precedent ← montant émis, pour révision N+1)
    - échec : UPDATE plan_facturation SET statut='ERREUR', erreur_message
    - validation post (logée mais non bloquante)
  COMMIT après chaque plan
```

**Tables modifiées** : `plan_facturation` (E lourd).

**Appels externes** : N × `POST Karlia /documents` (1 facture par contrat retenu) avec délai 0.8s entre appels (≈ 75 req/min).

**Effets de bord** :
- Une fois EMISE, un plan ne peut plus être recalculé (`valider_pre_calcul` bloque DEJA_EMISE).
- En cas d'échec Karlia, le plan reste `ERREUR` ; il faut intervenir manuellement (corriger en DB ou retraiter).
- Pas de `lots_facturation` créé (cf. anti-pattern phase 3 — `lot_id` jamais persisté).

**Points de friction** :
- L'utilisateur peut **lancer `/lancer` directement** sans passer par `/calculer` si le plan est `PLANIFIEE` ; dans ce cas, le `montant_revise_ht` est NULL et le code prend `montant_ht_prevu` (qui est le montant **non révisé**) — risque de facturation à l'ancien tarif.
- Aucun appel à `valider_pre_emission` (cf. anti-pattern phase 4 #9) → l'absence d'`article_karlia_id` ne bloque pas l'émission, Karlia peut alors enregistrer une facture à montant 0.

### Workflow 4 — Devis → Commande → Prestation → Facture (cycle commandes)

**Déclencheur** : utilisateur clique "Synchroniser depuis Karlia" sur `/commandes/nouvelles`.

**Pages frontend** : `NouvellesCommandes`, `CommandesAPlanifier`, `CommandesPlanifiees`, `CommandesTerminees`, `MesPrestations`.

**Cycle complet** :

```
ÉTAPE 1 — SYNCHRONISATION DEVIS ACCEPTÉS
─────────────────────────────────────────
Déclencheur : POST /api/commandes/sync (commandes.py:200)
Backend :
  → karlia_devis_service.sync_devis_acceptes(db, force_full=False)
  → Lit derniere_synchro_devis dans parametres
  → GET /documents?type=1&id_status=2 paginé (Karlia)
  → Pour chaque devis :
      - sleep 1.2s (KARLIA_SYNC_SLEEP_SECONDS)
      - skip si opportunity déjà "Traité" et pas de commande locale
      - sinon INSERT commandes (statut='nouvelle') + N INSERT commande_lignes
      - GET /opportunities/{id}/custom-fields → vérification "Traité"
      - POST /opportunities/{id}/custom-fields/66505 {field_value: 1}
        → MARQUE COMME "TRAITÉ" CÔTÉ KARLIA (effet de bord externe non réversible)
  → UPDATE parametres.derniere_synchro_devis

ÉTAPE 2 — VALIDATION (choix de traitement)
──────────────────────────────────────────
Sur NouvellesCommandes : utilisateur clique "Valider"
POST /api/commandes/{id}/valider (commandes.py:310)
  body: { type_traitement: 'a_planifier' | 'sans_planification', necessite_contrat: bool }
  Backend :
    - statut 'nouvelle' → 'a_planifier' (si type='a_planifier')
                        OU 'deployee' (si type='sans_planification')
    - date_validation = now()

ÉTAPE 3a — PLANIFICATION (si type='a_planifier')
────────────────────────────────────────────────
Sur CommandesAPlanifier : sélection formateur
POST /api/commandes/{id}/planifier (commandes.py:335)
  body: { date_planifiee, intervenant_id, intervenant_nom, notes }
  Backend :
    - statut 'a_planifier' → 'planifiee'
    - date_planifiee, intervenant_id renseignés

ÉTAPE 3b — CRÉATION DES PRESTATIONS (workflow récent)
─────────────────────────────────────────────────────
POST /api/prestations/from-commande/{commande_id}?formateur_id=X
  (prestations.py:203)
  Backend :
    - bloque si des prestations existent déjà pour cette commande
    - pour chaque commande_ligne, INSERT prestations (statut='a_planifier',
      formateur_id, designation issue de la ligne)

ÉTAPE 4 — PLANIFICATION DES PRESTATIONS (par formateur)
───────────────────────────────────────────────────────
Sur MesPrestations (vue formateur) :
POST /api/prestations/{id}/planifier (prestations.py:283)
  body: { date_planifiee, heure_debut, heure_fin, lieu, notes }
  Backend :
    - statut 'a_planifier' → 'planifiee'
    - SI toutes les prestations de la commande sont 'planifiee'/'realisee' :
      → la commande mère bascule à 'planifiee' (effet de bord en cascade)

ÉTAPE 5 — RÉALISATION
─────────────────────
POST /api/prestations/{id}/realiser (prestations.py:315)
  Backend :
    - statut 'planifiee' → 'realisee'
    - SI toutes les prestations de la commande sont 'realisee' :
      → la commande mère bascule à 'deployee' (équivalent métier "terminée")

ÉTAPE 6 — FACTURATION
─────────────────────
Sur CommandesTerminees : utilisateur clique "Facturer"
POST /api/commandes/{id}/facturer (commandes.py:404)
  Backend :
    - bloque si statut != 'deployee' ou client_karlia_id absent
    - construit lignes_karlia depuis commande_lignes
    - POST Karlia /documents (id_status=1 Brouillon)
    - UPDATE commandes SET statut='facturee', facture_karlia_id, facture_karlia_ref
```

**Tables modifiées** : `commandes` (E), `commande_lignes` (E), `prestations` (E), `parametres` (E derniere_synchro_devis).

**Appels externes** :
- Karlia : `GET /documents`, `GET /documents/{id}`, `GET /customers/{id}`, `GET /opportunities/{id}`, `POST /opportunities/{id}/custom-fields/66505`, `POST /documents` (facturation finale).
- Pas d'appel Google Calendar (service retiré).

**Points de friction** :
- Le marquage "Traité" côté Karlia est **non réversible** sans intervention manuelle dans Karlia.
- Le statut `terminee` (`commandes.py:367`) est mort — jamais affiché en liste.
- Les "terminees" affichées dans `CommandesTerminees` sont en réalité `deployee` (incohérence terminologique).
- Le cycle prestations est **embryonnaire** : 11 prestations seulement dans la DB sur 142 commandes (cf. phase 2). La majorité des commandes facturées suivent probablement le raccourci `sans_planification` (saute à `deployee` directement).

### Workflow 5 — Génération du plan de facturation

Sous-workflow déclenché à chaque **création** ou **modification** de contrat brouillon, ou par le **renouvellement** SPONTANE (1 ligne ajoutée).

**Code** : `services/contrat_service.py::generer_plan_facturation` (`contrat_service.py:56`).

**Algorithme** :

```python
plan = []
annee_debut = date_debut.year
annee_fin = date_fin.year
num = 1

for annee in range(annee_debut, annee_fin + 1):
    if annee == annee_debut and prorata["prorate"]:
        plan.append({
            "numero_facture": num,
            "annee_facturation": annee,
            "date_echeance": date(annee, 1, 1) if date_debut.month == 1 else date_debut,
            "type_facture": "PRORATE",
            "montant_ht_prevu": float(prorata["montant_ht"]),
            "statut": "PLANIFIEE",
        })
    else:
        plan.append({
            "numero_facture": num,
            "annee_facturation": annee,
            "date_echeance": date(annee, 1, 1),
            "type_facture": "ANNUELLE",
            "montant_ht_prevu": float(montant_annuel_ht),
            "statut": "PLANIFIEE",
        })
    num += 1
return plan
```

**Règles métier appliquées** :
- 1 ligne par année civile entre `date_debut.year` et `date_fin.year` inclus.
- Si l'an 1 est proraté (date_debut ≠ 01/01) : type `PRORATE`, montant proraté, échéance = `date_debut`.
- Sinon : type `ANNUELLE`, montant = `montant_annuel_ht` brut, échéance = 1er janvier de l'année.
- Statut initial : `PLANIFIEE`.
- Les montants annuels seront révisés à l'émission via le workflow 3.

**Tables modifiées** : `plan_facturation` (INSERT N lignes).

**Points de friction** :
- `calculer_nombre_annees` retourne `annee_fin - annee_debut + 1` : un contrat 01/03/2026 → 28/02/2027 retourne **2 lignes** (2026 prorata + 2027 année pleine) — comportement acceptable mais à expliciter.
- En cas de modification (`PUT /api/contrats/{id}`), le plan est **DELETE puis ré-INSERT en bloc** (`contrats.py:362-382`). Les `karlia_synchro_at`, `facture_karlia_id`, etc. déjà renseignés sur les lignes sont perdus. Heureusement, seuls les `BROUILLON` sont modifiables — donc aucun plan n'a encore été émis. Mais si la règle évolue, attention.

### Workflow 6 — Émission d'une facture vers Karlia

Sous-workflow appelé par les **workflows 3 (révision Syntec)** et **4 (facturation commande)**.

**Code** : `services/karlia_service.py::creer_facture` (`karlia_service.py:164`).

**Étapes** :

```
1. CONVERSION LIGNES → format Karlia
   pour chaque ligne :
     tva = ligne["vat_rate"]
     id_vat = "1" si tva ≥ 20
              "2" si tva ≥ 10
              "3" si tva ≥ 5
              "4" sinon (0%)
     p = { "price_without_tax": …, "quantity": …, "id_vat": … }
     si "id_product" présent : p["id_product"] = ligne["id_product"]
     sinon : p["description"] = ligne["description"] (fallback)

2. PAYLOAD KARLIA
   {
     "id_customer": int(client_karlia_id),
     "id_type": 4,                         # Facture
     "id_status": 1,                       # Brouillon (depuis v2.4.1)
     "reference": reference_contrat,       # ex CO-2025-001
     "date": today.strftime("%d/%m/%Y"),
     "date_end": date_echeance.strftime("%d/%m/%Y"),
     "description": description,
     "products_list": products_list
   }

3. POST /documents (Karlia)
   → renvoie {id, reference, …}

4. ERREURS
   401 → KarliaError("Clé API invalide ou expirée")
   429 → KarliaError("Quota dépassé 100 req/min")  — pas de retry ici
   autre → KarliaError(status, …)
```

**Tables modifiées** :
- Workflow 3 : `plan_facturation` (E facture_karlia_id, facture_karlia_ref, statut)
- Workflow 4 : `commandes` (E facture_karlia_id, facture_karlia_ref, statut='facturee')

**Appels externes** : `POST https://karlia.fr/app/api/v2/documents` avec Bearer Authorization.

**État cible côté Karlia** : la facture est créée en **statut Brouillon** (`id_status=1`). Elle doit être **validée manuellement** dans l'interface Karlia pour être envoyée au client.

> **Évolution récente** (cf. § 9) : le statut a évolué `2 (Envoyée) → 1 (Brouillon) → 0 (Brouillon réel)`. La branche `fix/karlia-facture-brouillon-v2` (tag `v2.4.6.1`) **non mergée sur main** change `id_status=1 → id_status=0`. Sur main aujourd'hui : `id_status=1`.

**Points de friction** :
- Le mapping `id_vat` plafonne à 4 codes — TVA intermédiaires (8.5%, 2.1%) toutes alignées sur `id_vat=4` ce qui est faux.
- Si la facture échoue côté Karlia (validation manuelle refusée), aucune notification revient vers le module — `plan_facturation` reste `EMISE` indéfiniment.
- `traitement_lot_factures` : aucun retry sur 429 (cf. anti-pattern phase 4 #4).

### Workflow 7 — Import des factures Karlia → table `factures_karlia` (préparation Chorus Pro)

**Déclencheur** : utilisateur clique "Synchroniser depuis Karlia" sur `/chorus-pro`.

**Page frontend** : `pages/ChorusProPage.js`.

**Endpoint** : `POST /api/chorus/synchro-factures` (`chorus.py:119`).

**Flux** :

```
1. APPEL KARLIA
   karlia._get("/documents", {
       type: 4,           # Facture
       status: 2,         # Envoyée (validée dans Karlia)
       limit: 500,
       order: "date",
       direction: "DESC"
   })
   → liste des factures émises et validées dans Karlia

2. POUR CHAQUE FACTURE
   - extraire id_customer, customer_name
   - chercher client dans clients_cache pour récupérer SIRET
     (chorus.py:163-169 — fallback si client absent du cache → SIRET=None)
   - calculer montants HT/TTC/TVA
   - parser date_facture (format "dd/MM/yyyy") et date_echeance

3. UPSERT factures_karlia
   - Si existante (karlia_document_id) ET statut_chorus == "NON_TRANSMISE" :
     UPDATE client_nom, client_siret, montants, date_echeance
     (les factures déjà TRANSMISE/EN_COURS ne sont pas mises à jour)
   - Si absente :
     INSERT avec statut_chorus="NON_TRANSMISE", contrat_id=NULL
   - COMMIT global à la fin
```

**Tables modifiées** : `factures_karlia` (INSERT/UPDATE conditionnel).

**Appels externes** : `GET https://karlia.fr/app/api/v2/documents?type=4&status=2&limit=500`.

**Effets de bord** :
- **Aucun lien automatique avec `contrats`** : `contrat_id` reste `NULL`. Le lien doit être fait manuellement (ou par un script).
- Les factures **déjà transmises** Chorus ne sont pas mises à jour — leurs métadonnées (SIRET corrigé) ne se propagent pas.
- Pas de delta : la sync ramène **toutes** les 500 dernières factures à chaque appel.

**Points de friction** :
- Si une facture Karlia est **modifiée** dans Karlia (montants, SIRET) **après transmission Chorus**, le module ne le sait pas. Risque de désynchronisation facture émise / facture transmise.
- Limite à 500 : si > 500 factures depuis le dernier import, les plus anciennes sont silencieusement omises. Aucune pagination boucle ici (contrairement à `/customers`).

### Workflow 8 — Transmission Chorus Pro via PISTE (OAuth2)

**Déclencheur** : utilisateur sélectionne une ou plusieurs factures `NON_TRANSMISE` dans `/chorus-pro` et clique "Transmettre".

**Page frontend** : `pages/ChorusProPage.js`.

**Endpoint** : `POST /api/chorus/transmettre` (`chorus.py:352`).

**Flux détaillé** :

```
1. CONFIGURATION
   _get_chorus_service(db) lit les 8 paramètres chorus_* depuis parametres
   Si l'un manque → HTTPException(400, "Configuration Chorus Pro incomplète")
   → ChorusProService(client_id, client_secret, tech_username, tech_password,
                      siret_emetteur, code_service, code_banque, mode_qualification)

2. POUR CHAQUE facture_id du request
   a. Charger FactureKarlia par id
   b. Refuser si statut_chorus IN (TRANSMISE, ACCEPTEE, EN_COURS)
   c. Refuser si client_siret est NULL
   d. INSERT TransmissionChorus (statut=EN_COURS, transmis_par=current_user.login)
   e. UPDATE FactureKarlia SET statut_chorus='EN_COURS'
   f. COMMIT
   g. Appel SERVICE :
      ChorusProService.soumettre_facture(
          destinataire_siret, destinataire_code_service, numero_facture,
          date_facture, date_echeance, montant_ht, montant_tva, montant_ttc,
          commentaire="Facture {numero_facture}"
      )
      → service._get_access_token()  ← OAuth2 token PISTE (cache en mémoire 55min)
      → service._post("/soumettre", payload)
      → Réponse PISTE : {numeroFluxDepot, identifiantFactureCPP, ...}

   h. SUCCÈS :
      - transmission.statut = 'SUCCES'
      - transmission.chorus_id_flux = numeroFluxDepot
      - transmission.chorus_id_facture = identifiantFactureCPP
      - transmission.reponse_json = (full response)
      - facture.statut_chorus = 'TRANSMISE'
      - facture.date_transmission = now()
      - facture.chorus_numero_flux = numeroFluxDepot
      - COMMIT

   i. ÉCHEC (ChorusError) :
      - transmission.statut = 'ECHEC'
      - transmission.code_retour = str(status_code)
      - transmission.message_retour = e.message
      - transmission.reponse_json = e.detail
      - facture.statut_chorus = 'ERREUR'
      - facture.chorus_message_erreur = "{status}: {message}"
      - COMMIT

3. RÉSUMÉ
   { "transmises": N, "echecs": M, "details": [...] }
```

**Tables modifiées** :
- `transmissions_chorus` (INSERT, puis UPDATE statut)
- `factures_karlia` (UPDATE statut_chorus, date_transmission, chorus_numero_flux, chorus_message_erreur)

**Appels externes** :
- `POST https://[sandbox-]oauth.piste.gouv.fr/api/oauth/token` (OAuth2 client_credentials)
- `POST https://[sandbox-]api.piste.gouv.fr/cpro/factures/v1/soumettre`

**Authentification PISTE — particularité** :

```
HTTP request body : grant_type=client_credentials&scope=openid
HTTP headers     : Authorization: Basic base64(tech_username:tech_password)
HTTP basic auth  : auth=(client_id, client_secret)
```

C'est la **double authentification** notée comme suspect dans anti-pattern phase 4 #11. PISTE attend `client_id/client_secret` comme l'OAuth2 standard via HTTP Basic auth pour identifier l'application, **et en plus** des credentials techniques (`tech_username/tech_password`) dans le header `Authorization` pour identifier l'utilisateur Chorus Pro qui dépose la facture. Cette construction est documentée dans la doc PISTE Chorus Pro mais peu connue.

**Token OAuth — cache** : le `ChorusProService` cache le token en mémoire (`chorus_service.py:65-66`) avec une marge de 5 min sur l'expiration (1h par défaut). **Mais le service est ré-instancié à chaque requête** (`_get_chorus_service(db)` dans `chorus.py:92`) → le cache n'est pas partagé entre requêtes. Chaque transmission redemande un token.

**État cible** :
- `factures_karlia.statut_chorus` passe à `TRANSMISE` (succès) ou `ERREUR` (échec).
- Le statut Chorus côté PISTE évolue ensuite : `RECUE`, `EN_TRAITEMENT`, `ACCEPTEE`, `REJETEE`. **Aucun polling automatique** n'est en place pour rafraîchir `statut_chorus` après la transmission initiale.

**Points de friction connus** :
- **Blocage 403 PISTE en production** (mémoire utilisateur [[chorus_pro_blocage]]) : 13 factures sur 15 sont `NON_TRANSMISE`, 1 `TRANSMISE`, 1 `ERREUR`. La cause exacte est en attente d'investigation côté Codial ou support PISTE.
- Pas de mécanisme de **renvoi** automatique en cas d'échec — toute facture en `ERREUR` doit être manuellement rejouée.
- Le `typeTva` est codé en dur `"TVA_SUR_DEBIT"` (cf. anti-pattern phase 4 #10).
- Aucun mécanisme de **retransmission** explicite : si l'utilisateur réessaie une facture `ERREUR`, un nouveau `TransmissionChorus` est créé mais la facture passe par les mêmes garde-fous.

### Workflow 9 — Synchronisation Karlia → DB locale (clients + articles)

**Déclencheur** : trois possibilités :
- Automatique au **boot du conteneur backend** (`main.py:165`)
- Automatique chaque **nuit à 02:00** (cron APScheduler `main.py:167`)
- Manuel : `POST /api/synchro/lancer` (depuis `/parametres` ou `Dashboard.js:90`)

**Endpoint** : `POST /api/synchro/lancer` ou directement `synchro_karlia()` (`main.py:38`).

**Flux** :

```
1. RECHARGER LA CLÉ API
   db.query(Parametre).filter(cle=='karlia_api_key').first()
   → karlia.api_key = param.valeur  (réécrit l'instance globale)
   Si pas de clé → log "Clé API absente — synchronisation ignorée" et return

2. SYNC CLIENTS (boucle paginée)
   offset = 0; limit = 100
   while True :
     result = karlia.lister_clients(limit, offset)
     pour chaque client Karlia :
       extraire karlia_id, client_number (fallback K{karlia_id}), address_list[type=main]
       upsert dans clients_cache :
         - si karlia_id existe → UPDATE
         - si karlia_id absent ET numero_client existe → fallback numéro K{karlia_id}
         - sinon INSERT
     db.commit() après chaque page
     si len(clients_data) < limit : break
     offset += 100

3. SYNC ARTICLES (un seul appel)
   result = karlia.lister_produits(limit=500)
   pour chaque produit :
     upsert dans articles_cache (par karlia_id)
   db.commit()

4. METTRE À JOUR LES STATS
   UPDATE parametres SET valeur=now WHERE cle='derniere_synchro'
   UPDATE parametres SET valeur='{total_clients} clients, {total_articles} articles'
     WHERE cle='synchro_stats'

5. LOG : "Terminée — {total_clients} clients, {total_articles} articles"
```

**Tables modifiées** : `clients_cache` (E), `articles_cache` (E), `parametres` (E `derniere_synchro` + `synchro_stats`).

**Appels externes** :
- Karlia : N × `GET /customers?limit=100&offset=…` (N = ⌈total_clients / 100⌉ + 1)
- Karlia : 1 × `GET /products?limit=500`

**Effets de bord** :
- Au boot, **bloque le démarrage** du backend tant que la sync n'est pas finie (cf. anti-pattern phase 1).
- Le scheduler crée 1 job à 02:00 ; si plusieurs instances backend tournent → multiple synchros concurrentes.
- Les clients supprimés dans Karlia restent dans `clients_cache` (pas de mécanisme de purge).

**Points de friction** :
- Sync globale (pas de delta) → coûteux côté quota Karlia (251 clients = 3 pages, 404 articles = 1 page).
- Si Karlia est indisponible, la synchro échoue silencieusement (catch global `print("Erreur : …")`).
- La sync **devis acceptés** (workflow 4) est **séparée** de cette sync et utilise `karlia_devis_service` (cf. § 4.2).

### Workflow 10 — Cycle d'authentification (login → JWT → droits)

**Déclencheur** : ouverture de l'application par un utilisateur non connecté.

**Pages frontend** : `pages/Login.js` (34 lignes) + `context/AuthContext.js`.

**Flux** :

```
1. CHARGEMENT INITIAL
   AuthProvider monté :
     - lit localStorage.token
     - si token : GET /api/auth/me (JWT en Authorization header via intercepteur axios)
       - 200 : setUser({login, nom_complet, role, formateur_id}),
               setDroits(getDroitsByRole(role))  ← duplication locale
       - !200 : localStorage.removeItem('token'), user reste null
     - sinon : user reste null
   loading passe à false → AppRoutes rendu

2. SAISIE LOGIN
   Login.js :
     handleSubmit → useAuth().login(username, password)
       → authAPI.login() :
           POST /api/auth/login
           Content-Type: application/x-www-form-urlencoded
           body: username=…&password=…
       → backend (auth.py:27) :
           - SELECT utilisateurs WHERE login = username
           - bcrypt.checkpw(password, user.password_hash)
           - jwt.encode({sub, role, id, formateur_id, exp=now+24h}, SECRET_KEY, HS256)
           - return {access_token, token_type, nom_complet, role, formateur_id}
     → localStorage.setItem('token', access_token)
     → setUser/setDroits localement (sans rappeler /me)
   navigate('/')

3. REQUÊTES SUIVANTES
   axios interceptor (api.js:3-7) injecte Authorization: Bearer {token}
   Backend Dependency get_current_user :
     - jwt.decode(token, SECRET_KEY, ['HS256'])
     - SELECT utilisateurs WHERE login = payload['sub']
     - vérifie user.actif == True
     - retourne l'objet Utilisateur (SQLAlchemy)

4. EXPIRATION / 401
   Backend renvoie 401 si :
     - JWT expiré (exp dépassé)
     - JWT invalide (signature, payload malformé)
     - utilisateur désactivé (actif=False)
     - utilisateur supprimé
   Axios interceptor (api.js:8-11) :
     - localStorage.removeItem('token')
     - window.location.href = '/login'  ← rechargement complet
```

**Tables lues** : `utilisateurs`.
**Tables modifiées** : aucune (note : `derniere_connexion` n'est **jamais mise à jour** alors que la colonne existe → fonctionnalité incomplète).

**Caractéristiques techniques** :
- **JWT 24h** (`auth.py:24`) au lieu de `Settings.ACCESS_TOKEN_EXPIRE_MINUTES=480` (8h non utilisé) — incohérence.
- **Stockage `localStorage`** : choix simple mais sensible XSS. Pour un module B2B interne, OK.
- **Pas de refresh token** : l'utilisateur est déconnecté brutalement après 24h.

**Points de friction** :
- Aucun verrouillage de compte après N tentatives échouées → vulnérable au brute-force.
- `password_hash` en VARCHAR(500) → bcrypt produit ~60 chars, mais place pour futures algos.
- Aucune notification de "session expirée bientôt" côté UI.

### Workflow 11 — Gestion des rôles (droits et filtrage d'affichage)

**Déclencheur** : un utilisateur navigue dans l'application.

**Code** : `AuthContext.js:7-35` (frontend) + `utilisateurs.py:17-22` (backend) — duplication des tables de droits.

**Rôles supportés** (depuis tag `v2.3.0` qui a supprimé `CONSULTANT` et ajouté `TECHNICIEN`) :

| Rôle | Droits effectifs | Vue par défaut | Particularité |
|---|---|---|---|
| `ADMIN` | tous | Dashboard complet | seul à pouvoir gérer Utilisateurs, Paramètres, vider cache |
| `GESTIONNAIRE` | tout sauf `parametres`, `utilisateurs` | Dashboard complet | équivalent ADMIN sur le métier |
| `FORMATEUR` | aucun droit listé | `/mes-prestations` | menu réduit à 3 entrées, redirigé si tente d'accéder à `/` (cf. `getForbiddenRedirect`) |
| `TECHNICIEN` | `contrats_lecture` uniquement | Dashboard simplifié | menu 5 entrées, accès lecture seule aux contrats |

**Mécanique** :

```
1. Côté backend
   - Le décorateur Depends(get_current_user) injecte le user
   - require_admin (utilisateurs.py:24) garde-fou pour les endpoints admin
   - Sinon : pas de check de rôle (cf. anti-pattern phase 3 #2)

2. Côté frontend
   - PrivateRoute.allow = (u) => u.role !== 'FORMATEUR' bloque par redirect
   - Layout.cleanMenu filtre les items selon droits[item.droit]
   - Plusieurs pages testent localement user.role ou droits.xxx avant
     d'afficher un bouton (ex : bouton "Supprimer modèle" en ADMIN)
```

**Effets de bord** : un FORMATEUR qui tape directement `/contrats` dans l'URL est **redirigé** vers `/mes-prestations`. Un TECHNICIEN qui tape `/parametres` est **redirigé** vers `/` (le predicate `allow={isNotFormateur}` le laisse passer côté route, mais Layout cache l'item dans le menu — et le backend renvoie 403 si tentative d'écriture).

**Points de friction** :
- Backend trust frontend (cf. anti-pattern phase 3 #2). Un TECHNICIEN motivé peut écrire sur `/api/contrats` directement avec son JWT.
- Pas de notion de **rôle multiple** : un utilisateur ne peut être qu'un seul rôle. Si un ADMIN doit aussi gérer ses prestations en tant que formateur, il faut lier `formateur_id`.
- La **suppression du rôle `CONSULTANT`** (v2.3.0) a été suivie d'aucune migration explicite. Si des utilisateurs `CONSULTANT` existaient en DB, `getDroitsByRole` les fait tomber dans le `default` (tout `false`) côté frontend, et `require_admin` les rejette côté backend.

### Workflow 12 — Nouveaux workflows apparus depuis l'audit v2.3.0

#### 12.1 — Dashboard refondu (tag `v2.4.2`, commit `2174640`)

**Déclencheur** : ouverture de `/`.

**Avant** : `Dashboard.js` faisait 3-4 appels distincts (`/api/contrats?statut=EN_COURS`, `/api/contrats/renouvellements`, `/api/commandes/stats`), agrégeait côté client, et boucle par famille.

**Après** :
- 1 seul endpoint backend `GET /api/dashboard/stats` (`dashboard.py:39`) qui retourne toutes les KPI agrégées.
- Côté frontend, `dashboardAPI.stats()` est appelé une seule fois.
- Le mapping `FAMILLE_LABELS` (8 entrées) est codé en dur côté backend ; le mapping `FAMILLE_META` (icônes/couleurs) est codé en dur côté frontend (cf. anti-pattern phase 5 #8).

**Effet de bord persistant** : `Dashboard.js:88-94` continue de lancer `POST /api/synchro/lancer` en arrière-plan au montage, ce qui peut déclencher une sync clients+articles complète (cf. anti-pattern phase 5 #5).

#### 12.2 — Sync devis Karlia avec rate-limit et retry (tags `v2.3.2` + `v2.4.5`)

**Évolution** : commits `99c0d9b` (fix paramètre `id_type → type`), `6e4e714` (sleep 1.2s + retry 429), `8cf0cf3` (rattrapage one-shot des 106 pdf_url manquants).

**Endpoint** : `POST /api/commandes/sync`.

**Mécanique nouvelle** :
- `KARLIA_SYNC_SLEEP_SECONDS=1.2` (`config.py:32`) entre chaque devis → 50 req/min max
- `_get_with_retry` (`karlia_devis_service.py:84`) : backoffs 5s/15s/30s sur 429 et erreurs réseau
- Compteurs étendus : `pdf_url_renseigne`, `pdf_url_absent`, `documents_rejetes_par_type`
- Défense en profondeur : rejet si `id_type != 1` côté Python (même si Karlia filtre déjà)

**Historique de l'incident traité** : `docs/DIAGNOSTIC_PDF_COMMANDES.md` (261 lignes) — sync du 20/05/2026 ayant créé 106 commandes avec `pdf_url=None`. Le script `scripts/rattrapage_pdf_url.py` (203 lignes) a corrigé via `get_devis_detail()` séquentiel.

#### 12.3 — Cleanup BC commandes (tag `v2.3.1`, commit `1045343`)

**Contexte** : 66 documents `BC*` (Bons de Commande, `id_type=2`) avaient été importés à tort en tant que `commandes` parce que l'ancien filtre Karlia `id_type=1` était silencieusement ignoré côté serveur (Karlia attend `type=1`).

**Script** : `scripts/cleanup_bc_commandes.py` (100 lignes) — exécuté hors container.

**Backup** : `backups/backup_pre_cleanup_bc_20260520_163107.sql` (git-ignoré) + `backups/deleted_bc_ids_20260520_164326.txt` (versionné, 66 IDs).

#### 12.4 — Factures Karlia en Brouillon (tags `v2.4.1` puis `v2.4.6.1`)

**Évolution** :
- Avant : `id_status=2` (Envoyée) → la facture était immédiatement envoyée au client
- `v2.4.1` (commit `34b2991`) : `id_status=1` (Brouillon) — validation manuelle requise
- `v2.4.6.1` (commit `ed3f9d5`, **non mergé sur main**) : `id_status=0` (Brouillon "non finalisé") sur **tous les chemins de facturation**

**Impact** : sécurise le workflow facturation — aucune facture ne part automatiquement sans relecture humaine dans Karlia.

#### 12.5 — Tri date_devis / date_acceptation (tag `v2.4.5`, commit `5887188`)

**Contexte** : la page `NouvellesCommandes` permet désormais de trier les commandes par date_devis et date_acceptation (avant : tri implicite par date_import uniquement).

**Endpoint impacté** : `GET /api/commandes/nouvelles` (et autres listes statut) supporte un paramètre `sort` côté frontend (paramètre côté backend pas systématiquement implémenté — à vérifier).

#### 12.6 — Service Google Calendar retiré

**Trace** : diff phase 0 montre `-44 lignes` sur `backend/app/services/google_calendar_service.py`. Le fichier n'existe plus.

**Impact** :
- La table `prestations` garde **5 colonnes orphelines** (cf. § 2.15).
- La table `formateurs.email_google` garde son sens (utilisable manuellement).
- Aucun workflow Google Calendar actif côté frontend (la page `MesPrestations` n'a aucune intégration calendrier).

**Trace dans la branche** : `feature/google-agenda-planning` existe sur origin mais pas mergée — c'est probablement la branche où le service avait été dévoloppé puis retiré.

#### 12.7 — Cleanup pdf_devis Base64 (tag `v2.4.6`, commit `f71d223`)

**Contexte** : le champ `commandes.pdf_devis` (déclaré `Text` dans `models.py` mais `bytea` en DB) recevait historiquement le PDF du devis encodé en base64. Ce mécanisme n'est plus utilisé depuis l'ajout de `pdf_url` qui pointe vers Karlia. Le commit retire le code mort.

**Impact résiduel** : la divergence type `models.py:Text` vs `DB:bytea` persiste (cf. divergence #4 phase 2).

---

## 7. Intégrations externes

> **Cette phase n'avait jamais été traitée dans l'audit v2.3.0**. Elle consolide toutes les intégrations externes du module avec un niveau de détail suffisant pour reconstruire chaque intégration en pré-refonte.

### 7.1 Karlia CRM (api v2)

#### 7.1.1 Identité de l'API

- **Base URL** : `https://karlia.fr/app/api/v2` (codée en dur dans `settings.KARLIA_API_URL`)
- **Version** : v2 (consommée par le module)
- **Authentification** : Bearer token statique (clé API personnelle générée dans Karlia)
- **Format** : JSON (`Content-Type: application/json`)
- **Documentation** : non publique côté Karlia, validation par essai/erreur en pré-prod
- **Quota** : **100 req/min** (signalé en code mais non documenté côté Karlia officiellement)

#### 7.1.2 Mécanisme de chargement de la clé API

La clé peut résider à **5 emplacements** différents :

| Source | Lieu | Priorité | Type |
|---|---|---|---|
| Fichier `.env` | `KARLIA_API_KEY=…` | défaut au boot | clé "fallback" |
| Pydantic Settings | `settings.KARLIA_API_KEY` (`config.py:13`) | défaut au boot | exposé à l'app |
| Table `parametres` | `karlia_api_key` (taille 34 chars en prod) | **canonique** | clé "live" |
| Instance globale | `karlia.api_key` (`karlia_service.py:34`) | mémoire | au boot puis surchargé par main.py |
| Variable locale | `karlia_devis_service.api_key` (`karlia_devis_service.py:45`) | mémoire | lu **une fois au boot** |

**Logique effective** :
1. `KarliaService.__init__` lit `settings.KARLIA_API_KEY` (depuis `.env`).
2. `main.py:155-164` au startup → relit depuis `parametres` et surcharge `karlia.api_key`.
3. `PUT /api/parametres/karlia-api-key` met à jour la DB **et** réécrit `karlia.api_key` en mémoire.
4. **MAIS** `KarliaDevisService.__init__` (`karlia_devis_service.py:43-45`) lit la DB une seule fois et **ne re-lit pas** lors d'une mise à jour live.
5. `clients.py:438` (BackgroundTask création contact) lit `settings.KARLIA_API_KEY` directement → ne reflète pas la clé courante.

**Conséquence** : une mise à jour de clé via `/api/parametres/karlia-api-key` :
- ✓ instantanée pour les workflows passant par l'instance `karlia` (facturation, sync clients, etc.)
- ✗ **pas prise en compte** par `karlia_devis_service` jusqu'à redémarrage du conteneur
- ✗ **pas prise en compte** par la création de contact en background (clients.py)

#### 7.1.3 Endpoints consommés

Le module appelle **10 endpoints distincts** Karlia :

| Endpoint | Méthode | Consommateur | Fréquence |
|---|---|---|---|
| `/company` | GET | `tester_connexion()` | manuelle |
| `/customers` | GET | sync clients (boot + cron + manuel) | 1 fois / 100 clients |
| `/customers/{id}` | GET | fallback détail, sync devis | rare |
| `/customers` | POST | création client | rare |
| `/products` | GET | sync articles + recherche live | sync ≈ 1×/jour |
| `/products/{id}` | GET | déclaré, **non utilisé** | — |
| `/products/{id}/sell-price` | GET | déclaré, **non utilisé** | — |
| `/documents` | GET | sync factures (Chorus) + sync devis | manuel |
| `/documents/{id}` | GET | détail devis dans sync | par devis |
| `/documents` | POST | **émission facture** (Syntec + commande) | sur action utilisateur |
| `/documents/templates` | GET | déclaré, **non utilisé** | — |
| `/opportunities/{id}` | GET | check opportunity "Traité" | par devis avec opp |
| `/opportunities/{id}/custom-fields/66505` | POST | marquage "Traité" | par nouveau devis |
| `/contacts` | POST | création contact principal (background) | par création client |

#### 7.1.4 Rate-limit et gestion des erreurs

| Service | Stratégie 429 | Stratégie autres erreurs |
|---|---|---|
| `karlia_service` (générique) | aucun retry → `KarliaError(429, "Quota dépassé")` | `KarliaError(status, detail)` |
| `karlia_service.traitement_lot_factures` | `delai_entre_requetes=0.8s` codé en dur (~75 req/min), pas de retry | `KarliaError` capturée, plan en `ERREUR` |
| `karlia_devis_service` | `_get_with_retry` : 3 retries 5s/15s/30s sur 429 et erreurs réseau | log error + `return None` (non bloquant) |
| `main.py::synchro_karlia` (sync clients/articles) | aucun retry, catch global `print("Erreur : …")` | journal stdout |

**Garde-fous applicatifs** :
- `settings.KARLIA_MAX_REQUESTS_PER_MINUTE = 80` (config.py:30) — **constante déclarée mais jamais utilisée** dans le code (probablement vestige).
- `settings.KARLIA_SYNC_SLEEP_SECONDS = 1.2` (config.py:32) — utilisé **uniquement** par `karlia_devis_service`.

#### 7.1.5 Format payload facture — exemple validé en production

```json
{
  "id_customer": 12345,
  "id_type": 4,
  "id_status": 1,
  "reference": "CO-2025-001",
  "date": "21/05/2026",
  "date_end": "31/05/2026",
  "description": "Facturation 2026 — Contrat CO-2025-001",
  "products_list": [
    {
      "id_product": "K42",
      "price_without_tax": 1500.00,
      "quantity": 1,
      "id_vat": "1"
    },
    {
      "description": "Maintenance complémentaire (ligne libre)",
      "price_without_tax": 250.00,
      "quantity": 2,
      "id_vat": "1"
    }
  ]
}
```

Caractéristiques :
- `id_customer` : entier (pas string) — converti par `int(client_karlia_id)`
- `id_type` : codes documents Karlia
  - `1` = Devis
  - `2` = Bon de commande
  - `4` = **Facture** (utilisé)
  - autres : utilisés selon le contexte mais non documentés
- `id_status` :
  - `0` = Brouillon non finalisé (cible cible v2.4.6.1, branche non mergée)
  - `1` = Brouillon (état actuel sur main, depuis v2.4.1)
  - `2` = Envoyée (ancien comportement avant v2.4.1)
- `date`, `date_end` : format **dd/MM/yyyy** (français), pas ISO
- `products_list` : array de lignes, chacune avec **soit** `id_product` (Karlia affiche le nom du catalogue automatiquement), **soit** `description` (fallback ligne libre)

Retour Karlia :

```json
{
  "id": 678901,
  "reference": "F2026-0042",
  "id_customer": 12345,
  ...
}
```

Le module persiste `karlia_doc_id = id`, `karlia_doc_ref = reference` (`karlia_service.py:278-279`).

#### 7.1.6 Codes `id_vat` Karlia

```python
# karlia_service.py:192-195
if tva >= 20: id_vat = "1"   # 20%
elif tva >= 10: id_vat = "2" # 10%
elif tva >= 5: id_vat = "3"  # 5.5%
else: id_vat = "4"           # 0% / exonéré
```

**Limites** :
- TVA 8.5%, 2.1% (DOM-TOM, presse) → mappent toutes sur `id_vat=4` (faux)
- Si Karlia ajoute un `id_vat=5` (taux intermédiaire), il faudra le coder manuellement

#### 7.1.7 Mapping local ↔ Karlia

| Entité locale | Champ pivot | Champ Karlia |
|---|---|---|
| `clients_cache.karlia_id` | `Customer.id` (entier en string) | identifiant client |
| `clients_cache.numero_client` | `Customer.client_number` | numéro métier (ex `DUM048`) |
| `articles_cache.karlia_id` | `Product.id` (entier en string) | identifiant article |
| `contrat_articles.article_karlia_id` | `Product.id` | référence catalogue |
| `commandes.karlia_document_id` | `Document.id` (Devis) | id devis Karlia |
| `commandes.karlia_customer_id` | `Document.id_customer_supplier` | id client lié au devis |
| `commandes.karlia_opportunity_id` | `Document.id_opportunity` | opportunité commerciale |
| `commande_lignes.karlia_product_id` | `Product.id` | ligne devis |
| `plan_facturation.facture_karlia_id` | `Document.id` (Facture) | facture émise |
| `plan_facturation.facture_karlia_ref` | `Document.reference` | référence facture |
| `factures_karlia.karlia_document_id` | `Document.id` (Facture) | facture importée |
| `commandes.facture_karlia_id/ref` | idem | facture commande |

#### 7.1.8 Champs Karlia notables

- **Custom field `66505`** sur l'objet `Opportunity` = case à cocher "Traité" utilisée par le module pour marquer qu'un devis a été importé. **Hardcodé** dans `karlia_devis_service.py:36`.
- `Customer.address_list` : array d'adresses, le module ne lit que celle de `type="main"`.
- `Product.sell_price.price` : prix HT — le module passe par `obtenir_prix_vente` jamais utilisé en pratique, lit directement `sell_price.price` dans la sync.

### 7.2 Chorus Pro via PISTE

#### 7.2.1 Identité de l'API

- **URLs OAuth** :
  - Sandbox : `https://sandbox-oauth.piste.gouv.fr/api/oauth/token`
  - Production : `https://oauth.piste.gouv.fr/api/oauth/token`
- **URLs API Chorus** :
  - Sandbox : `https://sandbox-api.piste.gouv.fr/cpro/factures/v1`
  - Production : `https://api.piste.gouv.fr/cpro/factures/v1`
- **Bascule sandbox/prod** : via paramètre DB `chorus_mode_qualification` (booléen string `'true'`/`'false'`)
- **Format** : JSON (`application/json`)
- **Standard** : Norme Factur-X / Chorus Pro API v1

#### 7.2.2 Compte technique et credentials

Les 8 paramètres stockés en table `parametres` (cf. § 2.12) :

| Clé | Rôle | Type | Masquage frontend |
|---|---|---|---|
| `chorus_client_id` | Client ID OAuth2 PISTE | UUID 36 chars | non |
| `chorus_client_secret` | Client Secret OAuth2 PISTE | secret 36 chars | **`••••••••`** |
| `chorus_tech_username` | Login compte technique Chorus Pro | format `TECH_1_xxx@cpro.fr` | non |
| `chorus_tech_password` | Mot de passe compte technique | secret 13 chars (court !) | **`••••••••`** |
| `chorus_siret_emetteur` | SIRET de la structure émettrice | 14 chiffres | non |
| `chorus_code_service` | Code service fournisseur (optionnel) | texte | non |
| `chorus_code_banque` | Code coordonnées bancaires (optionnel) | texte | non |
| `chorus_mode_qualification` | Sandbox actif | `'true'`/`'false'` | non |

> **Sécurité — observation critique** : le `chorus_tech_password` constaté en prod ne fait que **13 caractères**. Si c'est bien la valeur réelle, c'est en deçà des recommandations PISTE (12+ recommandés, mais souvent 16+ pour les comptes techniques). À durcir.

> **Sécurité — stockage** : tous ces paramètres sont stockés **en clair** dans la table `parametres.valeur` (TEXT). En cas de fuite de la DB, le compte technique Chorus Pro est compromis. À migrer vers un gestionnaire de secrets (Secret Manager GCP).

#### 7.2.3 Flux OAuth2 — particularité PISTE

**Le mécanisme d'authentification de PISTE est non standard** et c'est ce qui distingue Chorus Pro des autres API OAuth2 classiques :

```python
# chorus_service.py:76-92
credentials = base64.b64encode(f"{tech_username}:{tech_password}".encode()).decode()

response = await client.post(
    self.oauth_url,
    data={
        "grant_type": "client_credentials",
        "scope": "openid",
    },
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {credentials}",     # ← (1) header Basic
    },
    auth=(self.client_id, self.client_secret)        # ← (2) httpx Basic auth
)
```

**Deux authentifications simultanées** :
1. **Header `Authorization: Basic base64(tech_username:tech_password)`** → identifie l'**utilisateur Chorus Pro** qui va déposer la facture
2. **httpx `auth=(client_id, client_secret)`** → équivaut à `Authorization: Basic base64(client_id:client_secret)` (mais httpx écrase le header précédent normalement…)

⚠️ **Anomalie probable** : `httpx` applique normalement `auth=` en réécrivant le header `Authorization`. Donc **seul (2) part dans la requête réelle** et `(1)` est écrasé. C'est probablement le bug à la source du blocage 403 noté en mémoire ([[chorus_pro_blocage]]).

**Vérification recommandée** : passer les credentials techniques dans un autre header (custom comme `X-Cpro-Username` ou `Cpro-Account`), comme demandé par la spec PISTE.

#### 7.2.4 Endpoints PISTE consommés

| Endpoint | Méthode | Usage |
|---|---|---|
| `/api/oauth/token` | POST | obtenir access_token (cache 55 min) |
| `/cpro/factures/v1/rechercher/structures` | POST | recherche structure destinataire par SIRET |
| `/cpro/factures/v1/consulter/structure` | POST | détails structure |
| `/cpro/factures/v1/rechercher/services` | POST | services d'une structure |
| `/cpro/factures/v1/soumettre` | POST | **soumission facture** |
| `/cpro/factures/v1/consulter/facture` | POST | suivi statut facture |
| `/cpro/factures/v1/rechercher/factures/fournisseur` | POST | listing factures émises |

#### 7.2.5 Format payload `/soumettre` — analyse détaillée

```json
{
  "modeDepot": "SAISIE_API",
  "numeroFactureSaisi": "8918",
  "destinataire": {
    "codeDestinataire": "21620195400015",
    "codeServiceExecutant": null
  },
  "fournisseur": {
    "typeIdentifiantFournisseur": "SIRET",
    "identifiantFournisseur": "11111111111111",
    "codeServiceFournisseur": null,
    "codeCoordonneesBancairesFournisseur": null
  },
  "cadreDeFacturation": {
    "codeCadreFacturation": "A1_FACTURE_FOURNISSEUR",
    "codeStructureValideur": null
  },
  "references": {
    "deviseFacture": "EUR",
    "typeFacture": "FACTURE",
    "typeTva": "TVA_SUR_DEBIT",
    "motifExonerationTva": null,
    "numeroMarche": null,
    "numeroEngagement": null,
    "numeroBonCommande": null,
    "numeroFactureOrigine": null,
    "modePaiement": "VIREMENT",
    "dateFacture": "2026-05-21"
  },
  "lignePoste": [
    {
      "lignePosteNumero": 1,
      "lignePosteReference": "GLOBAL",
      "lignePosteDenomination": "Facture 8918",
      "lignePosteQuantite": 1,
      "lignePosteUnite": "lot",
      "lignePosteMontantUnitaireHT": 1500.0,
      "lignePosteMontantRemiseHT": 0,
      "lignePosteTauxTva": 20.0,
      "lignePosteTauxTvaManuel": null
    }
  ],
  "ligneRecapitulatifTVA": [
    {
      "ligneRecapTvaTauxManuel": null,
      "ligneRecapTvaTaux": 20.0,
      "ligneRecapTvaMontantBaseHtParTaux": 1500.0,
      "ligneRecapTvaMontantTvaParTaux": 300.0
    }
  ],
  "montantTotal": {
    "montantHtTotal": 1500.0,
    "montantTvaTotal": 300.0,
    "montantTtcTotal": 1800.0,
    "montantRemiseGlobaleTTC": 0,
    "motifRemiseGlobaleTTC": null,
    "montantAPayer": 1800.0,
    "montantAcompte": 0
  },
  "commentaire": "Facture 8918"
}
```

**Constats** :
- `modeDepot: "SAISIE_API"` — dépôt manuel via API (vs `IMPORT_PDF` ou `IMPORT_XML_CHORUS`)
- `cadreDeFacturation: "A1_FACTURE_FOURNISSEUR"` — cadre obligatoire (facture simple sans marché)
- `typeTva: "TVA_SUR_DEBIT"` **codé en dur** — n'autorise pas la TVA sur encaissements
- `modePaiement: "VIREMENT"` **codé en dur**
- Le payload courant **n'envoie qu'une seule ligne** récapitulative (20 %), même si la facture a plusieurs taux TVA → bug à corriger pour les factures mixtes

#### 7.2.6 Statuts factures (états Chorus Pro)

##### Côté DB locale (`factures_karlia.statut_chorus`)

CHECK constraint : `IN ('NON_TRANSMISE', 'EN_COURS', 'TRANSMISE', 'ACCEPTEE', 'REJETEE', 'ERREUR')`.

| Statut | Sens | Transition vers |
|---|---|---|
| `NON_TRANSMISE` | Importée depuis Karlia, jamais transmise | → `EN_COURS` (lors du POST `/transmettre`) |
| `EN_COURS` | Transmission en cours | → `TRANSMISE` (succès) ou `ERREUR` |
| `TRANSMISE` | Acceptée par PISTE (numeroFluxDepot reçu) | → `ACCEPTEE` ou `REJETEE` (à terme, par polling — pas en place) |
| `ACCEPTEE` | Acceptée par la collectivité destinataire | terminal |
| `REJETEE` | Rejetée par la collectivité destinataire | terminal |
| `ERREUR` | Échec technique (réseau, 4xx, 5xx) | manuel : retry possible |

##### Côté DB locale (`transmissions_chorus.statut`)

CHECK constraint : `IN ('EN_ATTENTE', 'EN_COURS', 'SUCCES', 'ECHEC', 'ANNULE')`.

| Statut | Sens |
|---|---|
| `EN_ATTENTE` | Créée mais pas encore tentée |
| `EN_COURS` | Appel API en cours |
| `SUCCES` | Réponse 200 PISTE avec `numeroFluxDepot` |
| `ECHEC` | Erreur HTTP ou exception |
| `ANNULE` | Annulation manuelle (non implémentée à ce jour) |

#### 7.2.7 Snapshot DB Chorus en production (21/05/2026)

```
factures_karlia (15 lignes) :
  NON_TRANSMISE : 13
  TRANSMISE     :  1
  ERREUR        :  1

transmissions_chorus (4 lignes) :
  ECHEC | code_retour=0   | "idFournisseur manquant — paramètre 'chorus_id_fournisseur' vide en base"  | 2026-05-16
  ECHEC | code_retour=400 | "Erreur sur /soumettre"                                                   | 2026-04-23
  ECHEC | code_retour=400 | "Erreur sur /soumettre"                                                   | 2026-04-22
  ECHEC | code_retour=400 | "Erreur sur /soumettre"                                                   | 2026-04-22
```

> **Observation forte** : aucune transmission `SUCCES` n'est enregistrée dans `transmissions_chorus`, mais 1 facture est en `TRANSMISE` côté `factures_karlia`. **Désynchronisation** des deux tables — probablement parce que la facture a été marquée TRANSMISE manuellement en DB ou via une version antérieure du code qui ne créait pas systématiquement la trace `TransmissionChorus`. La messagerie d'erreur `idFournisseur manquant` confirme que la configuration n'est pas complète (cf. `chorus_id_fournisseur` vide dans `parametres`).

#### 7.2.8 Masquage frontend

Le frontend (`pages/Parametres.js`) :
- **Affiche en clair** : `chorus_client_id`, `chorus_tech_username`, `chorus_siret_emetteur`, `chorus_code_service`, `chorus_code_banque`, `chorus_mode_qualification`
- **Affiche `••••••••`** : `chorus_client_secret`, `chorus_tech_password`
- À l'enregistrement, si la valeur envoyée vaut `••••••••`, le backend **ignore** le champ (cf. `parametres.py:140-142`) → l'utilisateur n'écrase pas accidentellement un secret.

> **Limite** : tout utilisateur connecté (pas seulement ADMIN) peut **lire** les valeurs non masquées via `GET /api/parametres/chorus` (cf. § 3.7). Seul l'écriture est restreinte à ADMIN.

### 7.3 Google Calendar — service retiré

#### 7.3.1 État actuel

- **Service backend** : `backend/app/services/google_calendar_service.py` → **fichier supprimé** (diff phase 0 montre `-44 lignes`).
- **Endpoints API** : aucun endpoint actif dans `backend/app/api/`.
- **Branche source historique** : `feature/google-agenda-planning` existe sur origin mais n'a jamais été mergée.
- **Configuration `.env`** : aucune variable `GOOGLE_*` n'apparaît dans `.env` ni dans `config.py`.

#### 7.3.2 Traces résiduelles

##### Schéma DB

5 colonnes dans `prestations` (cf. § 2.15) :
- `prestations.google_event_id` — ID de l'événement Google Calendar
- `prestations.google_calendar_id` — ID du calendrier (DB only, pas dans models.py)
- `prestations.google_sync_status` — statut sync (DB only)
- `prestations.google_sync_error` — message d'erreur (DB only)
- `prestations.google_synced_at` — date dernière sync (DB only)

1 colonne dans `formateurs` :
- `formateurs.email_google` — email du compte Google associé au formateur (gérée par `formateurs.py` et `Formateurs.js`)

##### Code orphelin
- `models.py:482` : `google_event_id = Column(String(255))` — déclaration ORM
- `prestations.py:60-100` : `google_event_id` dans la response Pydantic
- `formateurs.py:20,38,76,…` : `email_google` dans tous les schémas Pydantic
- `Formateurs.js` : champ `email_google` dans le formulaire de création/édition de formateur

#### 7.3.3 Périmètre supposé de l'ancien service (déduit du schéma)

Le service supprimé semblait :
1. **OAuth2 Google** : autoriser le module à publier dans le calendrier de chaque formateur (scope `https://www.googleapis.com/auth/calendar.events`)
2. **Stockage des tokens** : probablement dans la table `parametres` (clé hypothétique `google_oauth_token`) ou dans un fichier local — **aucune trace en DB aujourd'hui**.
3. **Synchronisation des prestations** : pour chaque prestation `planifiee`, créer un événement Google Calendar dans le calendrier du formateur (date_planifiee + heure_debut/heure_fin + lieu), stocker l'ID retourné dans `google_event_id`.
4. **Mise à jour bidirectionnelle** : peut-être un endpoint pour modifier/supprimer l'événement quand la prestation change.

#### 7.3.4 Questions ouvertes pour la refonte

- Faut-il **purger** les colonnes `google_*` et `email_google` du schéma DB ?
- Faut-il **réactiver** la sync Google Calendar avec un nouveau client OAuth2 ?
- Faut-il **basculer** vers un autre fournisseur de calendrier (Outlook Graph API, CalDAV, calendrier interne du module) ?
- Faut-il **abandonner** la planification calendrier au profit d'un export ICS téléchargeable par formateur (solution low-tech) ?

### 7.4 Autres intégrations externes potentielles

#### 7.4.1 Cloudflare Tunnel

Le module est accessible depuis l'extérieur via un Cloudflare Tunnel (mentionné dans le commit `a8690b7`, tag `v2.4.0` : "accès externe via Cloudflare Tunnel — CORS ajouté"). Cette intégration est **infrastructure**, pas applicative — aucun code du module ne dialogue avec Cloudflare. Le seul impact côté code est la liste `CORS_ORIGINS` qui inclut `https://gestion.sginformatique.fr`.

#### 7.4.2 INSEE / Syntec

Les indices Syntec sont **saisis manuellement** dans `/indices` (`pages/Indices.js`). Le champ `IndiceRevision.source_url` permet de stocker l'URL INSEE de référence (publié sur l'INSEE) mais aucune intégration automatique n'existe. À envisager pour la refonte : sync automatique depuis les pages INSEE Syntec.

#### 7.4.3 Email / Notifications

Aucun service d'envoi d'email ne fait partie du module. Pas de SMTP, pas d'API SendGrid/Mailgun/etc. Les notifications sont **uniquement** affichées via `react-hot-toast` côté UI. Pour une refonte : envisager les notifications pour facturation, renouvellements, ou alertes Chorus Pro.

#### 7.4.4 Stockage objet (S3 / GCS)

Pas de stockage objet. Les fichiers (modèles Word, documents générés, PDF devis Karlia) sont stockés :
- Sur bind-mount disque (`storage/modeles/`, `storage/documents_generes/`)
- Sur Karlia côté distant (URLs `pdf_url` pour devis)

Pour la migration GCP, prévoir une bascule vers GCS pour la durabilité et la scalabilité (cf. § 8).

---

## 8. État des lieux et perspectives (préparation refonte / migration GCP)

> **Cette phase n'avait jamais été traitée dans l'audit v2.3.0**. Elle synthétise les phases 1-7 sous forme de bilan : ce qui est solide, ce qui est partiel, ce qui est de la dette, et ce qu'il faut prévoir pour une migration vers Google Cloud Platform.

### 8.1 Fonctionnalités complètement opérationnelles

Fonctionnalités vues fonctionner en production avec des données réelles (volumétrie cf. § 2.1) :

| Domaine | État | Volumétrie / preuve |
|---|---|---|
| **Authentification JWT** | ✓ stable | 8 utilisateurs actifs, 4 rôles, login/logout opérationnel |
| **Synchronisation clients Karlia** | ✓ stable | 251 clients en cache, sync boot + cron 02:00 |
| **Synchronisation articles Karlia** | ✓ stable | 404 articles en cache |
| **Création de contrats (tunnel 4 étapes)** | ✓ stable | 572 contrats en base, tous `EN_COURS CONTRAT` |
| **Plan de facturation prévisionnel** | ✓ stable | 1150 lignes `plan_facturation` |
| **Calcul prorata an1 (avec demi-mois)** | ✓ stable | logique métier figée |
| **Gestion des indices Syntec** | ✓ stable | 6 indices saisis, écran Indices |
| **Familles de contrats + règles de révision** | ✓ stable | 7 familles, 4 règles (SYNTEC_AOUT / OCTOBRE / MANUELLE / AUCUNE) |
| **Renouvellement SPONTANE + FIN (multi-sélection)** | ✓ stable | logique testée, tag `v2-renouvellements-multi-selection` |
| **Émission de factures Karlia (Brouillon)** | ✓ stable | depuis tag `v2.4.1` |
| **Sync devis Karlia → commandes** | ✓ stable depuis `v2.4.5` | rate-limit + retry consolidés après incident 20/05 |
| **Workflow commande sans planification** | ✓ stable | majorité des commandes l'utilisent |
| **Workflow commande avec planification + formateur** | ✓ stable | 1 + 4 + 6 = 11 prestations |
| **Dashboard refondu (endpoint unique)** | ✓ stable depuis `v2.4.2` | `/api/dashboard/stats` |
| **Filtre par famille sur écran Renouvellements** | ✓ stable | tag `v2-renouvellements-filtre-famille` |
| **Cycle de vie contrats : BROUILLON → EN_COURS → TERMINE** | ✓ stable | seul `EN_COURS` actuellement en prod (572) |
| **Gestion utilisateurs + droits par rôle (frontend)** | ✓ stable | tableau DROITS appliqué au menu |
| **Gestion des formateurs (CRUD)** | ✓ stable | 7 formateurs |
| **Cleanup BC commandes (one-shot)** | ✓ exécuté | `v2.3.1`, 66 lignes supprimées, backup conservé |

### 8.2 Fonctionnalités partielles ou hooks à compléter

#### 8.2.1 Tables et endpoints fantômes

| Élément | État | Action requise |
|---|---|---|
| `lots_facturation` | **0 ligne en prod**, jamais alimentée | persister lots ou retirer table + endpoint stub `/api/facturation/lot/{id}` |
| `GET /api/facturation/lot/{id}` | endpoint stub retourne `{statut: "TERMINE"}` toujours | aligner avec `lots_facturation` ou retirer |
| `documents_generes` | **1 ligne** pour 572 contrats | génération Word à promouvoir ou à retirer |
| `karlia_service.obtenir_produit` / `obtenir_prix_vente` / `lister_templates_documents` | déclarées, jamais appelées | code mort, supprimer |
| `karlia_service.lister_types_documents` | utilitaire de debug | OK à garder pour outillage |
| `contrat_service.calculer_montant_revise` | dupliquée par `revision_service` | supprimer |
| `contrat_service.calculer_statut_renouvellement` | jamais appelée | supprimer ou activer pour le dashboard |
| `commandes.statut = 'terminee'` | code path existe (commandes.py:367) mais jamais affiché en liste | retirer ou unifier avec `deployee` |
| `pages/NouveauContrat.js` | probablement remplacée par `TunnelContrat` | retirer si confirmé |

#### 8.2.2 Workflows à finaliser

| Workflow | Manque |
|---|---|
| **Polling statut Chorus Pro** | aucun mécanisme ne met à jour `factures_karlia.statut_chorus` après le passage à `TRANSMISE` (pas de transition vers `ACCEPTEE`/`REJETEE`) |
| **Polling validation Karlia** | aucun mécanisme ne détecte qu'une facture émise en Brouillon a été validée puis envoyée dans Karlia |
| **Notifications email** | aucun envoi (renouvellements proches, échec Chorus, etc.) |
| **Mise à jour `utilisateurs.derniere_connexion`** | colonne déclarée, jamais alimentée |
| **Audit-trail des renouvellements** | seule trace = `motif_fin` en texte libre |
| **Calendrier formateurs** | Google Calendar retiré, rien en place |

#### 8.2.3 Hooks de validation incomplets

- `valider_pre_emission` (validation_service.py:153) **jamais appelée** par `/api/facturation/lancer` (anti-pattern phase 4 #9)
- Aucune validation en amont de `POST /api/commandes/{id}/facturer` (commandes terminées)
- Aucune validation en amont de `POST /api/chorus/transmettre` au-delà du `client_siret IS NOT NULL`

#### 8.2.4 Traces de TODO/FIXME en code

Recherche exhaustive `grep -rnE "TODO|FIXME|XXX|HACK|TBD"` dans `backend/app/` et `contrats-ui-src/src/` : **aucun résultat**.

Ce n'est pas un signe de propreté : les anti-patterns identifiés (cf. phases 4 #1-13 et 5 #1-14) ne sont **pas marqués** dans le code. Le suivi de la dette technique se fait uniquement via les **branches non mergées** sur origin (18 branches dormantes), les **messages de commit**, et les **notes en mémoire** (cf. `chorus_pro_blocage`, `versioning_baseline`).

> **Recommandation refonte** : adopter un marqueur de dette `# TODO(refonte):` ou intégrer un outil comme `todocheck` au CI pour rendre visible la dette résiduelle.

### 8.3 Dette technique identifiée

Synthèse cross-phase. Chaque ligne renvoie à la phase qui l'a décrite en détail.

#### 8.3.1 Schéma DB et ORM

| Item | Phase | Sévérité |
|---|---|---|
| 8 divergences `models.py` ↔ DB live (types, colonnes orphelines) | § 2.19 | élevée |
| Alembic dans requirements mais jamais câblé (toutes migrations à la main) | § 1.6 | **élevée** |
| `prestations` : 5 colonnes Google Calendar orphelines | § 2.15 | moyenne |
| `commande_lignes` : 3 colonnes `discount_*` non déclarées dans ORM | § 2.14 | moyenne |
| `commandes.pdf_devis` : `Text` (ORM) vs `bytea` (DB) | § 2.13 | élevée |
| Dates `timestamp without time zone` côté DB vs `timezone=True` côté ORM | § 2.13 | moyenne |
| `clients_cache.numero_client unique=True` côté ORM, pas en DB | § 2.2 | basse |
| `lots_facturation` 0 ligne et endpoint stub fictif | § 8.2.1 | basse |

#### 8.3.2 Backend / API

| Item | Phase | Sévérité |
|---|---|---|
| Aucune transaction explicite, commits intermédiaires | § 3.17 | **élevée** |
| Droits backend non vérifiés sur la majorité des endpoints (gating frontend uniquement) | § 3.2 | **élevée** |
| JWT 24h codé en dur (`Settings.ACCESS_TOKEN_EXPIRE_MINUTES=480` non utilisé) | § 3.2 | moyenne |
| `chorus.py` cumule `prefix="/chorus"` interne + `prefix="/api"` externe | § 3.1 | basse |
| `renouveler-lot` commit par contrat → pas de transaction globale | § 3.3 | moyenne |
| `app.version="1.0.0"` désynchronisée des tags git `v2.4.6` | § 3.16 | basse |
| `valider_pre_emission` jamais appelé | § 4.10 #9 | **élevée** |
| Pas de retry sur 429 dans `traitement_lot_factures` | § 4.10 #4 | moyenne |
| Cascade implicite prestation → commande non documentée | § 3.15 | moyenne |

#### 8.3.3 Services métier

| Item | Phase | Sévérité |
|---|---|---|
| Clé API Karlia lue à **5 endroits** différents | § 4.10 #1, § 7.1.2 | **élevée** |
| `karlia_devis_service` lit la clé **une seule fois** au boot | § 4.10 #2, § 7.1.2 | élevée |
| `clients.py:438` BackgroundTask utilise `settings.KARLIA_API_KEY` au lieu de la clé courante | § 3.8 | moyenne |
| `karlia_devis_service._create_commande` raw SQL devenu obsolète | § 4.10 #5 | basse |
| Mapping `id_vat` Karlia plafonné à 4 codes | § 7.1.6 | moyenne |
| Famille `CITYWEB` dans Dashboard mais pas dans `FAMILLES_CONTRAT` | § 4.10 #8 | basse |
| `chorus_service` : **double auth** (Basic header + `auth=`) écrasement probable | § 4.10 #11, § 7.2.3 | **critique** |
| `chorus_service` : `typeTva` codé en dur | § 4.10 #10 | moyenne |
| `chorus_service` : 1 seule ligne récapitulative TVA même pour multi-taux | § 7.2.5 | moyenne |
| Singleton `karlia` modifié à chaud → race conditions possibles sur scale | § 4.1 | élevée |

#### 8.3.4 Frontend React

| Item | Phase | Sévérité |
|---|---|---|
| CRA en mode maintenance depuis 2024 | § 5.9 #1 | élevée |
| Aucun test frontend (testing-library installé non utilisé) | § 5.9 #2 | élevée |
| 3 libs UI installées jamais utilisées (~300 ko) | § 5.7, § 5.9 #3 | moyenne |
| Double source de vérité droits (backend + AuthContext) | § 5.3, § 5.9 #4 | élevée |
| Dashboard lance sync Karlia silencieuse au montage | § 5.9 #5 | moyenne |
| `TunnelContrat` : 18 `useState` indépendants → manque store | § 5.9 #7 | moyenne |
| Mélange `api.get` direct + helpers `xAPI.*` | § 5.9 #6 | moyenne |
| Pas de TypeScript | § 5.9 #14 | dépend ambition |
| Emojis comme icônes | § 5.9 #9 | basse |
| TZ Paris : règle `T12:00:00` non systématique | § 5.9 #12 | moyenne |
| `pages/NouveauContrat.js` probablement obsolète | § 5.9 #11 | basse |
| Aucun composant `Pagination` partagé | § 5.9 #10 | basse |

#### 8.3.5 Sécurité

| Item | Phase | Sévérité |
|---|---|---|
| Secrets en clair dans `parametres` (`karlia_api_key`, `chorus_client_secret`, `chorus_tech_password`) | § 2.12, § 7.2.2 | **critique** |
| `chorus_tech_password` à 13 chars en prod | § 7.2.2 | moyenne |
| `GET /api/parametres/` accessible à tout utilisateur connecté (pas seulement ADMIN) — révèle des paramètres Chorus non masqués | § 3.7 | moyenne |
| Aucun verrouillage de compte après N tentatives échouées | § 6 (workflow 10) | moyenne |
| `localStorage.token` (vulnérable XSS) | § 5.3 | basse (intranet B2B) |
| Backend en `uvicorn --reload` (anti-pattern prod) | § 1.2 | moyenne |
| Pas de chiffrement TLS sur le port 80 (délégué Cloudflare Tunnel) | § 1.3 | basse |

#### 8.3.6 Opérations

| Item | Phase | Sévérité |
|---|---|---|
| Sync Karlia au boot bloquante → bouclage si Karlia down | § 1.8 | élevée |
| APScheduler in-process → incompatible scale horizontale | § 1.8 | élevée |
| Aucun backup automatique côté module (snapshots VM uniquement) | § 1.5 | élevée |
| Aucun système de log centralisé / agrégé / Sentry | § 5.4 | moyenne |
| Aucun monitoring applicatif (uptime, latence, erreurs) | — | moyenne |
| `print()` utilisés pour logs critiques (`main.py:67,89,…`) | § 1.8 | basse |
| 18 branches obsolètes sur origin | § 1.10 | basse |
| Tags désordonnés (`v2.4.2 → v2.4.5` volontaire) | § 1.10 (mémoire) | n/a |

### 8.4 Préparation à la migration GCP

Hypothèse : la migration cible **Google Cloud Platform** avec services managés (Cloud Run + Cloud SQL + Cloud Storage + Secret Manager + Cloud Build). Le module doit donc être adapté pour ces environnements.

#### 8.4.1 Cible architecturale recommandée

```
Utilisateur ──HTTPS──► Cloud CDN / Load Balancer
                            │
                            ├── frontend (Cloud Storage + Cloud CDN)
                            │   ou Cloud Run conteneur statique
                            │
                            └── backend (Cloud Run)
                                  │
                                  ├── Cloud SQL PostgreSQL 16
                                  ├── Cloud Storage (modèles, documents)
                                  ├── Secret Manager (clé Karlia, Chorus, JWT)
                                  ├── Cloud Logging (logs structurés)
                                  ├── Cloud Scheduler (jobs cron Karlia)
                                  └── Cloud Tasks (jobs async Karlia/Chorus)
```

#### 8.4.2 Migration des données — PostgreSQL → Cloud SQL

**Volumétrie actuelle** : DB = **13 MB**. Cloud SQL absorbe sans difficulté.

**Marche à suivre** :
1. **Préalable : passer à Alembic** (cf. dette technique 8.3.1). Sans migrations versionnées, la migration est risquée.
2. **Aligner `models.py` avec la DB** pour repartir d'un schéma propre (résoudre les 8 divergences phase 2).
3. **Dump** : `pg_dump --no-owner --no-privileges contrats > dump.sql`
4. **Import** : créer instance Cloud SQL PostgreSQL 16, configurer la connexion via Cloud SQL Proxy, importer le dump.
5. **Connexion** : `DATABASE_URL` en variable d'environnement Cloud Run, utilisant l'instance Cloud SQL Connector.

**Garde-fous à anticiper** :
- Cloud SQL force **TLS** par défaut — adapter la string `DATABASE_URL` avec `sslmode=require`.
- L'utilisateur `contrats` actuel doit être recréé côté Cloud SQL avec un mot de passe géré via Secret Manager.
- Penser à activer **Point-in-Time Recovery** (backups automatiques 7 jours) — comble la lacune backup actuelle (cf. dette 8.3.6).

#### 8.4.3 Migration des secrets — `parametres` clair → Secret Manager

**Secrets actuellement en clair dans la table `parametres`** (cf. § 7.2.2) :
- `karlia_api_key`
- `chorus_client_secret`
- `chorus_tech_password`

Plus dans `.env` : `SECRET_KEY` (JWT), `DB_PASSWORD`.

**Plan** :
1. Créer 5 secrets dans **Google Secret Manager** : `karlia-api-key`, `chorus-client-secret`, `chorus-tech-password`, `jwt-secret-key`, `db-password`.
2. Modifier `config.py` pour les lire via le client `google-cloud-secret-manager` (cache 5 min recommandé pour éviter le coût par accès).
3. Modifier `chorus_service.get_chorus_service_from_params` pour ne plus lire les secrets depuis `parametres` mais directement depuis Secret Manager.
4. **Conserver** dans `parametres` uniquement les paramètres **non secrets** : `chorus_client_id`, `chorus_tech_username`, `chorus_siret_emetteur`, `chorus_code_*`, `chorus_mode_qualification`, `derniere_synchro*`, `synchro_stats`.
5. **Migration des valeurs** : exporter via script Python avant migration, importer dans Secret Manager, **vider** les colonnes secrètes en DB.
6. **Audit** : ajouter un log Cloud Audit Logs sur chaque accès Secret Manager pour traçabilité.

#### 8.4.4 Migration des fichiers — `storage/` → Cloud Storage

**Volumétrie actuelle** : 688 KB total (modèles + documents générés). Tient sans difficulté dans 1 bucket GCS.

**Plan** :
1. Créer 1 bucket `gs://contrats-storage-{env}/` avec versioning activé (les modèles Word évoluent rarement, mais on garde l'historique).
2. Sous-préfixes : `modeles/`, `documents-generes/`.
3. Remplacer les `Path("/app/storage")` dans `document_service.py` par un client `google-cloud-storage`.
4. Pour la génération Word : télécharger le template dans `/tmp`, générer, uploader le résultat — ou utiliser `python-docx` directement sur des `BytesIO` (préférable).
5. Pour `GET /api/documents/telecharger/{id}` : générer une URL signée GCS (15 min de validité).
6. Le `bind-mount` Docker `./storage:/app/storage` disparaît.

#### 8.4.5 Scheduler — APScheduler → Cloud Scheduler

L'`AsyncIOScheduler` in-process (`main.py:152`) est **incompatible** avec un déploiement Cloud Run (instances multiples, redémarrages fréquents). Plan :

1. **Cron sync Karlia 02:00** : créer un **Cloud Scheduler job** qui appelle un endpoint dédié (par exemple `POST /api/synchro/lancer` avec un header secret).
2. **Sync au boot** : à retirer complètement (anti-pattern). Le job Cloud Scheduler couvre la régénération du cache.
3. **Authentification du Cloud Scheduler** : utiliser un service account avec rôle `Cloud Run Invoker` + signature OIDC du token.

#### 8.4.6 Logs — `print()` → Cloud Logging structuré

Migration recommandée :
1. Remplacer tous les `print(...)` (`main.py:67,89,…`) par `logging.getLogger(__name__).info(...)`.
2. Configurer le logger Python avec un handler JSON pour que Cloud Logging parse automatiquement les champs (`severity`, `message`, `httpRequest`, etc.).
3. Ajouter `trace_id` propagé entre les services pour le tracing (utile pour les workflows multi-étapes Karlia/Chorus).

#### 8.4.7 Conteneurisation et déploiement

**Modifications à apporter à `backend/Dockerfile`** :
- Retirer `--reload` dans la commande `uvicorn` (anti-pattern prod).
- Utiliser un image multi-stage pour réduire la taille (actuellement `python:3.12-slim` = ~150 MB).
- Activer `--workers 2 --worker-class uvicorn.workers.UvicornWorker` via Gunicorn pour utiliser tous les vCPU Cloud Run.
- Exposer un endpoint `/healthz` pour Cloud Run health checks (existe déjà : `/api/health`).

**Modifications côté frontend** :
- Migrer **CRA → Vite** (cf. dette 8.3.4) : build 5× plus rapide, taille moindre.
- Servir le build statique depuis **Cloud Storage + Cloud CDN** (plutôt que via nginx dans un conteneur).
- Configurer un Load Balancer HTTP(S) pour router :
  - `/` → bucket GCS
  - `/api/*` → service Cloud Run backend

**Le proxy nginx disparaît** au profit du Load Balancer GCP. Conséquences :
- `CORS_ORIGINS` doit inclure le nouveau domaine GCP.
- Le timeout proxy 300s doit être paramétré via les annotations Cloud Run (`run.googleapis.com/timeout: 300`).

#### 8.4.8 Variables d'environnement et configuration

Migration du `.env` → Cloud Run env vars + Secret Manager :

| Variable actuelle | Cible GCP |
|---|---|
| `DATABASE_URL` | Cloud Run env var (avec Cloud SQL Connector) |
| `KARLIA_API_KEY` | Secret Manager `karlia-api-key` → monté en env var via Cloud Run |
| `SECRET_KEY` | Secret Manager `jwt-secret-key` |
| `CORS_ORIGINS` | env var Cloud Run |
| `DB_PASSWORD` | Secret Manager `db-password` |
| `TZ` | env var Cloud Run `TZ=Europe/Paris` |

#### 8.4.9 CI/CD recommandé

Bascule recommandée :
1. **Cloud Build** : trigger sur push GitHub → build de l'image Docker → déploiement Cloud Run via blue/green.
2. **Tests** : intégrer les tests Python (à créer — actuellement aucun test) et les tests frontend (à créer aussi).
3. **Migrations DB** : Alembic exécuté par Cloud Build avant le déploiement de la nouvelle image (`alembic upgrade head`).
4. **Sécurité** : scan d'images via Container Analysis (vulnérabilités Python/OS).

#### 8.4.10 Estimation des coûts GCP indicatifs (mensuel)

Volumétrie actuelle réaliste : 13 MB DB, ~700 Ko storage, ~100 req/jour max. La charge est négligeable.

| Service | Plan | Coût estimé / mois |
|---|---|---|
| Cloud SQL PostgreSQL (db-f1-micro) | smallest tier | ~10 € |
| Cloud Run backend | scale to 0, ~50 K req/mois | < 1 € |
| Cloud Storage frontend + assets | < 1 GB | < 0,10 € |
| Cloud Storage documents | < 1 GB | < 0,10 € |
| Secret Manager | 5 secrets, < 10 K accès/mois | < 1 € |
| Cloud Scheduler | 1 job | gratuit |
| Cloud Logging | < 1 GB/mois | gratuit (free tier) |
| **Total estimé** | | **< 15 €/mois** |

**Comparaison VM Ubuntu actuelle** : selon le fournisseur ~5-15 €/mois pour la VM seule (sans backup automatique, sans monitoring, sans HA). La migration GCP **ne devrait pas augmenter significativement** les coûts d'infrastructure tout en apportant : backups automatiques, HA, scale, secrets managés, logs centralisés.

#### 8.4.11 Risques et chemin recommandé

**Étapes de migration suggérées (ordre)** :
1. **Pré-migration interne** :
   - Aligner `models.py` ↔ DB (résoudre divergences phase 2).
   - Activer Alembic (créer une baseline migration `ad-hoc` représentant l'état actuel).
   - Fixer le blocage Chorus Pro 403 (cf. § 7.2.3).
   - Supprimer le code mort (lots fictif, NouveauContrat, calculer_montant_revise, etc.).
   - Centraliser la clé API Karlia en une seule source.

2. **Migration infrastructure** :
   - Provisionner Cloud SQL + Cloud Storage + Secret Manager.
   - Importer DB + secrets + fichiers.
   - Déployer le backend sur Cloud Run.
   - Déployer le frontend sur GCS + CDN.
   - Configurer DNS + Load Balancer.

3. **Coupure** :
   - Geler les écritures côté legacy.
   - Rejouer un dump différentiel.
   - Basculer le domaine.
   - Garder l'ancien backend en lecture seule pendant 30 jours.

4. **Post-migration** :
   - Migrer CRA → Vite (frontend).
   - Migrer vers TypeScript (optionnel mais recommandé).
   - Ajouter tests + Sentry.
   - Activer le polling Chorus statut.

**Durée estimée** : 4 à 6 semaines de travail effectif si une seule personne, dont 2 semaines de pré-migration (étape 1 critique).

---

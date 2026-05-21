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

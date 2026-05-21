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

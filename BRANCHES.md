# Branches et conventions Git — Module Gestion Contrats

Document de référence pour la gestion des branches du dépôt
[contrats-manager](https://github.com/julienmotte-code/contrats-manager).

> Mis à jour le **21 mai 2026** à la suite du cleanup post-audit
> (chantier 1.1, branche `audit/refonte-v2`).

---

## 1. Branches actives

À cet instant, le dépôt contient **9 branches actives** sur `origin`. Toute
nouvelle branche `feature/*` ou `fix/*` doit avoir une justification écrite
ici dès sa création et être taguée puis supprimée dès qu'elle est mergée.

| Branche | Rôle | Statut |
|---|---|---|
| `main` | Tronc de production | actif |
| `audit/refonte-v2` | Audit complet (2026-05-21) — base pour la refonte | actif (traçabilité) |
| `audit/module-v2.3.0` | Audit précédent (2026-05-18) | conservé pour traçabilité |
| `diag/karlia-facture-statut` | Logs debug `karlia_service.creer_facture` (lié Q1 audit : `id_status`) | actif tant que Q1 non tranchée |
| `feat/stabilisations-v2.3.1` | Ajoute colonnes `discount_*` au modèle `CommandeLigne`, logique remises Karlia, méthode `marquer_facture_envoyee`, `id_status=0` | à intégrer (chantier 1.3 alignement schéma) |
| `feature/google-agenda-planning` | Service Google Calendar pour planifier les prestations | en attente d'arbitrage (Q6 audit) |
| `fix/chorus-payload-v5-01-clean` | Refonte Chorus Pro selon spec V5.01 + logging structuré + dry-run | en attente d'arbitrage (Q5 audit blocage 403 PISTE) |
| `fix/karlia-api-key-centralisation` | Centralisation des accès à la clé API Karlia (anti-pattern : 5 emplacements actuels) | à intégrer (Vague 2.4) |
| `fix/karlia-facture-brouillon-v2` | `id_status=0` au lieu de `1` sur tous les chemins de facturation | en attente d'arbitrage (Q1 audit) |

Toute autre branche **doit être supprimée** dès qu'elle est mergée
(cf. convention legacy ci-dessous).

---

## 2. Tags `legacy/*` — branches archivées

Une branche `feature/*` ou `fix/*` mergée sur `main` n'a plus de raison
de rester ouverte. Avant suppression, on crée un tag `legacy/<nom>` sur
son dernier commit pour préserver la traçabilité (auteur, message, diff
stat) sans polluer la liste des branches actives.

**Convention nommage** : `legacy/<nom-branche-aplati>` — les `/` du nom
de branche sont remplacés par `-` (par cohérence avec les contraintes
de nommage des tags Git).

**Tags actuellement créés** (12, état au 2026-05-21) :

| Tag | Origine | Commentaire |
|---|---|---|
| `legacy/feat-dashboard-stats-endpoint` | `feat/dashboard-stats-endpoint` | mergée via tag `v2.4.2` |
| `legacy/feature-chorus-pro` | `feature/chorus-pro` | mergée via tag `v2.1.0` |
| `legacy/feature-dashboard-refonte` | `feature/dashboard-refonte` | précurseur de `v2.4.2` + correctif familles `AT/CITYWEB` |
| `legacy/feature-ecran-clients` | `feature/ecran-clients` | mergée (vérifié par `git cherry main`) |
| `legacy/feature-generation-contrats-word` | `feature/generation-contrats-word` | mergée |
| `legacy/feature-gestion-commandes` | `feature/gestion-commandes` | mergée via tag `v1.5.0` |
| `legacy/feature-gestion-formateurs` | `feature/gestion-formateurs` | mergée + pattern soft-delete utile à conserver |
| `legacy/feature-renouvellements-multi-selection` | `feature/renouvellements-multi-selection` | mergée (tag git existant `v2-renouvellements-multi-selection`) |
| `legacy/feature-seed-test-data` | `feature/seed-test-data` | mergée (tag git existant `v-seed-test-data`) |
| `legacy/feature-sync-devis-opportunites-traitees` | `feature/sync-devis-opportunites-traitees` | mergée via tag `v2.2.0` |
| `legacy/fix-chorus-payload-v5-01-original` | `fix/chorus-payload-v5-01` | doublon épais de `fix/chorus-payload-v5-01-clean` (archive complète avec tous les commits parasites) |
| `legacy/fix-karlia-factures-brouillon` | `fix/karlia-factures-brouillon` | mergée via tag `v2.4.1` (traçabilité du débat `id_status`) |

**Une branche `feature/contrats-onglets-statut`** a été supprimée
sans tag : aucun commit divergent vs main, aucun diff vs main
(vérifié par `git cherry main` vide et `git diff main...` vide).

### Restaurer une branche archivée

Pour réouvrir une branche legacy en local :

```bash
git fetch --tags
git checkout -b feature/<nom-original> legacy/<nom-aplati>
```

Pour la repousser sur origin et la remettre au travail : `git push -u origin feature/<nom-original>`.

---

## 3. Conventions Git

### 3.1 Création d'une branche

- Préfixer par catégorie : `feature/`, `fix/`, `chore/`, `docs/`,
  `refactor/`, `diag/`, `audit/`.
- Le nom doit décrire le **résultat** (ex `fix/karlia-api-key-centralisation`),
  pas le **moyen** (`fix/refactor-config-py` ❌).
- Une branche par sujet ; pas de branche multi-objectifs.

### 3.2 Avant de supprimer une branche feature ou fix

**Toujours créer un tag `legacy/<nom>` avant suppression**, sauf si
la branche est strictement équivalente à `main` (aucun commit
divergent, aucun diff). Vérifier d'abord :

```bash
git fetch --all --prune
git cherry main origin/<branche>          # vide = tout est dans main
git log main..origin/<branche> --oneline  # vide = aucun commit divergent
git diff main...origin/<branche> --stat   # vide = aucun fichier différent
```

Si toutes les commandes ci-dessus retournent vide, la branche peut
être supprimée sans tag (catégorie C de l'audit).

### 3.3 Procédure standard d'archivage

```bash
# 1. Créer le tag legacy
git tag legacy/<nom-aplati> origin/<branche>

# 2. Pousser le tag
git push origin legacy/<nom-aplati>

# 3. Supprimer la branche sur origin
git push origin --delete <branche>

# 4. Supprimer la branche en local
git branch -D <branche>
```

### 3.4 Branches `legacy/*` (interdiction de travail)

Les branches préfixées `legacy/` n'existent pas (uniquement des **tags**).
Si un tag `legacy/<nom>` apparaît, il signifie qu'il préserve l'état
d'une ancienne branche. **Ne jamais travailler directement dessus** :
toujours créer une nouvelle branche `feature/...` à partir du tag si
nécessaire (cf. section 2 "Restaurer une branche archivée").

### 3.5 Branches `audit/*`

Les branches `audit/*` sont **conservées indéfiniment** comme références
horodatées de l'état du dépôt à un instant donné. Elles ne sont jamais
mergées sur main. Leur contenu fait foi pour reconstituer l'état du
projet à la date de l'audit correspondant.

### 3.6 Synchronisation local ↔ origin

Avant tout cleanup ou refactoring :

```bash
git fetch --all --prune
git status                                       # working tree clean ?
# Vérifier qu'aucune branche locale n'a de commits non poussés :
for b in $(git branch | sed 's/[* ]//g'); do
  if git rev-parse --verify --quiet "origin/$b" >/dev/null 2>&1; then
    ahead=$(git rev-list --count "origin/$b..$b" 2>/dev/null)
    [ "$ahead" != "0" ] && echo "⚠ $b : $ahead commit(s) en local non poussé(s)"
  fi
done
```

---

## 4. Tags non-`legacy/`

Les autres tags du dépôt suivent un schéma de versioning :

- `v<MAJOR>.<MINOR>.<PATCH>` (ex `v2.4.6`) — releases stables
- `v<MAJOR>.<MINOR>.<PATCH>.<HOTFIX>` (ex `v2.4.6.1`) — hotfix sur une release
- `v<MAJOR>.<MINOR>.<PATCH>-pre-<nom>` — snapshots pré-mergé
- `v-<nom>` ou `v<MAJOR>-<nom>` — tags exceptionnels nominaux

> Note : des sauts volontaires existent dans la séquence (ex `v2.4.2 → v2.4.5`).
> Ne pas signaler ces sauts comme des anomalies — ils sont intentionnels.

---

## 5. Historique des cleanups

| Date | Avant | Après | Tags legacy créés | Référence |
|---|---|---|---|---|
| 2026-05-21 | 22 branches origin | 9 branches origin | 12 | Chantier 1.1 / branche `audit/refonte-v2` |
| 2026-05-21 | 10 fichiers, 4 commits | 4 fichiers cleanés (-427/+4 lignes) | — | Chantier 1.2 / PR `chore/dead-code-cleanup-v1` mergée en CLI (`--no-ff`), tag `v2.4.7-dead-code-cleanup` |
| 2026-05-21 | 8 divergences models.py ↔ DB | 7/8 alignées (+31/-11 lignes sur `models.py`), #2 reportée chantier 1.4 | — | Chantier 1.3 / PR `chore/schema-alignment` mergée en CLI (`--no-ff`), tag `v2.4.8-schema-alignment` |
| 2026-05-21 | Alembic dans requirements mais jamais câblé | Alembic câblé, baseline 0001 stampée en prod, migration 0002 prête (non-appliquée) | — | Chantier 1.4 / PR `chore/alembic-setup` mergée en CLI (`--no-ff`). **Pas de tag** — le tag `v2.4.9-vague-1-complete` sera posé après le chantier de déploiement qui appliquera 0002. |
| 2026-05-21 | `alembic_version=0001`, table `lots_facturation` présente, ancien UNIQUE `date_publication`, backend tournant avec ancien code en mémoire | `alembic_version=0002`, `lots_facturation` droppée, nouveau UNIQUE `(annee, mois)`, backend rebuildé avec code chantiers 1.3+1.4 | — | **Chantier de déploiement Vague 1** / migration `0002` appliquée en prod + rebuild backend, tag `v2.4.9-vague-1-complete` posé. |
| 2026-05-21 | 94 endpoints backend, dont 7 routers totalement ouverts, 6 checks RBAC inline dispersés, dashboard public, anomalies #2/#4 audit pendantes | 94 endpoints **100 % gatés** via `app/core/security.py` (73 `require_role`, 17 `require_authenticated`, 2 `get_current_user` direct, 2 publics légitimes), 6 inline checks factorisés, dashboard authentifié (filtre par rôle reporté), helper `openPdfWithAuth` créé | — | **Chantier 2.1 Vague 2** / PR `feat/backend-rbac` mergée en CLI (`--no-ff`), 18 commits. **Pas de tag** — le tag `v2.5.0-vague-2-complete` sera posé après le chantier de déploiement complet de la Vague 2. **Code mergé sur main MAIS PAS encore déployé en prod** (rebuild backend prévu dans le chantier de déploiement Vague 2). |

### Détail chantier 1.2 (2026-05-21)

PR `chore/dead-code-cleanup-v1` mergée sur `main` via merge CLI `--no-ff` (la PR GitHub n'a pas été cliquée).

Commits intégrés (du plus ancien au plus récent) :

1. `41b841d` — `chore(backend): remove unused service functions` — retrait de `calculer_montant_revise`, `calculer_statut_renouvellement`, `obtenir_produit`, `obtenir_prix_vente`, `lister_templates_documents` + nettoyage imports
2. `870e8b7` — `chore(backend,frontend): remove facturation lot stub endpoint and LotFacturation model` — retire `GET /api/facturation/lot/{id}`, modèle `LotFacturation`, helper `facturationAPI.lotStatut`. **Note** : la table `lots_facturation` reste en DB (drop reporté au chantier 1.4 Alembic), `api/indices.py:139` exécute encore un raw SQL `UPDATE lots_facturation` qui continue de fonctionner
3. `cb70244` — `chore(backend,frontend): remove orphan CITYWEB family` — famille CITYWEB orpheline (0 contrat en DB, absente de `FAMILLES_CONTRAT`) retirée du dashboard backend + frontend
4. `8370bbb` — `chore(frontend): remove unused UI libraries` — désinstallation de `lucide-react`, `react-select`, `react-datepicker` (jamais importées, ~300 ko gzippés de gain estimé)

Merge commit : voir le `git log` du tag `v2.4.7-dead-code-cleanup`.

**Point à reporter au chantier 1.4** : `backend/app/api/indices.py:139` exécute encore un `UPDATE lots_facturation SET indice_utilise_id = NULL` en raw SQL. Quand la table sera dropée via Alembic, ce SQL devra être retiré.

### Détail chantier 1.3 (2026-05-21)

PR `chore/schema-alignment` mergée sur `main` via merge CLI `--no-ff`.

Commits intégrés (1 par divergence, dans l'ordre #1 → #8) :

1. `6f6713d` — `chore(schema): align clients_cache.numero_client uniqueness (#1)` — retire `unique=True` du modèle (DB n'a pas UNIQUE, 0 doublon en prod)
2. `464b98a` — `chore(schema): document divergence #2 (indices_revision uniqueness) — defer to chantier 1.4` — TODO Python uniquement, pas de modif fonctionnelle (contradiction `CODING_RULES.md § 9` vs DB à arbitrer au chantier 1.4)
3. `81e6532` — `chore(schema): align contrats.client_karlia_id nullability (#3)` — passe `nullable=True` côté modèle (DB autorise NULL, 0 NULL en prod)
4. `0d9ae0a` — `chore(schema): align commandes.pdf_devis type (#4)` — `Text` → `LargeBinary` (DB est `bytea`, colonne vide)
5. `bf6f1bc` — `chore(schema): align commandes/commande_lignes timestamps to without-tz (#5)` — retire `timezone=True` sur 5 colonnes
6. `17cfb54` — `chore(schema): add commande_lignes.discount_* columns to model (#6)` — ajout `discount_type/value/percent` (déjà en DB, peuplé à 57 %)
7. `af748eb` — `chore(schema): add agenda_formateur_id and google_* columns to Prestation (#7)` — ajout 5 colonnes + relations `formateur` / `agenda_formateur` (avec `foreign_keys` explicites)
8. `f2c1fd4` — `chore(schema): add transmissions_chorus.is_test column to model (#8)` — ajout `Boolean default=False`

Merge commit : voir le `git log` du tag `v2.4.8-schema-alignment`.

**Points à reporter au chantier 1.4 (Alembic)** :
- Divergence #2 : DROP UNIQUE `indices_revision_date_publication_key` + CREATE UNIQUE sur `(annee, mois)` + ajout `UniqueConstraint('annee', 'mois')` dans models. TODO actif au-dessus de la classe `IndiceRevision` dans `models.py`.
- Divergence #1 : décider si on ajoute UNIQUE en DB sur `clients_cache.numero_client` (0 doublon en prod, viable).
- Divergence #3 : décider si on ajoute NOT NULL en DB sur `contrats.client_karlia_id` (0 NULL en prod, viable).
- Point chantier 1.2 toujours valable : retirer le raw SQL `UPDATE lots_facturation` de `api/indices.py:139` au moment du drop de la table.

### Détail chantier 1.4 (2026-05-21)

PR `chore/alembic-setup` mergée sur `main` via merge CLI `--no-ff`. **Pas de tag** à ce stade : le tag `v2.4.9-vague-1-complete` sera posé après le chantier séparé de déploiement Vague 1.

Commits intégrés (4) :

1. `fd8bcd5` — `chore(alembic): initialize Alembic in backend/` — création manuelle de `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/.gitkeep`. `prepend_sys_path = .` + `compare_type=True` + `compare_server_default=True` + `file_template = %%(rev)s_%%(slug)s`.
2. `cf8c662` — `chore(alembic): baseline existing DB - empty no-op migration as version 0001` — baseline `0001` no-op (`upgrade=pass`, `downgrade=pass`) après échec de l'autogenerate (32 opérations parasites produites par `--autogenerate` sur la DB existante). `alembic stamp head` exécuté sur la DB de prod → création de la table `alembic_version` avec `version_num='0001'`. **Aucune autre table de prod n'a été modifiée.**
3. `ded43e2` — `chore(alembic): migration 0002 - drop lots_facturation + indices_revision UNIQUE on (annee, mois)` — migration **manuelle** (autogenerate désactivé) avec 3 opérations strictes : `drop_table('lots_facturation')`, `drop_constraint('indices_revision_date_publication_key')`, `create_unique_constraint('uq_indices_revision_annee_mois', ['annee', 'mois'])`. `downgrade()` inverse strict (table recréée selon `\d` réel observé en DB). Modifs accompagnantes dans `models.py` (ajout `UniqueConstraint`, retrait TODO) et `api/indices.py` (retrait du raw SQL `UPDATE lots_facturation`). **Test à blanc validé** sur DB `contrats_test_migration` (upgrade + downgrade OK), DB temp supprimée. **Migration 0002 NON appliquée sur la DB de prod** — sera déployée au chantier suivant.
4. `cc106fb` — `docs(alembic): workflow Alembic + bannissement SQL DDL manuel` — `backend/alembic/README.md` (workflow + template migration manuelle + procédure test à blanc + notes historiques sur la baseline 0001 et l'absence d'autogenerate) + `CODING_RULES.md § 12` (règle absolue : tout DDL passe par Alembic, plus de `db.execute(text("ALTER TABLE ..."))` ni `Base.metadata.create_all()`).

Merge commit sur main : `cd348ca`.

État DB de prod à la fin du chantier 1.4 :
- Table `alembic_version` créée avec `version_num='0001'`
- 17 tables métier inchangées (aucun `ALTER TABLE`, aucun `DROP`)
- `alembic current` retourne `0001` (la migration `0002` est dans le repo mais pas dans la DB)

**À traiter au chantier de déploiement Vague 1 (chantier suivant)** :
- Appliquer la migration `0002` sur la DB de prod (`docker compose run --rm backend alembic upgrade head`)
- Rebuild backend (intègre les changements chantiers 1.3 + 1.4)
- Vérifications post-déploiement
- Pose du tag `v2.4.9-vague-1-complete`

### Détail chantier de déploiement Vague 1 (2026-05-21)

Mise en production des chantiers 1.2 (code mort), 1.3 (alignement schéma) et 1.4 (Alembic). Procédure en 5 étapes séquencées avec point de validation à chaque étape.

**Tag de release** : `v2.4.9-vague-1-complete` posé sur le commit `80f079b` (HEAD main avant déploiement) et poussé sur origin.

**Étape 1 — Backup pré-déploiement (filet de sécurité)** :

- Fichier : `~/contrats/backups/backup_pre_vague1_20260521-171929.dump`
- Format : PostgreSQL custom (`pg_dump --format=custom`)
- Taille : 250 662 octets (~245 Ko)
- sha256 : `5a8fe976fd7cfafe669de1ada48b4c6887c2e57669f056d86e50d69b7430faa5`
- TOC : 119 entries, 18 tables (17 métier + `alembic_version`)
- Sanity check `pg_restore --list` OK
- Utilisable pour rollback complet via `pg_restore` (cf. procédure ROLLBACK R2 du chantier de déploiement)

**Étape 2 — Migration Alembic 0001 → 0002 sur DB de prod** :

- `alembic upgrade head` exécuté, sortie nominale : `Running upgrade 0001 -> 0002`
- Aucun warning, aucun rollback transactionnel
- `SELECT version_num FROM alembic_version` → `0002`
- Table `lots_facturation` **droppée** (`Did not find any relation`)
- Contrainte `indices_revision_date_publication_key` **supprimée**
- Contrainte `uq_indices_revision_annee_mois UNIQUE (annee, mois)` **créée**
- 0 doublon `(annee, mois)` constaté sur les 6 indices existants — la contrainte est immédiatement satisfaite
- Volumétries préservées (cf. ci-dessous)

**Étape 3 — Rebuild + restart backend uniquement (frontend + db inchangés)** :

- `docker compose build backend` puis `docker compose up -d backend`
- Conteneur recréé en 18 secondes, boot complet (`Application startup complete` + hooks `[CONFIG]`/`[SYNCHRO]`/`[SCHEDULER]`)
- Aucun TRACEBACK SQLAlchemy au boot
- Tous les nouveaux attributs ORM chargent : `CommandeLigne.discount_*`, `Prestation.agenda_formateur_id/google_*`, `TransmissionChorus.is_test`, `IndiceRevision.UniqueConstraint('annee','mois')`
- Code rebuildé ne contient plus le raw SQL `UPDATE lots_facturation` (vérifié via `inspect.getsource`)

**Étape 4 — Vérifications fonctionnelles complètes (5/5 endpoints + 3/3 sanity checks)** :

- `/api/health` → 200 OK
- `/api/contrats` → 572 contrats, format `{total, data}`
- `/api/indices` → 6 indices (2023/2024/2025 × AOUT/OCTOBRE)
- `/api/facturation/apercu/2026` → 1 plan calculé sans erreur SQL
- `/api/dashboard/stats` → 572 contrats répartis sur 7 familles (CITYWEB absente comme attendu après chantier 1.2), CA 1 174 405 € HT
- Lecture ORM des colonnes nouvelles : ligne 369 de `commande_lignes` confirme `discount_type='percent', percent=46.0` (matche l'audit) ; 5 prestations sur 11 ont `agenda_formateur_id` + `google_sync_status='pending_google_integration'` ; 4 transmissions Chorus toutes `is_test=False`

**Volumétries préservées en prod (post-déploiement)** :

| Table | Lignes |
|---|---|
| `contrats` | 572 |
| `plan_facturation` | 1150 |
| `indices_revision` | 6 |
| `commandes` | 142 |
| `commande_lignes` | 196 |
| `factures_karlia` | 15 |
| `prestations` | 11 |
| `transmissions_chorus` | 4 |
| `utilisateurs` | 8 |

Aucune ligne perdue, aucune ligne créée par erreur. Seule la table `lots_facturation` (0 lignes en prod) a été supprimée.

**Containers en prod après déploiement** :

- `contrats-backend-1` : rebuildé, `Up` avec nouveau code
- `contrats-db-1` : inchangé, `Up 7 weeks (healthy)`, désormais à `alembic_version=0002`
- `contrats-frontend-1` : inchangé, `Up 21 hours+`

**Statut** : Vague 1 complète. Prête pour Vague 2.

### Détail chantier 2.1 — RBAC backend (2026-05-21)

PR `feat/backend-rbac` mergée sur `main` via merge CLI `--no-ff` (la PR GitHub n'a pas été cliquée). Merge commit : **`a0b439d`**.

**Objectif** : appliquer un contrôle RBAC strict sur les 94 endpoints du backend FastAPI. État initial : 7 routers totalement ouverts (aucun `Depends(get_current_user)`), 6 checks inline `if current_user.role != "ADMIN"` dispersés (anomalie #2 audit), 1 bug `current_user: dict` (anomalie #4), 1 dashboard public retournant des données financières confidentielles, 1 pattern `window.open` cassant l'auth Bearer pour les PDF.

**18 commits intégrés** (du plus ancien au plus récent) :

1. `01d7f40` — `feat(rbac): add app/core/security.py with require_role factory + tests/rbac_check.sh` — création des helpers centraux `require_role(*roles)` et `require_authenticated`, + script de test RBAC pour les 4 rôles `test_*`
2. `bf8c159` — `feat(rbac): apply require_role to contrats router` — 10 endpoints (2 reads TOUS_AUTH, 8 writes ADMIN+GESTIO)
3. `fdec11c` — `feat(rbac): apply require_role to commandes router` — 14 endpoints ADMIN+GESTIO
4. `ede8bee` — `fix(rbac): replace window.open by openPdfWithAuth helper for /api/commandes/{id}/pdf` — création `contrats-ui-src/src/services/pdfFetch.js` qui fetch avec Bearer puis ouvre via Blob URL ; 5 pages frontend modifiées pour utiliser le helper
5. `01e60b1` — `feat(rbac): apply require_role to facturation router` — 3 endpoints ADMIN+GESTIO
6. `54eb9a6` — `feat(rbac): apply require_role to chorus router + fix current_user dict bug` — 9 endpoints ADMIN+GESTIO + fix anomalie #4 ligne 390 (`current_user.get("login", "system")` → `current_user.login`, annotation `dict` retirée)
7. `5ba3959` — `feat(rbac): apply require_role to clients router` — 7 endpoints ADMIN+GESTIO (router totalement ouvert avant)
8. `4766369` — `feat(rbac): apply require_role to formateurs router` — 5 endpoints mixtes (2 reads TOUS_AUTH pour MesPrestations, 3 writes ADMIN)
9. `8b88005` — `feat(rbac): apply require_role to prestations router with ownership filtering` — 10 endpoints, helpers `check_prestation_ownership` et `filter_prestations_for_user` ajoutés à `core/security.py`, TECH/FORM ne voient que leurs propres prestations (`formateur_id` ou `agenda_formateur_id` match)
10. `512895f` — `feat(rbac): apply require_role to produits router` — 2 endpoints (1 read TOUS_AUTH, 1 sync ADMIN+GESTIO)
11. `b4a3f04` — `feat(rbac): apply require_role to documents router + factorize inline ADMIN checks` — 7 endpoints, 3 checks inline supprimés (lignes 76, 98, 111). Pas de pattern `window.open` à corriger (DetailContrat.js:79 utilise déjà `fetch` avec Bearer)
12. `5a1e9a4` — `feat(rbac): apply require_role to parametres router + factorize inline ADMIN checks` — 6 endpoints ADMIN strict, 3 checks inline supprimés (lignes 38, 76, 131)
13. `ac91a9d` — `feat(rbac): apply require_role to indices router` — 7 endpoints (4 reads TOUS_AUTH dont `/courant` critique pour Dashboard tous rôles, 3 writes ADMIN+GESTIO). Logique DELETE (2 UPDATE ORM chantier 1.4) préservée intacte
14. `1453583` — `feat(rbac): apply require_role to audit router` — 3 endpoints ADMIN+GESTIO
15. `e2ee610` — `feat(rbac): apply require_authenticated to dashboard router` — 1 endpoint TOUS_AUTH. **Fuite de données financières documentée en HIGH priority dans `TODO_REFONTE.md`** (FORMATEUR/TECHNICIEN voient le CA total portefeuille — chantier `feat/dashboard-filter-by-role` à traiter dès Vague 2 mergée)
16. `9252053` — `feat(rbac): apply gates to main.py root endpoints` — 3 endpoints : `/api/health` PUBLIC, `/api/synchro/statut` TOUS_AUTH, `/api/synchro/lancer` ADMIN+GESTIO. `auth.py` non touché (`/me` conserve `get_current_user` pour éviter un import circulaire `auth ↔ security`)
17. `90ffacd` — `refactor(rbac): replace local require_admin by central require_role in utilisateurs router` — cleanup post-audit F.1, suppression du helper `require_admin` local de `utilisateurs.py` au profit de `require_role("ADMIN")` du module commun (source unique de vérité)
18. `ab59a15` — `docs: recap chantier 2.1 backend RBAC (17 commits, 14 routers + main + cleanup utilisateurs)` — création de `CHANTIER_2_1_RECAP.md` (synthèse exhaustive)

**Couverture finale (94 endpoints) — matrice live confirmée par tests `rbac_check.sh`** :

| Gate | Endpoints | Description |
|---|---|---|
| `require_role("ADMIN", "GESTIONNAIRE")` | 57 | Données financières, opérations métier (chorus, clients, commandes, facturation, audit, contrats writes) |
| `require_role("ADMIN")` | 16 | Administration système (parametres, formateurs writes, documents templates, utilisateurs CRUD) |
| `require_authenticated` | 17 | Lectures catalogue/référentiel (dashboard, indices reads, produits read, prestations avec filtre métier ownership) |
| `get_current_user` direct | 2 | `auth.py:/me` et `utilisateurs.py:/droits` (retour info utilisateur courant, pas de check de rôle) |
| **PUBLIC légitime** | 2 | `GET /api/health` (Docker healthcheck), `POST /api/auth/login` (bootstrap auth) |
| **Total** | **94** | **100 %** |

**7 dettes documentées dans `TODO_REFONTE.md`** :

- 🔴 **PRIORITÉ ÉLEVÉE** : `feat/dashboard-filter-by-role` — fuite CA portefeuille à FORMATEUR/TECHNICIEN (à traiter dès Vague 2 mergée, avant Vague 3)
- 6 dettes priorité faible : endpoint commandes manquant, endpoints commandes/prestations orphelins (code mort frontend), gating frontend granulaire (`isNotFormateur` trop large), UX TECHNICIEN sur DetailContrat (section Documents silencieuse), bouton Synchroniser Dashboard visible pour FORM/TECH

**Comptes `test_*` préservés** (4 rôles, conservés pour chantiers 2.2-2.4) :

| Login | Rôle | `actif` | `formateur_id` |
|---|---|---|---|
| `test_admin` | ADMIN | ✅ | `None` |
| `test_gestionnaire` | GESTIONNAIRE | ✅ | `None` |
| `test_technicien` | TECHNICIEN | ✅ | `2` (Delphine) |
| `test_formateur` | FORMATEUR | ✅ | `2` (Delphine) |

Mot de passe commun : `Test123!`. Suppression à la clôture de la Vague 2.

**État backend prod après merge** :

- Code mergé sur `main` mais **PAS encore déployé en prod**.
- Le backend Docker tourne toujours avec l'image du chantier de déploiement Vague 1 (tag `v2.4.9-vague-1-complete`).
- Le rebuild backend interviendra dans le chantier de déploiement complet de la Vague 2 (qui inclura aussi 2.2 valider_pre_emission, 2.3, 2.4 centralisation clé Karlia, et le fix dashboard filter prioritaire).

Référence détaillée : `~/contrats/CHANTIER_2_1_RECAP.md` (synthèse exhaustive avec liste des 18 commits, anomalies résolues, régressions évitées, tests effectués).

**Statut** : chantier 2.1 complet. Prochain : 2.2 `valider_pre_emission`.


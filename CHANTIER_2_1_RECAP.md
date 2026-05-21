# Chantier 2.1 — Backend RBAC : récap exhaustif

**Branche** : `feat/backend-rbac`
**Date de réalisation** : 2026-05-21
**Durée** : 1 session (interruption PuTTY puis reprise complète sur 16 commits + 1 cleanup + 1 doc)
**Vague** : 2 (sécurité backend)

---

## Objectif

Mettre en place un contrôle de rôle (RBAC) sur **tous les endpoints** du backend FastAPI. L'état initial présentait :
- Plusieurs routers totalement ouverts (sans aucun `Depends(get_current_user)`) : `clients.py`, `produits.py`, `formateurs.py`, `prestations.py`, `indices.py`, `dashboard.py`, `audit.py`, `main.py:/api/synchro/*`
- Plusieurs routers avec `get_current_user` (authentification mais aucun contrôle de rôle) : `contrats.py`, `commandes.py`, `facturation.py`, `chorus.py`, `audit.py`, `parametres.py`
- 6 checks inline `if current_user.role != "ADMIN"` dispersés (anomalie #2 audit)
- 1 bug `current_user: dict` au lieu d'objet ORM Utilisateur (anomalie #4 audit, ligne 390 chorus.py)
- 1 dashboard non gaté retournant des données financières confidentielles
- 1 dépendance frontend `window.open` cassant l'auth Bearer pour les PDF commandes

La cible : factoriser tous les contrôles via `app/core/security.py` (helpers `require_role(*roles)` et `require_authenticated`), couvrir les 94 endpoints, et documenter les dettes restantes.

---

## Architecture mise en place

### Helpers centraux (`backend/app/core/security.py`)
- `require_authenticated(current_user: Utilisateur = Depends(get_current_user)) -> Utilisateur` : exige juste un utilisateur authentifié (token JWT valide).
- `require_role(*roles: str)` : factory retournant une dépendance FastAPI qui exige que le rôle de l'utilisateur soit dans la liste passée. Lève 403 sinon.
- `check_prestation_ownership(prestation, current_user)` : helper métier pour le filtrage ownership des prestations (ADMIN/GESTIO pass, TECH/FORM doivent matcher `formateur_id` ou `agenda_formateur_id`).
- `filter_prestations_for_user(query, current_user)` : applique le filtre SQL équivalent sur une query Prestation.

### Outillage de test
- `tests/rbac_check.sh` : script bash qui authentifie 4 comptes `test_*` (un par rôle) et appelle un endpoint pour comparer les codes HTTP retournés. Usage type : `./tests/rbac_check.sh GET /api/contrats`.

---

## Liste des 18 commits

| # | SHA | Type | Sujet | Fichiers |
|---|---|---|---|---|
| 1 | `01d7f40` | feat | add `app/core/security.py` with `require_role` factory + `tests/rbac_check.sh` | core/security.py, tests/rbac_check.sh |
| 2 | `bf8c159` | feat | apply `require_role` to **contrats** router | api/contrats.py |
| 3 | `fdec11c` | feat | apply `require_role` to **commandes** router | api/commandes.py |
| 4 | `ede8bee` | fix | replace `window.open` by `openPdfWithAuth` helper for `/api/commandes/{id}/pdf` | contrats-ui-src (services/pdfFetch.js, pages/Commandes*.js) |
| 5 | `01e60b1` | feat | apply `require_role` to **facturation** router | api/facturation.py |
| 6 | `54eb9a6` | feat | apply `require_role` to **chorus** router + fix `current_user: dict` bug (anomalie #4) | api/chorus.py |
| 7 | `5ba3959` | feat | apply `require_role` to **clients** router | api/clients.py |
| 8 | `4766369` | feat | apply `require_role` to **formateurs** router | api/formateurs.py |
| 9 | `8b88005` | feat | apply `require_role` to **prestations** router with ownership filtering (helpers added) | api/prestations.py, core/security.py, TODO_REFONTE.md |
| 10 | `512895f` | feat | apply `require_role` to **produits** router | api/produits.py |
| 11 | `b4a3f04` | feat | apply `require_role` to **documents** router + factorize 3 inline ADMIN checks | api/documents.py |
| 12 | `5a1e9a4` | feat | apply `require_role` to **parametres** router + factorize 3 inline ADMIN checks | api/parametres.py, TODO_REFONTE.md |
| 13 | `ac91a9d` | feat | apply `require_role` to **indices** router (DELETE logic preserved from chantier 1.4) | api/indices.py |
| 14 | `1453583` | feat | apply `require_role` to **audit** router | api/audit.py |
| 15 | `e2ee610` | feat | apply `require_authenticated` to **dashboard** router (financial leak documented) | api/dashboard.py, TODO_REFONTE.md |
| 16 | `9252053` | feat | apply gates to **main.py** root endpoints | main.py, TODO_REFONTE.md |
| 17 | `90ffacd` | refactor | replace local `require_admin` by central `require_role` in **utilisateurs** router | api/utilisateurs.py |
| 18 | _(this doc)_ | docs | recap chantier 2.1 backend RBAC (17 commits, 14 routers + main + utilisateurs cleanup) | CHANTIER_2_1_RECAP.md |

**Note** : le commit `ede8bee` (fix `window.open`) est intercalé dans la séquence des routers car il a été identifié pendant le commit commandes et résolu immédiatement pour éviter une régression UX bloquante en prod.

---

## Matrice de couverture finale (94 endpoints)

### Récap par gate

| Gate | Compte | Pourcentage |
|---|---|---|
| `require_role("ADMIN", "GESTIONNAIRE")` | 57 | 60.6 % |
| `require_role("ADMIN")` | 16 | 17.0 % |
| `require_authenticated` | 17 | 18.1 % |
| `get_current_user` (auth.py `/me` + utilisateurs.py `/droits`) | 2 | 2.1 % |
| **PUBLIC légitime** (`GET /api/health`, `POST /api/auth/login`) | 2 | 2.1 % |
| **Total** | **94** | **100 %** |

### Détail par router

| Router | Endpoints | Profil dominant |
|---|---|---|
| `audit.py` | 3 | ADMIN+GESTIONNAIRE strict |
| `auth.py` | 2 | 1 PUBLIC (login) + 1 get_current_user (me) |
| `chorus.py` | 9 | ADMIN+GESTIONNAIRE strict |
| `clients.py` | 7 | ADMIN+GESTIONNAIRE strict |
| `commandes.py` | 14 | ADMIN+GESTIONNAIRE strict |
| `contrats.py` | 10 | Mixte : 2 reads TOUS_AUTH, 8 writes ADMIN+GESTIO |
| `dashboard.py` | 1 | TOUS_AUTH (avec dette financière documentée) |
| `documents.py` | 7 | Mixte : 1 TOUS_AUTH (modeles), 3 ADMIN+GESTIO (génération/download), 3 ADMIN (templates admin) |
| `facturation.py` | 3 | ADMIN+GESTIONNAIRE strict |
| `formateurs.py` | 5 | Mixte : 2 reads TOUS_AUTH, 3 writes ADMIN |
| `indices.py` | 7 | Mixte : 4 reads TOUS_AUTH, 3 writes ADMIN+GESTIO |
| `parametres.py` | 6 | ADMIN strict |
| `prestations.py` | 10 | Mixte : 5 TOUS_AUTH avec filtrage ownership, 5 writes ADMIN+GESTIO |
| `produits.py` | 2 | Mixte : 1 read TOUS_AUTH, 1 sync ADMIN+GESTIO |
| `utilisateurs.py` | 5 | 4 CRUD ADMIN + 1 droits TOUS_AUTH |
| `main.py` | 3 | 1 PUBLIC (health) + 1 TOUS_AUTH (statut) + 1 ADMIN+GESTIO (lancer) |

---

## Anomalies détectées et résolues

| # | Anomalie | Détection | Résolution | Commit |
|---|---|---|---|---|
| 1 | 7 routers totalement ouverts (`clients`, `produits`, `formateurs`, `prestations`, `indices`, `dashboard`, `audit`) | Étape 0 audit + scan chantier | Gate ajouté sur chaque endpoint | 4766369, 5ba3959, 8b88005, 512895f, ac91a9d, 1453583, e2ee610 |
| 2 | 6 checks inline `current_user.role != "ADMIN"` (3 dans documents.py lignes 76, 98, 111 + 3 dans parametres.py lignes 38, 76, 131) | Étape 0 audit anomalie #2 | Factorisation via `require_role("ADMIN")` | b4a3f04, 5a1e9a4 |
| 3 | `current_user: dict` au lieu de `Utilisateur` dans chorus.py + `.get("login", "system")` au lieu de `.login` | Étape 0 audit anomalie #4 (ligne 390) | Suppression annotation `dict`, usage attribut ORM | 54eb9a6 |
| 4 | `window.open('/api/commandes/{id}/pdf', '_blank')` ne transmet pas le Bearer JWT — casse le PDF dès qu'on protège l'endpoint | Détection pendant commit commandes | Création helper `openPdfWithAuth` (fetch + Blob URL) | ede8bee |
| 5 | Helper local `require_admin` dupliquant `require_role("ADMIN")` dans utilisateurs.py | F.1 audit couverture exhaustif | Refactor pour utiliser le helper central | 90ffacd |

---

## Régressions UX évitées

| Situation | Frontend impacté | Résolution |
|---|---|---|
| PDF commandes via `window.open` | `pages/CommandesACommander.js`, `pages/Commandes*.js` | Helper `pdfFetch.js` créé pour préserver Bearer header (commit ede8bee) |
| Dashboard sync auto au mount | `pages/Dashboard.js:89-93` | Fallback `.catch` → `GET /statut` déjà en place — pas de régression pour FORMATEUR/TECHNICIEN |
| `GET /api/auth/me` import circulaire | `core/security.py` ↔ `api/auth.py` | Conservation de `Depends(get_current_user)` directement dans auth.py (sémantique identique) |
| Logique métier DELETE indices (chantier 1.4) | `api/indices.py:141-142` | Les 2 UPDATE ORM (Contrat.indice_reference_id, PlanFacturation.indice_calcul_id → NULL) préservées intactes |

---

## Dettes documentées dans TODO_REFONTE.md

| # | Titre | Priorité | Chantier proposé |
|---|---|---|---|
| 1 | **FUITE DE DONNÉES FINANCIÈRES sur Dashboard pour FORMATEUR et TECHNICIEN** (CA annuel, contrats par famille avec montants) | 🔴 **ÉLEVÉE (sécurité)** | `feat/dashboard-filter-by-role` — À traiter dès Vague 2 mergée |
| 2 | Endpoint `PUT /api/commandes/{id}` manquant (régression silencieuse 404) | Faible | UX dédié |
| 3 | Endpoints commandes orphelins (POST `/planifier`, POST `/lier-contrat`) | Faible | Investigation UI |
| 4 | Gating frontend granulaire — `isNotFormateur` trop large vs `AuthContext.droits` | Faible | `feat/frontend-rbac-granular` |
| 5 | Endpoints prestations sans appel frontend (POST `/`, PUT `/{id}`) | Faible | Investigation UI |
| 6 | UX TECHNICIEN sur DetailContrat — section Documents vide silencieuse | Faible | `feat/frontend-rbac-granular` |
| 7 | Bouton "Synchroniser maintenant" Dashboard visible pour FORMATEUR/TECHNICIEN | Faible | `feat/frontend-rbac-granular` |

---

## Tests effectués

### Tests automatisés via `tests/rbac_check.sh`
Pour chaque router, scénario standard : authentifier les 4 comptes `test_*` et appeler tous les endpoints. **Résultats : 100 % conformes à la matrice cible**.

### Tests métier additionnels

- **Prestations — filtrage ownership** : modification temporaire d'une prestation pour assigner `formateur_id=2`, vérification que TECHNICIEN/FORMATEUR (formateur_id=2) reçoivent 200 in-scope et 403 out-of-scope. Helper `filter_prestations_for_user` testé directement en Python via `docker compose exec`.
- **Prestations — `GET /formateur/{id}`** : TECH/FORM = 200 sur `/formateur/2` (own), 403 sur `/formateur/3` (other).
- **PDF commandes — Bearer transmis** : helper `openPdfWithAuth` testé manuellement, PDF s'ouvre sans erreur 401.
- **main.py — endpoints publics confirmés** :
  - `GET /api/health` → 200 sans Bearer ✅
  - `POST /api/auth/login` → 200 sans Bearer (credentials valides) ✅
  - `GET /api/synchro/statut` → 401 sans Bearer (était 200 avant) ✅
  - `GET /api/auth/me` → 401 sans Bearer ✅
- **Tests non-destructifs sur `parametres` PUT** : body vide pour ADMIN (validation Pydantic 422), non-admin reçoivent 403 — aucune modification réelle des clés Karlia/Chorus.
- **Tests non-destructifs sur `indices` DELETE** : UUID `00000000-...` bidon utilisé — ADMIN reçoit 404, non-admin reçoivent 403, aucune suppression réelle.

---

## Comptes `test_*` (conservés pour Vague 2)

| Login | Rôle | `actif` | `formateur_id` |
|---|---|---|---|
| `test_admin` | ADMIN | ✅ | `None` |
| `test_gestionnaire` | GESTIONNAIRE | ✅ | `None` |
| `test_technicien` | TECHNICIEN | ✅ | `2` (Delphine) |
| `test_formateur` | FORMATEUR | ✅ | `2` (Delphine) |

Mot de passe commun : `Test123!`. **À conserver pour les chantiers 2.2-2.4**, suppression à la clôture de la Vague 2.

---

## Prochain chantier

**2.2 — valider_pre_emission** : ajouter une garde métier supplémentaire avant l'émission Karlia (cf. plan Vague 2).

Puis ordre d'exécution prévu :
- 2.2 valider_pre_emission
- 2.3 …
- 2.4 centralisation clé Karlia
- Avant ouverture Vague 3 : chantier dette `feat/dashboard-filter-by-role` (priorité sécurité)

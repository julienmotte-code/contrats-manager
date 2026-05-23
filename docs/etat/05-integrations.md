# 05 — Intégrations externes (Karlia & Chorus Pro)

Données extraites de `backend/app/services/karlia_service.py`, `karlia_devis_service.py`, `chorus_service.py` et des routers `chorus.py`, `commandes.py`, `parametres.py`.

## 1. Karlia (CRM/Facturation)

### 1.1 URL & authentification
- Base : `KARLIA_API_URL` (`settings`) = `https://karlia.fr/app/api/v2` (config par défaut, peut être surchargée par `.env`).
- Auth : `Authorization: Bearer <KARLIA_API_KEY>`.
- La clé n'est jamais figée dans le code : `KarliaService.__init__` la lit dans `settings.KARLIA_API_KEY`, **mais** au démarrage de FastAPI (`main.py:startup`) et avant chaque tick du scheduler, la clé est rechargée depuis la table `parametres` (clé `karlia_api_key`). C'est cette valeur qui est utilisée à la volée — `karlia.api_key = param.valeur`.

### 1.2 Méthodes appelées (`karlia_service.py`)

| Méthode | Endpoint | Détails |
|---|---|---|
| `lister_clients(recherche, limit, offset)` | `GET /customers` | params : `limit`, `offset`, `archived=0`, `quick_search` (optionnel). |
| `obtenir_client(karlia_id)` | `GET /customers/{id}` | — |
| `creer_client(data)` | `POST /customers` | inclut le `client_number` personnalisé. |
| `dernier_numero_client()` | `GET /customers?limit=500&fields=client_number&archived=0` | extrait le max numérique de tous les `client_number`. |
| `lister_produits(recherche, limit=200)` | `GET /products` | `quick_search` optionnel. |
| `lister_types_documents()` | `GET /documents?limit=1` | utilitaire. |
| `creer_facture(...)` | `POST /documents` | payload : `id_type=4` (Facture), `id_status=1` (Brouillon Karlia), `id_customer`, `reference`, `date`, `date_end`, `description`, `products_list`. `id_vat` mappé d'après le taux de TVA (1=20%, 2=10%, 3=5,5%, 4=0%). |
| `obtenir_document(doc_id)` | `GET /documents/{id}` | — |
| `tester_connexion()` | `GET /company` | renvoie `{ok, company}`. |
| `traitement_lot_factures(factures, delai_entre_requetes=0.8)` | boucle `creer_facture` avec `asyncio.sleep(0.8)` entre chaque appel (≈75 req/min, sous le quota 100). |

### 1.3 Sync devis acceptés (`karlia_devis_service.py`)
Classe `KarliaDevisService`. Boucle principale `sync_devis_acceptes(db, force_full)`.

Hypothèses Karlia connues :
- Devis : `id_type=1`, statut accepté = `id_status=2`.
- Bon de commande : `id_type=2` (documenté uniquement dans les logs).
- Custom field "Traité" : `id=66505` posé sur l'opportunité parente du devis.

Rate-limit appliqué :
- `settings.KARLIA_SYNC_SLEEP_SECONDS = 1.2` s en tête de chaque itération (4 appels Karlia max par itération → ~50 req/min en pire cas).
- Helper `_get_with_retry` : 3 retries sur HTTP 429 avec backoffs `[5, 15, 30]` s. Les autres codes (404, 5xx) ne sont pas retryés.
- Historique : sync du 2026-05-20 a saturé Karlia (108 devis en rafale, `get_devis_detail()` silencieusement avalés en 429, 106 commandes créées avec `pdf_url=None`). Rattrapage via `scripts/rattrapage_pdf_url.py`. Diagnostic complet : `docs/DIAGNOSTIC_PDF_COMMANDES.md`.

Méthodes :
- `get_devis_acceptes(depuis_date)` : filtre type=1, status=2 ; sinon **delta** lecture depuis `derniere_synchro_devis` en `parametres`.
- `get_devis_detail(document_id)`, `get_customer_detail(customer_id)`.
- `_is_opportunity_traitee(client, opportunity_id)` / `_marquer_opportunity_traitee(...)` via PATCH du custom field `66505`.
- `_create_commande`, `_update_commande` : persistent dans `commandes` + `commande_lignes` (incluant `discount_*`).
- `_parse_karlia_date(str)` (format `dd/mm/yyyy`), `_parse_tva(any)` (robustifié).

### 1.4 Scheduler
`app.main.synchro_karlia` (séparé de la sync devis) :
- Tâche `AsyncIOScheduler` planifiée chaque jour à **02h00** (`CronTrigger(hour=2, minute=0)`).
- Exécutée aussi **au démarrage** (`startup`).
- Synchronise `ClientCache` puis `ArticleCache` (depuis `/customers` paginé puis `/products?limit=500`).
- Met à jour les `parametres` `derniere_synchro` et `synchro_stats`.

La sync devis (`sync_devis_acceptes`) est déclenchée **manuellement** par l'UI via `POST /api/commandes/sync` ou `POST /api/commandes/sync?force_full=true` ; il n'y a pas de job cron pour cette sync au commit de référence.

## 2. Chorus Pro via PISTE

### 2.1 URLs & environnements
Constantes dans `chorus_service.py` :

| Environnement | OAuth | API factures |
|---|---|---|
| Sandbox (qualification) | `https://sandbox-oauth.piste.gouv.fr/api/oauth/token` | `https://sandbox-api.piste.gouv.fr/cpro/factures/v1` |
| Production | `https://oauth.piste.gouv.fr/api/oauth/token` | `https://api.piste.gouv.fr/cpro/factures/v1` |

Switch par paramètre `chorus_mode_qualification` (`'true'` → sandbox).

### 2.2 Authentification OAuth2
`_get_access_token()` :
- POST sur `oauth_url` avec `Content-Type: application/x-www-form-urlencoded`, payload `grant_type=client_credentials&scope=openid`.
- `auth=(client_id, client_secret)` (BasicAuth httpx) ET header `Authorization: Basic <base64(tech_username:tech_password)>`.
- Token mis en cache pour `expires_in - 300` s (5 min de marge avant expiration).

État réel : **bloqué par un 403 PISTE non résolu** (cf. `MEMORY.md → chorus_pro_blocage.md`). La transmission réelle d'une facture n'a pas encore réussi en production. En base, `transmissions_chorus` contient 6 lignes (toutes en `ECHEC` ou `EN_COURS` selon période), `factures_karlia.statut_chorus` ne compte que `NON_TRANSMISE=30` et `TRANSMISE=2`. À VÉRIFIER ce que recouvrent ces 2 transmises (à confirmer en relisant les enregistrements via psql avant tout reset).

### 2.3 Méthodes (`ChorusProService`)

| Méthode | Endpoint Chorus | Usage |
|---|---|---|
| `tester_connexion()` | (`/api/oauth/token`) | renvoie `{ok, mode}`. |
| `rechercher_structure_destinataire(siret)` | `POST /rechercher/structures` | `typeIdentifiantStructure=SIRET`, `statutStructure=ACTIF`. |
| `consulter_structure(id)` | `POST /consulter/structure` | — |
| `rechercher_services_structure(id)` | `POST /rechercher/services` | — |
| `soumettre_facture(...)` | `POST /soumettre` | payload structuré (voir § 2.4). |
| `consulter_statut_facture(id)` | `POST /consulter/facture` | — |
| `rechercher_factures_emises(...)` | `POST /rechercher/factures/fournisseur` | — |

### 2.4 Payload de soumission (état actuel, branche `main`)

`modeDepot = "SAISIE_API"`. Format JSON Chorus Pro (pas Factur-X) :
- `numeroFactureSaisi`
- `destinataire.codeDestinataire = SIRET`, optionnel `codeServiceExecutant`
- `fournisseur.typeIdentifiantFournisseur = "SIRET"`, `identifiantFournisseur = siret_emetteur` (param `chorus_siret_emetteur`)
- `cadreDeFacturation.codeCadreFacturation = "A1_FACTURE_FOURNISSEUR"`
- `references.deviseFacture = "EUR"`, `typeFacture = "FACTURE"`, `typeTva = "TVA_SUR_DEBIT"`, `modePaiement = "VIREMENT"`, `dateFacture` au format ISO.
- `lignePoste[]` : une ligne unique si pas de détail ; sinon une ligne par article (avec `lignePosteMontantUnitaireHT`, `lignePosteTauxTva`).
- `ligneRecapitulatifTVA` : forcé à 20 % unique au commit de référence (limitation à VÉRIFIER pour des contrats multi-taux).
- `montantTotal.{montantHtTotal, montantTvaTotal, montantTtcTotal, montantAPayer}`.
- `commentaire`.

### 2.5 Branche `feature/chorus-facturx` (non mergée sur main)
Les derniers commits (cf. `git log feature/chorus-facturx`) introduisent :
- Génération Factur-X (CII EN16931 BASIC) + normalisation PDF/A-3 via Ghostscript, et dépôt par `deposer/flux`.
- Endpoint `POST /api/chorus/factures/{id}/rafraichir-statut` + colonnes `chorus_numero_flux` / `chorus_statut_technique` exposées dans l'UI.
- Garde anti-doublon `EN_COURS` relançable + bascule "toutes branches `EN_COURS → ERREUR`" en cas d'incident.
- Omission de `BuyerReference` (BT-10) sur le dépôt — valeur Karlia jugée non fiable.

Ces évolutions ne sont **pas** en production : `main` reste sur `SAISIE_API` (cf. § 2.4). Un script de dry-run `scripts/dryrun_facturx_8906.py` accompagne la branche (untracked sur `main`).

### 2.6 Paramètres Chorus stockés en DB

Clés présentes dans `parametres` (longueurs uniquement, jamais les valeurs) :

| Clé | Présente ? | Notes |
|---|---|---|
| `chorus_client_id` | oui (36) | + backup `chorus_client_id_backup_20260522_160258` (idem 36). |
| `chorus_client_secret` | oui (36) | + backup similaire. |
| `chorus_tech_username` | oui (31) | — |
| `chorus_tech_password` | oui (13) | — |
| `chorus_siret_emetteur` | oui (14) | — |
| `chorus_code_service` | présente, valeur vide | — |
| `chorus_code_banque` | présente, valeur vide | — |
| `chorus_mode_qualification` | oui (5) | string `'true'`/`'false'`. |
| `chorus_id_fournisseur` | présente, valeur vide | utilisé par la branche Factur-X, géré dans `~/contrats-ui/src/pages/Parametres.js` (version build). |
| `chorus_id_utilisateur_courant` | présente, valeur vide | idem. |

Les secrets sont masqués côté API : `GET /api/parametres/chorus` renvoie `'••••••••'` pour `chorus_client_secret` et `chorus_tech_password`. Le `PUT /api/parametres/chorus` ignore les valeurs reçues encore masquées (pas d'écrasement involontaire).

### 2.7 Vue d'ensemble des transmissions

- `POST /api/chorus/transmettre` (router `chorus.py`) ; pour chaque facture :
  1. Skip si statut déjà `TRANSMISE/ACCEPTEE/EN_COURS`.
  2. Skip si `client_siret` manquant.
  3. Crée une ligne `transmissions_chorus` à `EN_COURS`, marque la facture `EN_COURS`.
  4. Appelle `service.soumettre_facture(...)` (synchrone).
  5. En succès : statut `TRANSMISE`, stocke `chorus_numero_flux` (`numeroFluxDepot` ou `idFlux`).
  6. En échec `ChorusError` : statut `ERREUR`, message stocké côté facture **et** dans `message_retour`.
- `POST /api/chorus/synchro-factures` : importe depuis Karlia (filtre `type=4, status=2, limit=500`) → met à jour ou crée des `factures_karlia` (siret repris du `clients_cache` si présent).
- `GET /api/chorus/statistiques` : agrégat par statut Chorus.

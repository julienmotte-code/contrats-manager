# 00 — État des lieux complet — contrats-manager

> ⚠️ **Base de référence unique.** Ce dossier `docs/etat/` remplace tous les audits, notes et états antérieurs (`AUDIT_REFONTE.md`, `BRANCHES.md`, `CHANTIER_2_1_RECAP.md`, `TODO_REFONTE.md`, `PROJECT_CONTEXT.md`, `DIAGNOSTIC_PDF_COMMANDES.md`, etc.). Tout document antérieur est désormais obsolète et ne doit plus servir de source.

## 1. Métadonnées de génération

- Date initiale : **2026-05-23** — mise à jour : **2026-05-25** (ajout factures fournisseurs).
- Commit de référence : `f43cead merge: feat/factures-fournisseurs (v3.2.0)` (branche `main`).
- Branche de travail : `docs/etat-des-lieux-complet` (créée depuis `main` au début de l'opération).
- Tag stable courant : **v3.2.0** (factures fournisseurs).
- Environnement vérifié : docker-compose actif (`db`, `backend`, `frontend` up).

## 2. Table des matières

| Fichier | Contenu |
|---|---|
| [`01-arborescence.md`](01-arborescence.md) | Arborescence complète backend + frontend, lignes par fichier source. |
| [`02-backend.md`](02-backend.md) | Modèles SQLAlchemy, routers/endpoints, services, config, auth, matrice RBAC. |
| [`03-base-de-donnees.md`](03-base-de-donnees.md) | Schéma PostgreSQL réel, volumétries, écarts entre `models.py` et la DB. |
| [`04-frontend.md`](04-frontend.md) | Pages, composants, services API, routing, double localisation des sources. |
| [`05-integrations.md`](05-integrations.md) | Intégration Karlia + Chorus Pro (URLs, payloads, état réel). |
| [`06-workflows.md`](06-workflows.md) | Workflows métier décrits en suivant le code. |
| [`07-deploiement.md`](07-deploiement.md) | docker-compose, nginx, Dockerfiles, `.env` (clés masquées). |

## 3. État d'avancement actuel

### Stable et opérationnel
- **Gestion des contrats** : création, modification (BROUILLON), validation, terminaison, renouvellement (3 cas), traitement en lot (SPONTANE/FIN). 572 contrats en base, 571 EN_COURS.
- **Plan de facturation** : prorata, génération annuelle automatique, révision Syntec (Août/Octobre), Digitech manuel. 1 150 lignes au plan, 571 EMISE.
- **Facturation Karlia** : aperçu → calcul (gardes pré-calcul) → émission (gardes pré- et post-émission, batching avec rate-limit).
- **Sync Karlia** (clients/articles) : auto au démarrage + cron 02h00. 251 clients, 404 articles en cache.
- **Sync devis Karlia** (commandes) : manuelle, rate-limit 1,2 s, retry 429 (backoffs 5/15/30 s). 144 commandes en base, 131 nouvelles. _Note v3.1.0_ : source de synchro bascule sur bons de commande + synchro unifiée depuis le Dashboard.
- **Factures fournisseurs** _(nouveau v3.2.0)_ : création locale de factures fournisseurs à partir des bons de réception (BR) Karlia, avec rapprochement par ligne, filtrage des BR par catégorie de fournisseur (blacklist configurable via `config.py`), brouillon éditable, anti-doublon par pointage à la validation, cache catalogue articles côté service. Routes `/api/factures-fournisseurs/*`. Émission Karlia _non encore activée_ — voir §6 Chantiers ouverts.
- **Prestations** : visibilité filtrée FORMATEUR/TECHNICIEN par `formateur_id`/`agenda_formateur_id`. 11 prestations en base.
- **RBAC** : 4 rôles (ADMIN, GESTIONNAIRE, FORMATEUR, TECHNICIEN), matrice DROITS partagée backend (source `utilisateurs.py:DROITS`) + frontend (copie dans `AuthContext.js`). 12 utilisateurs.
- **Authentification** : JWT HS256, 24 h, bcrypt.
- **Génération Word** : modèles par famille de contrat, publipostage paragraphes + tableaux.
- **Indices Syntec** : 6 lignes (Août/Octobre 2023-2025).
- **Branding SGI** : sidebar, écran de connexion, favicon (depuis v3.0.3).
- **Dashboard formateur/technicien** : 3 tuiles prestations + garde de rôle sur `/api/dashboard/stats` (depuis v3.0.1).

### Partiellement opérationnel / en cours
- **Chorus Pro (transmission)** : code complet (OAuth2 PISTE + payload `SAISIE_API`) sur `main`, mais **transmission bloquée par un 403 PISTE non résolu** côté production (voir `MEMORY.md → chorus_pro_blocage.md`). 32 factures importées, 2 marquées TRANSMISE, 30 NON_TRANSMISE.
- **Refonte Factur-X (Chorus)** : branche `feature/chorus-facturx` (non mergée). Génération CII EN16931 BASIC + PDF/A-3 (Ghostscript) + bascule sur `deposer/flux`, endpoint `/factures/{id}/rafraichir-statut`, UI étendue. Dry-run validé en local sur facture 8906 ; pas encore de premier dépôt réel.
- **Front : double localisation des sources** : `contrats-ui-src/` (versionné) et `~/contrats-ui/` (build) divergent sur 4 fichiers (`App.js`, `pages/{ChorusProPage,Contrats,Parametres}.js`). Le build de production reflète `~/contrats-ui/` — par exemple les paramètres `chorus_id_fournisseur` et `chorus_id_utilisateur_courant` n'apparaissent que dans l'UI buildée. À résorber lors du prochain merge `feature/chorus-facturx`.
- **MUI dans le repo** : `MesPrestations.js` importe `@mui/x-date-pickers` mais `contrats-ui-src/package.json` n'inclut pas MUI — build standalone impossible sans ajout.

### Cassé / connu pour ne pas fonctionner ou inutilisé
- **Table `lots_facturation`** : modèle SQLAlchemy supprimé, table toujours présente en DB (0 ligne) bien que la migration `0002` soit marquée appliquée — drop apparemment non exécuté. À VÉRIFIER avant nettoyage.
- **Colonne `commandes.pdf_devis BYTEA`** : déclarée et présente, mais plus utilisée depuis le commit `f71d223`.
- **Colonnes Google Calendar sur `prestations`** : 4 colonnes (`google_calendar_id`, `google_sync_status`, `google_sync_error`, `google_synced_at`) — service de sync retiré du code. Données partielles conservées (5/11 ont un `google_calendar_id`, 11/11 un `google_sync_status`).
- **Endpoint `/api/utilisateurs/droits`** : exposé côté backend mais **non appelé** par le frontend (les droits sont recalculés en local).
- **`ACCESS_TOKEN_EXPIRE_MINUTES`** dans `config.py` (`= 480`) : jamais lu — `auth.py` impose 24 h en dur.
- **Doublons dans `parametres`** : clés `chorus_client_id_backup_20260522_160258` et `chorus_client_secret_backup_20260522_160258` (sauvegarde ponctuelle), à nettoyer si jugées obsolètes.
- **Valeur par défaut `Utilisateur.role = "UTILISATEUR"`** dans `models.py` : hors matrice. Aucun utilisateur ne porte cette valeur ; piège potentiel pour un compte créé sans rôle explicite.
- **Checks DB non répliqués dans `models.py`** : `ck_statut_chorus` (factures_karlia) et `ck_statut_transmission` (transmissions_chorus) existent côté Postgres mais sont absents des modèles → un `create_all` from scratch ne les recrée pas.

## 4. Chantiers ouverts (au 2026-05-25, post v3.2.0)

### 4.1 Émission de la facture fournisseur dans Karlia — BLOQUÉE
- `POST /suppliers-documents` renvoie `"API not available"` sur l'environnement Karlia courant.
- En attente d'une réponse du support Karlia.
- **Architecture déjà prête côté `contrats-manager`** : colonnes `id_suppliers_document_karlia` et `statut_emission_karlia` nullables sur `factures_fournisseurs` (migration `0003`). Bouton d'émission à ajouter côté UI une fois le endpoint disponible.

### 4.2 Filtre par opportunité / affaire CLIENT — NON FAISABLE en l'état
- Le circuit achat Karlia n'expose aucun lien direct BR → opportunité client.
- Les opportunités fournisseur ne sont pas récupérables individuellement via `GET /opportunities/{id}` (réponse non exploitable).
- À reprendre si un pont achat ↔ vente est identifié côté Karlia (changement d'API ou nouvelle relation côté Karlia).

### 4.3 Piste de performance — cache détails BR
- Au premier chargement de `/facturables` à froid, le temps reste ~18 s (le cache catalogue articles déjà mis en place couvre les articles, pas les détails BR).
- Optimisation potentielle : ajouter un cache TTL pour les détails BR Karlia (`/purchase-receipts/{id}`).
- Non bloquant ; à activer uniquement si l'utilisateur final le ressent.

### 4.4 Bug latent — `karlia_devis_service` confond clients et fournisseurs
- `karlia_devis_service.py` appelle `/customers/{id}` pour certaines entités qui peuvent en réalité être des fournisseurs (devraient passer par `/suppliers/{id}`).
- Conséquence : 404 silencieux possibles, données partielles côté sync devis/commandes.
- À auditer séparément (hors périmètre v3.2.0).

## 5. Comment naviguer ce dossier

1. Commencer par `01-arborescence.md` pour un panorama des fichiers.
2. `02-backend.md` détaille les modèles, routers et services — c'est la référence pour comprendre l'API.
3. `03-base-de-donnees.md` croise le schéma réel et `models.py`, et liste les volumétries et écarts.
4. `04-frontend.md` cartographie les pages, le routing et la double localisation des sources.
5. `05-integrations.md` et `06-workflows.md` plongent dans le métier (Karlia, Chorus Pro, contrats, facturation).
6. `07-deploiement.md` couvre l'infra (Docker, nginx, `.env`).

## 6. Conventions

- "À VÉRIFIER" signale un point non confirmé par lecture directe au moment de la rédaction.
- Les nombres d'enregistrements proviennent d'un `SELECT count(*)` réel et reflètent l'état de la base à la date indiquée.
- Aucun fichier de code, de config ou de données n'a été modifié pendant la rédaction de ce dossier — seuls les fichiers `docs/etat/*.md` ont été créés.

# 04 — Frontend (React 19 + Tailwind)

Sources versionnées dans `contrats-ui-src/` (CRA 5). Build copié dans `contrats-ui/build` puis embarqué dans l'image nginx (cf. § 07).

## 1. Pile technique

`contrats-ui-src/package.json` :

| Paquet | Version |
|---|---|
| react / react-dom | 19.2.4 |
| react-router-dom | 7.13.1 |
| axios | 1.13.6 |
| date-fns | 4.1.0 |
| react-hot-toast | 2.6.0 |
| react-scripts | 5.0.1 |
| web-vitals | 2.1.4 |
| tailwindcss | 3.4.19 (devDep) |
| postcss / autoprefixer | (devDep) |

Builder : `react-scripts build` (CRA, pas de Vite). Pas de TypeScript.

## 2. Double localisation des sources

Deux dossiers existent sur la machine :

| Dossier | Versionné Git ? | Rôle |
|---|---|---|
| `~/contrats/contrats-ui-src/` | ✅ oui (dans ce repo) | source de vérité |
| `~/contrats-ui/` (hors repo) | ❌ non | dossier de build hérité — sert à `npm install` + `npm run build` (CRA), puis `~/contrats/contrats-ui/build/` est utilisé par Docker |
| `~/contrats/contrats-ui/build/` | non (cf. `.gitignore`) | artefact CRA embarqué dans l'image nginx |

`diff -rq ~/contrats/contrats-ui-src/src ~/contrats-ui/src` (au commit de référence) :

```
Files contrats-ui-src/src/App.js and /home/user/contrats-ui/src/App.js differ
Files contrats-ui-src/src/pages/ChorusProPage.js and /home/user/contrats-ui/src/pages/ChorusProPage.js differ
Files contrats-ui-src/src/pages/Contrats.js and /home/user/contrats-ui/src/pages/Contrats.js differ
Files contrats-ui-src/src/pages/Parametres.js and /home/user/contrats-ui/src/pages/Parametres.js differ
```

Constats (diff manuel) :
- `~/contrats-ui/src/App.js` est plus court (78 l. vs 91 l.) et **ne** porte **pas** le routing par rôle (`PrivateRoute allow=...`). Version potentiellement antérieure au RBAC front.
- `~/contrats-ui/src/pages/ChorusProPage.js` est plus long (586 l. vs 496 l.), ajoute notamment `SyncStatusIcon` et un état dédié au rafraîchissement de statut.
- `~/contrats-ui/src/pages/Contrats.js` ajoute la lecture du filtre famille depuis l'URL (`useSearchParams`) et un sélecteur de familles dynamiques.
- `~/contrats-ui/src/pages/Parametres.js` ajoute les champs `chorus_id_fournisseur` et `chorus_id_utilisateur_courant` (cohérents avec les clés vides observées en DB) ainsi qu'un bloc "auto-config Chorus".

`~/contrats-ui/package.json` ajoute aussi les paquets MUI (`@mui/icons-material`, `@mui/x-date-pickers`, `@emotion/*`) qui sont **importés** par `MesPrestations.js` du repo (cf. § 4). Sans ces paquets, le `npm run build` du repo standalone échouera.

Conclusion : les deux dossiers ont divergé. Toute modification du front doit aujourd'hui passer par `contrats-ui-src/` **puis** être propagée dans `~/contrats-ui/` avant `npm run build` (procédure documentée dans `frontend_deployment_procedure.md` côté MEMORY).

## 3. Routing — `src/App.js`

`BrowserRouter` + `Routes` + `AuthProvider`. Garde `PrivateRoute({children, allow})` : redirige `/login` si non auth, sinon `getForbiddenRedirect(user)` (FORMATEUR → `/mes-prestations`, sinon `/`).

| Chemin | Composant | Accès |
|---|---|---|
| `/login` | `Login` | public |
| `/` | `Dashboard` | tout user connecté |
| `/contrats` | `Contrats` | role ≠ `FORMATEUR` |
| `/contrats/nouveau` | `NouveauContrat` | role ≠ `FORMATEUR` |
| `/contrats/tunnel` | `TunnelContrat` | role ≠ `FORMATEUR` |
| `/contrats/:id` | `DetailContrat` | role ≠ `FORMATEUR` |
| `/contrats/:id/modifier` | `ModifierContrat` | role ≠ `FORMATEUR` |
| `/renouvellements` | `Renouvellements` | role ≠ `FORMATEUR` |
| `/facturation` | `Facturation` | role ≠ `FORMATEUR` |
| `/indices` | `Indices` | role ≠ `FORMATEUR` |
| `/clients` | `Clients` | role ≠ `FORMATEUR` |
| `/parametres` | `Parametres` | role ≠ `FORMATEUR` |
| `/utilisateurs` | `Utilisateurs` | role ≠ `FORMATEUR` |
| `/commandes/nouvelles` | `NouvellesCommandes` | role ≠ `FORMATEUR` |
| `/commandes/a-planifier` | `CommandesAPlanifier` | role ≠ `FORMATEUR` |
| `/commandes/planifiees` | `CommandesPlanifiees` | role ≠ `FORMATEUR` |
| `/commandes/terminees` | `CommandesTerminees` | role ≠ `FORMATEUR` |
| `/contrats-a-creer` | `ContratsACreer` | role ≠ `FORMATEUR` |
| `/formateurs` | `Formateurs` | role ≠ `FORMATEUR` |
| `/mes-prestations` | `MesPrestations` | tout user connecté |
| `/chorus-pro` | `ChorusProPage` | role ≠ `FORMATEUR` |
| `*` | redirect `/` | — |

Le contrôle réel des permissions reste **côté backend** (`require_role`) ; le front limite seulement la visibilité dans la barre de navigation et bloque la navigation directe par URL.

## 4. Menu — `src/components/Layout.js`

Trois variantes (`MENU_COMPLET`, `MENU_FORMATEUR`, `MENU_TECHNICIEN`) — choisies via `user?.role`.

### `MENU_COMPLET` (ADMIN / GESTIONNAIRE)
| Section | Item | Droit requis |
|---|---|---|
| — | `/` Tableau de bord | aucun |
| Commandes | `/commandes/nouvelles` | `commandes` |
| Commandes | `/commandes/a-planifier` | `formateurs` |
| Commandes | `/commandes/planifiees` | `commandes` |
| Commandes | `/commandes/terminees` | `commandes` |
| Commandes | `/mes-prestations` | aucun (`forFormateur=true`) |
| Contrats | `/contrats` | `contrats_lecture` |
| Contrats | `/contrats/tunnel?mode=nouveau` | `contrats_ecriture` |
| Contrats | `/contrats-a-creer` | `commandes` |
| Contrats | `/renouvellements` | `contrats_ecriture` |
| Gestion | `/clients` | `contrats_ecriture` |
| Gestion | `/facturation` | `facturation` |
| Gestion | `/indices` | `indices` |
| Gestion | `/chorus-pro` | `facturation` |
| Admin | `/parametres` | `parametres` |
| Admin | `/formateurs` | `utilisateurs` |
| Admin | `/utilisateurs` | `utilisateurs` |

### `MENU_FORMATEUR`
- `/` Tableau de bord
- `/mes-prestations` Mes prestations

### `MENU_TECHNICIEN`
- `/` Tableau de bord
- `/mes-prestations` Mes prestations
- `/contrats` Contrats techniques (sans droit explicite côté menu)

Le filtrage final retire les items dont `droit` n'est pas dans `droits` (passés par `AuthContext`) et nettoie les séparateurs consécutifs/orphelins.

## 5. AuthContext — `src/context/AuthContext.js`

- `AuthProvider` : `useState` pour `user` et `droits`, `loading` initial true.
- Au montage : lit `localStorage.token`, appelle `authAPI.me()` ; en cas de 401, supprime le token.
- `login(username, password)` : POST `/api/auth/login` (form-url-encoded), stocke `access_token` dans `localStorage`, expose user + droits.
- `logout()` : supprime le token, redirige vers `/login`.
- Droits déterminés en local par `getDroitsByRole(role)` — **duplique** la matrice DROITS du backend (`utilisateurs.py`). L'endpoint `/api/utilisateurs/droits` existe côté backend mais **n'est pas appelé** par ce front (la matrice est calculée localement).

## 6. Services HTTP — `src/services/`

### `api.js` (46 l.)
- Axios instance, baseURL vide (le backend est servi via `/api` par nginx).
- Intercepteurs : ajout `Authorization: Bearer <token>` ; 401 → vide token + redirection `/login`.
- Wrappers typés :
  - `authAPI = {login, me}`
  - `clientsAPI = {liste, recherche, creer, synchro}`
  - `contratsAPI = {liste, detail, creer, valider, terminer, renouveler, renouvelerLot, renouvellements}`
  - `produitsAPI = {liste}`
  - `indicesAPI = {liste, creer, courant, supprimer}`
  - `facturationAPI = {apercu, lancer}`
  - `dashboardAPI = {stats}`
- Beaucoup d'appels `api.get/post/put/delete` directs aussi (cf. § 8).

### `pdfFetch.js` (57 l.)
- `openPdfWithAuth(url)` : `fetch(url, {Authorization: Bearer ...})`, transforme la réponse en `Blob`, ouvre via `URL.createObjectURL` dans un nouvel onglet, révoque l'URL après 60 s. Justifié par le fait qu'`window.open` n'envoie pas le header Authorization, et tous les endpoints PDF sont gatés depuis le chantier 2.1.

## 7. Pages — fonctions principales

(extrait des en-têtes et imports lus dans chaque fichier)

| Page | Endpoints/composants notables |
|---|---|
| `Login.js` (34 l.) | Form login, appelle `authAPI.login` puis `navigate('/')`. |
| `Dashboard.js` (231 l.) | `GET /api/dashboard/stats`, `GET /api/synchro/statut`, `POST /api/synchro/lancer`, indice courant. |
| `Contrats.js` (230 l.) | `contratsAPI.liste` avec compteurs par statut, filtre famille (technicien : familles techniques). |
| `NouveauContrat.js` (207 l.) | `contratsAPI.creer` + `indicesAPI` + `clientsAPI` + `produitsAPI`. |
| `TunnelContrat.js` (608 l.) | Workflow guidé multi-étapes : création/renouvellement, calcul + lancement facturation pour la 1ère année. |
| `DetailContrat.js` (254 l.) | Détail contrat, génération document Word (`POST /api/documents/generer/{id}`), terminaison, validation prorata, renouvellement (redirection vers tunnel). |
| `ModifierContrat.js` (219 l.) | `PUT /api/contrats/{id}` (BROUILLON only). |
| `Renouvellements.js` (289 l.) | `contratsAPI.renouvellements`, redirect vers tunnel renouvellement. |
| `Facturation.js` (305 l.) | `GET /api/facturation/apercu/{annee}`, `POST /api/facturation/calculer`, `POST /api/facturation/lancer`. |
| `Indices.js` (183 l.) | CRUD indices Syntec (POST, PUT, DELETE). |
| `Clients.js` (321 l.) | `GET /api/clients`, search Karlia, fiche complète. |
| `Parametres.js` (377 l.) | clé API Karlia, test connexion, vider cache, modèles Word, paramètres Chorus Pro (`PUT/GET /api/parametres/chorus`, `GET /api/chorus/test-connexion`). |
| `Utilisateurs.js` (264 l.) | CRUD utilisateurs (`/api/utilisateurs`). |
| `Formateurs.js` (280 l.) | CRUD formateurs (`/api/formateurs`). |
| `MesPrestations.js` (432 l.) | Vue formateur/technicien sur ses prestations. Utilise `@mui/x-date-pickers` (DatePicker/TimePicker) et `LocalizationProvider AdapterDateFns` — **dépendance MUI absente du `package.json` du repo** ; présente dans `~/contrats-ui/package.json`. |
| `NouvellesCommandes.js` (504 l.) | `GET /api/commandes/stats`, `/nouvelles`, `POST /api/commandes/sync?force_full=`, validation commande (`POST /api/commandes/{id}/valider`). |
| `CommandesAPlanifier.js` (432 l.) | `GET /api/commandes/a-planifier`, attribution formateur via `POST /api/prestations/{from-commande/reattribuer-commande}`. |
| `CommandesPlanifiees.js` (309 l.) | Marquer terminée (`POST /api/commandes/{id}/terminer`). |
| `CommandesTerminees.js` (235 l.) | Facturation commande terminée (`POST /api/commandes/{id}/facturer`). |
| `ContratsACreer.js` (322 l.) | `GET /api/commandes/contrats-a-creer`, redirige vers `/contrats/nouveau` avec préremplissage. |
| `ChorusProPage.js` (496 l.) | `GET /api/chorus/factures`, `statistiques`, `synchro-factures`, `transmettre`, `test-connexion`, `PUT /siret`. |

## 8. Appels API directs (hors wrappers)

Recensés par `grep -E "api\.(get|post|put|delete|patch)"` dans `src/pages/`. Liste représentative :

- Synchro : `POST /api/synchro/lancer`, `GET /api/synchro/statut`.
- Commandes : tous les endpoints `/api/commandes/*` cités au § 02.
- Prestations : `GET /api/prestations?commande_id=…`, `GET /api/prestations/formateur/{id}`, `POST /api/prestations/from-commande/{id}`, `POST /api/prestations/reattribuer-commande/{id}`, `POST /api/prestations/{id}/planifier`.
- Formateurs : `GET /api/formateurs?actif_only=true|false`, CRUD.
- Documents : `GET /api/documents/contrat/{id}`, `POST /api/documents/generer/{id}`, `GET /api/documents/modeles`, upload/patch/delete modèles.
- Indices : `GET /api/indices?...`, `GET /api/indices/familles`.
- Chorus : tous les endpoints décrits au § 02.

## 9. Notes & écarts

- L'unique source partagée de la matrice RBAC est **dupliquée** (backend `DROITS`, frontend `getDroitsByRole`). Toute évolution doit toucher les deux.
- `MesPrestations.js` importe MUI ; un build à partir de `contrats-ui-src/` seul nécessite donc d'ajouter ces dépendances ou de migrer vers les composants existants.
- Les pages `~/contrats-ui/src/...` qui divergent (`App.js`, `Parametres.js`, `Contrats.js`, `ChorusProPage.js`) sont actuellement la base du build de production (les paramètres `chorus_id_fournisseur`/`chorus_id_utilisateur_courant` apparaissent dans l'UI réelle mais pas dans le repo). Cette divergence est connue et trackée dans `MEMORY.md → frontend_deployment_procedure.md` — à résorber au prochain merge.
- Aucun framework de tests effectif (présence de `App.test.js`, `setupTests.js` par défaut CRA, mais pas de tests métier).

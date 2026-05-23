# 06 — Workflows métier

Chaque workflow est décrit en suivant le code. Les références pointent au fichier:ligne quand utile.

## 1. Création d'un contrat

Endpoint : `POST /api/contrats` (`contrats.py:153`). Auth `ADMIN, GESTIONNAIRE`.

Étapes :
1. Vérifie `numero_contrat` unique (sinon `400`).
2. Vérifie `date_fin > date_debut` (sinon `400`).
3. Calcule `prorata` via `contrat_service.calculer_prorata(date_debut, montant_annuel_ht)` :
   - Début au 1er janvier (sans option ½ mois) → pas de prorata.
   - Sinon : `nb_mois = 13 - mois_debut` (avec ajustement si `jour > 15`), `montant = montant_annuel * nb_mois / 12`, option `demi_mois` ajoute `montant/24`.
4. Calcule `nombre_annees` via `calculer_nombre_annees(date_debut, date_fin)`.
5. Insère le `Contrat` en statut `BROUILLON`.
6. Crée les `ContratArticle` (rang 0 = principal, 1-7 = annexes).
7. Génère le plan via `generer_plan_facturation(...)` :
   - Une ligne par année civile, échéance au 1er janvier (sauf année 1 proratée → échéance = `date_debut`).
   - Première année proratée → `type_facture = "PRORATE"` avec `montant_ht_prevu = prorata.montant`.
   - Suivantes → `type_facture = "ANNUELLE"` avec `montant_ht_prevu = montant_annuel_ht`.
8. Persiste tout (commit + refresh) et renvoie le contrat dict + le détail du prorata + le plan.

Modification (`PUT /api/contrats/{id}`, `contrats.py:323`) :
- Refusée si statut ≠ `BROUILLON`.
- Si articles fournis → remplacement total.
- Si `date_debut`/`date_fin`/`montant_annuel_ht` modifiés → recalcul prorata + suppression/regénération complète du plan.

Validation finale (`POST /api/contrats/{id}/valider`, `contrats.py:283`) :
- Refus si statut ≠ `BROUILLON`.
- Refus si aucun article.
- Refus si prorata non validé alors que `prorate_annee1 = true`.
- Passe `statut = EN_COURS`, set `validated_at` et `date_statut_change`.

Suppression (`DELETE /api/contrats/{id}`, `contrats.py:309`) : `BROUILLON` uniquement (cascade DB sur articles + plan).

## 2. Renouvellement d'un contrat

Endpoint unitaire : `POST /api/contrats/{id}/renouveler` (`contrats.py:428`). Action portée par `RenouvellementAction.type_renouvellement` :

### Cas `FIN`
- Statut `TERMINE`, `motif_fin` = `notes` ou "Départ client".

### Cas `SPONTANE`
- `date_fin += 1 an`, recalcule `nombre_annees`.
- Statut `EN_COURS`, ajoute une ligne `PlanFacturation` (`numero_facture = max+1`, `annee = nouvelle_fin.year`, échéance 1er janv., type ANNUELLE, montant = `montant_annuel_ht` du contrat).

### Cas `NOUVEAU_CONTRAT`
- Marque l'ancien `TERMINE` (motif "Remplacé par nouveau contrat").
- Cherche les avenants enfants (`contrat_parent_id = ancien` et `type_contrat='AVENANT'`).
- Crée un nouveau contrat (statut BROUILLON, `type_contrat='RENOUVELLEMENT'`, `contrat_parent_id`=ancien) avec dates calculées (date début = `nouvelle_date_debut` ou ancien `date_fin + 1j`, durée = `nombre_annees`).
- Copie les `ContratArticle` du parent.
- Fusionne les articles des avenants dans les rangs libres (≤ 7), marque les avenants `TERMINE`.
- Génère le plan via `generer_plan_facturation(...)`.

### Lot (`POST /api/contrats/renouveler-lot`, `contrats.py:615`)
Itère sur `ids` ; supporte uniquement `SPONTANE` et `FIN` ; renvoie compteurs `traites`/`erreurs` + détails par contrat.

## 3. Facturation annuelle

Workflow en 3 étapes côté UI (`Facturation.js`).

### a) Aperçu — `GET /api/facturation/apercu/{annee}` (`facturation.py:21`)
Sélectionne les `PlanFacturation` en statut `PLANIFIEE`/`CALCULEE` rattachés à un `Contrat` `EN_COURS` pour l'année cible, joint la règle de révision et la disponibilité des indices nécessaires. Filtre `famille` optionnel.

### b) Calcul — `POST /api/facturation/calculer` (`facturation.py:64`)
Pour chaque `plan_id` :
- Refus si `annee` future.
- Première année du contrat → pas de révision (`taux_revision = 1`).
- Sinon : `valider_pre_calcul(db, plan, nouveau_montant)`.
- Appelle `calculer_revision(db, famille, annee, montant_precedent, nouveau_montant_manuel)` :
  - `SYNTEC_AOUT/OCTOBRE` → `indice_new / indice_ref` (N-1 / N-2 du mois choisi).
  - `MANUELLE` (Digitech) → utilise `nouveau_montant_manuel`.
  - `AUCUNE` → conserve le montant.
- Stocke `montant_revise_ht`, `taux_revision`, `indice_calcul_id`, statut `CALCULEE`.

### c) Émission — `POST /api/facturation/lancer` (`facturation.py:143`)
Pour chaque plan_id (acceptés : `PLANIFIEE`/`CALCULEE`/`EMISE`) :
- **Garde pré-émission** (`valider_pre_emission`) : si erreur, rejet sans appeler Karlia, message renvoyé. WARNING tracé en log (notamment `ID_PRODUCT_MANQUANT`).
- Construit la liste des lignes à partir des articles du contrat, prix unitaire révisé proportionnellement au `taux_revision`, arrondi `ROUND_HALF_UP` ; ajustement de l'écart d'arrondi sur la dernière ligne pour coller au total HT.
- Fallback : si pas d'article, ligne unique avec montant total.
- Appelle `karlia.traitement_lot_factures(...)` (boucle séquentielle avec `sleep(0.8)`).
- Pour chaque retour Karlia :
  - succès → `plan.statut = EMISE`, stocke `facture_karlia_id`/`facture_karlia_ref`, met à jour `montant_annuel_precedent` ; lance `valider_post_emission(plan, r)` (log ERROR si KO).
  - échec → `plan.statut = ERREUR`, message stocké.
- Retourne `{lot_id, traites, emises, erreurs, resultats}`.

## 4. Synchronisation Karlia

### 4.1 Clients + Articles — `synchro_karlia()` (`main.py:51`)
- Auto au démarrage et chaque jour à 02h00 (APScheduler).
- Clients : itère `lister_clients(limit=100)` jusqu'à épuisement, upsert dans `clients_cache` (clé `karlia_id`). Si `client_number` est déjà pris par un autre client local, le nouveau prend `f"K{karlia_id}"` pour éviter l'erreur d'unicité applicative.
- Articles : `lister_produits(limit=500)`, upsert dans `articles_cache`.
- Met à jour `parametres.derniere_synchro` et `parametres.synchro_stats`.

### 4.2 Devis (commandes) — `KarliaDevisService.sync_devis_acceptes` (sync devis)
Déclenché manuellement par `POST /api/commandes/sync` (param `force_full`).
- Lit `parametres.derniere_synchro_devis` (sauf `force_full=true`).
- Récupère les devis acceptés (`id_type=1, id_status=2`).
- Pour chaque devis : 4 appels max (détail devis, customer, vérif opportunité traitée, marquage traité). Sleep `1.2s` entre itérations, retry sur 429.
- Filtre : ignore les devis dont l'opportunité parente porte déjà le custom field `66505 = Traité` côté Karlia.
- Upsert dans `commandes` + `commande_lignes`, puis appelle `_marquer_opportunity_traitee`.
- Sauvegarde la nouvelle borne `derniere_synchro_devis`.

## 5. Pipeline commandes (devis → prestations → facturation)

Vue d'ensemble de cycle de vie (table `commandes`) :
1. `nouvelle` — créé par la sync, `necessite_contrat` calculé.
2. `POST /api/commandes/{id}/valider` (UI `NouvellesCommandes`) : enregistre `type_traitement`, passe en `a_planifier` ou directement plus loin.
3. `POST /api/commandes/{id}/planifier` (UI `CommandesAPlanifier`) : assigne formateur/agenda, statut `planifiee`.
4. `POST /api/commandes/{id}/terminer` (UI `CommandesPlanifiees`) : statut `deployee` (intitulé en base).
5. `POST /api/commandes/{id}/facturer` (UI `CommandesTerminees`) : appelle Karlia pour facturer.
6. `POST /api/commandes/{id}/lier-contrat/{contrat_id}` : rattache la commande à un contrat existant.

Branche commande nécessitant un contrat : `GET /api/commandes/contrats-a-creer` (UI `ContratsACreer`) → redirige `Nouveau contrat` avec préremplissage.

## 6. Prestations (sous-tâches)

Créées depuis une commande : `POST /api/prestations/from-commande/{commande_id}?formateur_id=…` (`prestations.py:219`).
Réattribution : `POST /api/prestations/reattribuer-commande/{commande_id}?formateur_id=…`.

Cycle prestation :
- `a_planifier` (défaut) → `POST /api/prestations/{id}/planifier` (date, lieu) → statut `planifiee`.
- `POST /api/prestations/{id}/realiser` → statut `realisee` (À VÉRIFIER : valeur exacte dépend du code de l'endpoint, à confirmer en lecture détaillée si nécessaire).

Contrôle d'accès (`core/security.py`) :
- ADMIN/GESTIONNAIRE : tout.
- FORMATEUR/TECHNICIEN : voit uniquement ses prestations (`formateur_id` ou `agenda_formateur_id` = son `formateur_id`).
- Sans `formateur_id` lié au compte : 403 systématique.

Colonnes Google Calendar conservées sur `prestations` mais **plus de service de sync actif** (5/11 ont `google_calendar_id`, 11/11 ont `google_sync_status` selon les commentaires du modèle).

## 7. Indices Syntec

CRUD via `/api/indices` (saisie manuelle). Champs : `annee`, `mois ∈ {AOUT, OCTOBRE, AUTRE}`, `valeur`, `famille` (par défaut `SYNTEC`), `commentaire`, `source_url`.

Vérification automatique : `verifier_indices_disponibles(db, famille, annee_facturation)` (appelée par `apercu_facturation` et exposée en `GET /api/indices/verifier/{famille}/{annee}`) renvoie `{ok, message, indices}`.

Suppression sécurisée : `DELETE /api/indices/{id}` (`indices.py:129`) délie d'abord toutes les références `Contrat.indice_reference_id` et `PlanFacturation.indice_calcul_id` avant suppression.

## 8. Transmission Chorus Pro

Workflow (cf. § 05) :
1. `POST /api/chorus/synchro-factures` : importe les factures émises depuis Karlia.
2. UI Chorus Pro (`ChorusProPage`) : sélection multiple, vérification SIRET (édition possible via `PUT /api/chorus/factures/{id}/siret`).
3. `POST /api/chorus/transmettre` : boucle facture par facture, payload `SAISIE_API` envoyé à PISTE.
4. `GET /api/chorus/factures/{id}/transmissions` : historique des tentatives.
5. `GET /api/chorus/statistiques` : agrégat statuts/montants.

État : module bloqué par un 403 PISTE non résolu sur la branche `main`. Refonte en cours sur `feature/chorus-facturx` (Factur-X + `deposer/flux`).

## 9. Génération documentaire (Word)

`POST /api/documents/generer/{contrat_id}` (`documents.py:41`) :
- Charge le contrat + le client cache.
- Sélectionne le modèle Word selon `famille_contrat` (`document_service.FAMILLE_MODELE`) — sinon recherche dans `modeles_documents` (DB).
- Remplit les variables (`{NomClient}`, `{NoContrat}`, etc.) dans paragraphes et tableaux.
- Persiste le DOCX dans `/app/storage/documents_generes/`, crée une ligne `documents_generes`.

`GET /api/documents/telecharger/{doc_id}` renvoie le binaire.
Gestion des modèles (`/api/documents/modeles*`) réservée ADMIN.

# TODO refonte — items différés

Liste des chantiers identifiés au fil de la refonte mais reportés à plus tard.
Chaque entrée précise la référence code, la raison du report, et la priorité.

---

## 🔴 PRIORITÉ ÉLEVÉE — FUITE DE DONNÉES FINANCIÈRES sur Dashboard pour FORMATEUR et TECHNICIEN

- **Référence backend** : `backend/app/api/dashboard.py` (endpoint `GET /api/dashboard/stats`)
- **Référence frontend** : `contrats-ui-src/src/pages/Dashboard.js` (consomme et affiche tous les champs sans filtrage UI)
- **Accès** : page `/` exposée dans `Layout.js` à TOUS les rôles — `MENU_FORMATEUR` (ligne 31) et `MENU_TECHNICIEN` (ligne 38) incluent "Tableau de bord" comme première entrée
- **Description** : l'endpoint `GET /api/dashboard/stats` retourne sans aucun filtrage les KPI globaux du portefeuille à tout utilisateur authentifié. Le chantier 2.1 a ajouté `require_authenticated` (auparavant l'endpoint était même public, sans auth), mais le filtrage par rôle n'est PAS implémenté.

  **Données exposées à un FORMATEUR ou TECHNICIEN authentifié :**
  - `ca_annuel_ht` — chiffre d'affaires annuel total du portefeuille (env. 1 174 405 € en prod)
  - `contrats_par_famille` — répartition revenus par famille de contrats (montants HT/famille)
  - `total_contrats` — effectif portefeuille (env. 572)
  - `a_renouveler_ce_mois` — pipeline commercial
  - `commandes_par_statut` — pipeline commandes (nouvelles, à planifier, planifiées, facturées)

- **Impact** : un FORMATEUR ou TECHNICIEN voit immédiatement à son login le CA total de l'entreprise et la répartition par famille de contrats. **Fuite de données financières confidentielles** qui ne devraient être visibles que pour ADMIN et GESTIONNAIRE.
- **Identifié pendant** : chantier 2.1 (RBAC backend), commit `<dashboard sha>`.
- **Chantier proposé** : `feat/dashboard-filter-by-role` — **À TRAITER EN PRIORITÉ après la Vague 2**, avant les vagues frontend/GCP.

  **Approche suggérée** :
  - Filtrer en backend selon `current_user.role` dans le handler de `/stats`
  - ADMIN + GESTIONNAIRE : conservent toutes les stats actuelles (comportement actuel)
  - FORMATEUR : voit uniquement le nombre et la liste de SES prestations (à venir, planifiées, réalisées). Jamais de CA ni de montants par famille.
  - TECHNICIEN : voit uniquement les contrats "techniques" qui le concernent (critère exact à trancher, cf. audit Q8). Jamais de CA.
  - Alternative : 2 endpoints distincts (`/dashboard/stats` réservé ADMIN+GESTIO, `/dashboard/me` pour FORMATEUR/TECHNICIEN avec payload réduit) — choix d'archi à faire au démarrage du chantier.

- **Priorité** : **ÉLEVÉE (sécurité)** — fuite active, à corriger dès que la Vague 2 est mergée.

---

## Endpoint `PUT /api/commandes/{id}` manquant

- **Référence frontend** : `contrats-ui-src/src/pages/CommandesAPlanifier.js:96`
- **Description** : le frontend appelle `api.put('/api/commandes/${id}', {...})` sur le bouton "Modifier" de la page _Commandes à planifier_, mais l'endpoint backend n'existe pas dans `backend/app/api/commandes.py`. Le bouton retourne donc 404 silencieusement.
- **Identifié pendant** : chantier 2.1 (RBAC backend), grep frontend ↔ backend sur le router commandes.
- **Décision** : à traiter dans un chantier UX dédié. Deux options :
  1. Implémenter l'endpoint backend (créer `PUT /api/commandes/{id}` avec gating `require_role("ADMIN", "GESTIONNAIRE")`)
  2. Retirer le bouton frontend si la fonctionnalité n'est pas voulue
- **Priorité** : faible (régression silencieuse, jamais signalée par les utilisateurs).

---

## Endpoints commandes non utilisés par le frontend (code mort potentiel)

- **Référence backend** :
  - `backend/app/api/commandes.py:335` — `POST /api/commandes/{id}/planifier`
  - `backend/app/api/commandes.py:375` — `POST /api/commandes/{id}/lier-contrat/{contrat_id}`
- **Description** : ces deux endpoints sont implémentés et protégés (RBAC chantier 2.1), mais aucune page React ne les appelle.
- **Identifié pendant** : chantier 2.1 (RBAC backend), grep cohérence frontend ↔ backend.
- **Décision** : à investiguer. Soit pages UI prévues mais non implémentées, soit résidus à supprimer. Ne pas toucher tant qu'on n'a pas confirmation.
- **Priorité** : faible.

---

## Gating frontend granulaire pour les routes sensibles

- **Référence frontend** : `contrats-ui-src/src/App.js:52` (`isNotFormateur`) vs `contrats-ui-src/src/context/AuthContext.js:19-23` (droits TECHNICIEN).
- **Description** : le helper `isNotFormateur` protège les routes `/contrats/tunnel`, `/contrats/nouveau`, `/contrats/:id/modifier`, `/facturation`, `/chorus-pro`, `/utilisateurs`, etc., mais laisse passer le rôle TECHNICIEN. Or les droits granulaires définis dans `AuthContext.getDroitsByRole('TECHNICIEN')` indiquent `contrats_ecriture: false`, `facturation: false`, `utilisateurs: false`. Un TECHNICIEN qui tape l'URL directement (deep-link) accède donc à la page alors qu'il n'a pas le droit métier correspondant.
- **Identifié pendant** : chantier 2.1 (RBAC backend), analyse cohérence frontend ↔ backend sur le router facturation.
- **Impact actuel** : aucun (le backend RBAC bloque en 403 sur les appels d'écriture). Incohérence UX uniquement : l'utilisateur voit la page se charger puis se prend une erreur sur la première action.
- **Chantier proposé** : `feat/frontend-rbac-granular` — remplacer `isNotFormateur` par des gates basés sur `droits.contrats_ecriture` / `droits.facturation` / `droits.utilisateurs` selon la route. À prévoir en Vague 2 ou 3.
- **Priorité** : faible (pas urgent, la défense en profondeur backend est suffisante côté sécurité).

---

## Endpoints prestations sans appel frontend

- **Référence backend** :
  - `backend/app/api/prestations.py:175` — `POST /api/prestations` (création unitaire)
  - `backend/app/api/prestations.py:264` — `PUT /api/prestations/{id}` (édition générale)
- **Description** : ces deux endpoints sont implémentés et protégés (chantier 2.1, `require_role('ADMIN', 'GESTIONNAIRE')`), mais aucune page React ne les appelle. La création se fait via `POST /api/prestations/from-commande/{commande_id}` depuis CommandesAPlanifier. L'édition de date/heure/lieu passe par `POST /api/prestations/{id}/planifier`.
- **Identifié pendant** : chantier 2.1 (RBAC backend), grep cohérence frontend ↔ backend sur le router prestations.
- **Décision** : à investiguer. Soit pages UI prévues mais non implémentées (modification générale, édition admin), soit résidus à supprimer. Ne pas toucher tant qu'on n'a pas confirmation.
- **Priorité** : faible.

---

## UX TECHNICIEN sur DetailContrat — section Documents vide silencieuse

- **Référence frontend** : `contrats-ui-src/src/pages/DetailContrat.js:29` (appel `GET /api/documents/contrat/{id}`), `contrats-ui-src/src/components/Layout.js:37-43` (`MENU_TECHNICIEN` → "Contrats techniques").
- **Description** : DetailContrat est accessible à TECHNICIEN via son menu "Contrats techniques" (lien vers `/contrats`). Avec le RBAC du chantier 2.1, l'API `GET /api/documents/contrat/{id}` retourne 403 pour TECHNICIEN, mais le frontend masque l'erreur via `.catch(() => {})` silencieux. Résultat : la section "Documents générés" apparaît vide pour TECHNICIEN sans aucune explication ni indication que c'est un manque de droits.
- **Identifié pendant** : chantier 2.1 (RBAC backend), commit `b4a3f04` (router documents).
- **Amélioration suggérée** : masquer carrément la section "Documents générés" si `current_user.role` n'est pas dans `('ADMIN', 'GESTIONNAIRE')`, plutôt que d'afficher une section vide. Ou afficher un message explicite "Réservé aux administrateurs et gestionnaires".
- **Chantier proposé** : à intégrer au futur `feat/frontend-rbac-granular` (cf. entrée plus haut).
- **Priorité** : faible (cosmétique, pas de fuite d'info, pas de bug fonctionnel).

---

## Bouton "Synchroniser maintenant" Dashboard visible pour FORMATEUR/TECHNICIEN

- **Référence frontend** : `contrats-ui-src/src/pages/Dashboard.js:155` (bouton), `Dashboard.js:107-118` (fonction `lancerSynchro`).
- **Description** : le bouton "🔄 Synchroniser maintenant" du bandeau synchro Karlia est affiché sans condition de rôle, donc visible aux 4 rôles. Avec le RBAC du chantier 2.1 (`POST /api/synchro/lancer` restreint à ADMIN+GESTIO), un FORMATEUR ou TECHNICIEN qui clique voit le spinner "⏳ Synchronisation..." un instant, puis le bouton redevient cliquable sans aucun feedback (l'erreur 403 est avalée par `console.error` ligne 114). Aucun toast d'erreur.
- **Note importante** : l'appel `useEffect` automatique au mount (lignes 89-93) gère **correctement** le 403 via fallback vers `GET /api/synchro/statut` — donc pas de problème pour la consultation passive. Le bug ne concerne que l'action manuelle.
- **Identifié pendant** : chantier 2.1 (RBAC backend), commit `<main.py sha>`.
- **Amélioration suggérée** : masquer le bouton si `current_user.role` n'est pas dans `('ADMIN', 'GESTIONNAIRE')`, ou afficher un `toast.error('Réservé aux administrateurs et gestionnaires')` dans le catch.
- **Chantier proposé** : à intégrer au futur `feat/frontend-rbac-granular`.
- **Priorité** : faible (cosmétique, fonctionnellement bloqué par backend = pas de risque, juste UX dégradée).

---

## Mapping article rang 0 ↔ catalogue Karlia

### Constat
Sur 572 contrats EN_COURS, seuls **4** ont leur article rang 0 avec `article_karlia_id` défini. Les **568** autres émettent leurs factures Karlia avec un fallback `description` (cf. `backend/app/services/karlia_service.py:193-199`). Le montant facturé est correct (`price_without_tax` + `quantity` toujours envoyés), mais l'article n'est pas lié au catalogue produits côté Karlia.

### Impact actuel
- **Aucun impact financier** : les 571 factures EMISE en prod totalisent 1 196 275 €, **0 facture à 0 €** constatée. Le fallback `description` fonctionne.
- **Impact UX Karlia** : les rapports analytiques par produit catalogue ne reflètent pas la réalité (les factures sans `id_product` apparaissent comme "ligne libre" plutôt que rattachées à un produit du catalogue Karlia).
- **Détection** : depuis le chantier 2.2, `valider_pre_emission` émet un WARNING `ID_PRODUCT_MANQUANT` loggé sur chaque émission concernée (`[PRE-EMISSION-WARN]`).

### Note historique
Le commentaire original de `valider_pre_emission` annonçait à tort que sans `id_product` Karlia enregistrait le montant à 0 €. Vérifié faux en prod (chantier 2.2). Le niveau a été corrigé de ERREUR à WARNING dans le même commit. **Cf. également** : sur les 571 plans EMISE, 568 ont été créés par un import en masse historique (`created_at = 2026-04-20 13:30:44`, identique à la seconde) et n'ont jamais transité par le code Python.

### Action proposée
Chantier `feat/data-cleanup-article-karlia-id` pour matcher les articles rang 0 avec les produits du catalogue Karlia. Heuristique probable : `JOIN articles_cache ON LOWER(designation) = LOWER(...)` ou matching sur `reference`. Validation manuelle possible si les correspondances ne sont pas claires.

### Priorité
Faible — pas de bug actif, juste donnée non optimale pour les analytics Karlia. À traiter quand le rythme le permet.

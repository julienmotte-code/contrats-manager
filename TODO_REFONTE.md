# TODO refonte — items différés

Liste des chantiers identifiés au fil de la refonte mais reportés à plus tard.
Chaque entrée précise la référence code, la raison du report, et la priorité.

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

# Règles de développement — Module Gestion Contrats
# À lire IMPÉRATIVEMENT avant toute modification du code

## 1. IMPORTS FRONTEND

### Toujours vérifier les imports avant d'utiliser une fonction/variable
- `api` (instance axios par défaut) doit être importé explicitement :
```js
  import api, { contratsAPI, clientsAPI } from '../services/api';
```
- Ne pas supposer qu'un import existe déjà — vérifier avec `head -5` ou `grep -n "import"`

### AuthContext — variables exposées
- Le Provider doit exposer TOUTES les variables utilisées dans `value={{...}}`
- Vérifier que `droits`, `user`, `login`, `logout`, `loading` sont bien dans le `value`
- Après ajout d'une variable dans le state, toujours l'ajouter dans `value`

---

## 2. DATES — FORMAT ISO SANS HEURE

### Problème rencontré
`new Date("2026-01-01")` provoque `Invalid time value` en timezone Paris car interprété comme UTC minuit.

### Solution systématique
```js
// ❌ Mauvais
format(new Date(date_publication), 'd MMMM yyyy')
// ✅ Correct
date_publication ? format(new Date(date_publication + 'T12:00:00'), 'd MMMM yyyy') : ''
```

---

## 3. ROUTES FRONTEND

### Toujours faire les 4 étapes lors d'ajout d'une page
1. Créer le fichier `src/pages/MaPage.js`
2. Ajouter l'import dans `App.js`
3. Ajouter la `<Route>` dans `App.js`
4. Ajouter le lien dans `Layout.js` (MENU_COMPLET)

### Format exact des routes dans App.js
```jsx
<Route path="/ma-page" element={<PrivateRoute><MaPage /></PrivateRoute>} />
```

---

## 4. CONTEXTE AUTH ET DROITS

### Problème rencontré
`droits` est `undefined` au premier rendu → crash `can't access property X of undefined`

### Solution
- Initialiser `droits` avec toutes les clés à `true` par défaut dans useState
- Toujours utiliser `droits && droits[item.droit]` (double vérification)
- Toujours inclure `droits` dans le `value` du Provider

---

## 5. CLÉS ÉTRANGÈRES BASE DE DONNÉES

### Problème rencontré
`ForeignKeyViolation` lors de suppression d'un enregistrement référencé par d'autres tables.
Tables connues avec FK vers indices_revision : contrats, plan_facturation, lots_facturation

### Solution systématique
```python
# Délier TOUTES les références avant suppression
db.query(TableA).filter(TableA.fk_id == id).update({"fk_id": None})
db.execute(text("UPDATE table_b SET fk_id = NULL WHERE fk_id = :id"), {"id": id})
db.commit()
db.delete(objet)
db.commit()
```

---

## 6. KARLIA API

### Payload factures validé
```json
{
  "id_customer": 1234567,
  "id_type": 4,
  "id_status": 1,
  "reference": "NUM-CONTRAT",
  "date": "03/03/2026",
  "date_end": "31/12/2026",
  "products_list": [{
    "id_product": "549713",
    "description": "Désignation",
    "price_without_tax": 1500.00,
    "quantity": 1,
    "id_vat": "1"
  }]
}
```
- `id_product` est OBLIGATOIRE pour que le montant soit enregistré
- `id_status: 1` à la création = Brouillon (à valider manuellement dans Karlia)
- `POST /documents/{id}/status` ne fonctionne PAS pour les factures
- `id_vat` : "1"=20%, "2"=10%, "3"=5.5%, "4"=0%

### DNS Docker
- `/etc/docker/daemon.json` → `{"dns": ["8.8.8.8", "8.8.4.4"]}` — ne pas modifier

---

## 7. PATCHES PYTHON

### Toujours vérifier avant d'appliquer
```python
print('found:', old in c)
# Si found: False → chercher le texte exact avec grep/sed avant de continuer
```

---

## 8. REBUILD FRONTEND

### ⚠️ Double localisation des sources React — CRITIQUE
Les sources React existent à DEUX endroits distincts :
- `~/contrats-ui/src/` → utilisé pour le build (npm run build)
- `~/contrats/contrats-ui-src/src/` → versionné dans git

**Toute modification frontend doit être appliquée dans les DEUX dossiers.**
Le git push depuis `~/contrats/` ne voit que `contrats-ui-src/` — si on ne modifie que `contrats-ui/`, le changement est déployé mais pas versionné.

### Séquence complète obligatoire
```bash
# 1. Modifier le fichier dans ~/contrats-ui/src/pages/MaPage.js
# 2. Appliquer la même modification dans ~/contrats/contrats-ui-src/src/pages/MaPage.js
# 3. Build et déploiement
cd ~/contrats-ui && npm run build 2>&1 | tail -5
cp -r ~/contrats-ui/build ~/contrats/contrats-ui/
cd ~/contrats && docker compose up -d --build frontend 2>&1 | tail -5
# 4. Git push (depuis ~/contrats uniquement — c'est le seul repo git)
cd ~/contrats && git add . && git commit -m "message" && git push
```

### Accès
- Module : http://192.168.1.186 (port 80, nginx)
- API : http://192.168.1.186/api/...
- Port 8000 NON accessible directement depuis la VM

---

## 9. MODÈLES SQLALCHEMY

- Toujours mettre à jour models.py après une migration SQL
- `date_publication` sur indices_revision n'est plus unique (Août et Octobre même année)
- Unicité sur `(annee, mois)` pour indices_revision

---

## 10. CHECKLIST APRÈS DÉPLOIEMENT

- [ ] `docker compose logs backend --tail=20 | grep -i error` → aucune erreur
- [ ] Login possible sur http://192.168.1.186
- [ ] Pas de page blanche (F12 Console)
- [ ] Les menus s'affichent correctement
- [ ] L'endpoint modifié répond via curl http://192.168.1.186/api/...

---

## 11. CLÉ API KARLIA — SOURCE UNIQUE DE VÉRITÉ

### Règle absolue
La clé API Karlia **active** est toujours celle stockée en base, table `parametres`, clé `karlia_api_key`.
Elle est chargée au démarrage du backend via l'événement `startup` dans `main.py`.
L'écran Paramètres du module permet de la modifier sans redémarrage.

### `.env` — rôle limité
- `KARLIA_API_KEY` dans `.env` doit rester **vide** en production
- Elle ne sert que de fallback si la base est vide au premier démarrage
- Ne jamais y mettre une clé de production ou de test

### Tests curl depuis la VM
Ne jamais utiliser `$(grep KARLIA_API_KEY ~/contrats/.env)` pour les tests.
Toujours récupérer la clé active depuis la base :
```bash
KARLIA_KEY=$(docker compose exec backend python3 -c "
from app.core.database import SessionLocal
from app.models.models import Parametre
db = SessionLocal()
p = db.query(Parametre).filter(Parametre.cle == 'karlia_api_key').first()
print(p.valeur if p and p.valeur else '')
")
```

### Ne jamais hardcoder l'URL Karlia
`KARLIA_API_URL` est dans `config.py` avec sa valeur par défaut — ne pas la dupliquer ailleurs.

---

## 12. MIGRATIONS DB — ALEMBIC OBLIGATOIRE

### Règle absolue

Tout changement de schéma DB (ALTER TABLE, CREATE TABLE, DROP TABLE, ADD COLUMN,
DROP COLUMN, CREATE INDEX, CREATE CONSTRAINT, etc.) DOIT passer par une migration
Alembic versionnée.

Interdit :
- Exécuter du SQL DDL manuel sur la DB de prod
- Modifier `models.py` sans migration correspondante
- Utiliser `db.execute(text("ALTER TABLE ..."))` dans le code applicatif
- Utiliser `Base.metadata.create_all()` pour créer de nouvelles tables

### Workflow

Voir `backend/alembic/README.md` pour la procédure complète.

Résumé :
1. Modifier `models.py`
2. Créer la migration MANUELLEMENT (autogenerate désactivé tant que la dette
   `server_default` / `Index` / `comment` n'est pas traitée)
3. Tester à blanc sur DB temporaire (upgrade + downgrade)
4. Commit + PR
5. Appliquer en prod avec `alembic upgrade head`

### Pourquoi ?

Avant le chantier 1.4 (mai 2026), toutes les évolutions de schéma se faisaient
à la main, ce qui a produit 8 divergences `models.py` ↔ DB (cf. `AUDIT_REFONTE.md`
§ 2.19). Alembic versionne désormais chaque changement et permet un rollback
sûr en cas d'incident.

---

## 13. RÔLES — 4 COPIES À SYNCHRONISER

### Règle absolue
La notion de rôle est dupliquée à **4 endroits**. Tout ajout ou modification d'un rôle doit être répercuté dans les 4 — un seul oubli provoque une incohérence silencieuse (le rôle existe mais ne fonctionne qu'à moitié).

1. `backend/app/core/security.py` → tuple `ROLES`.
   ⚠️ Si on appelle `require_role("NOUVEAU", …)` sans avoir ajouté le rôle ici, le backend **ne démarre plus** (ValueError levée à l'import).
2. `backend/app/api/utilisateurs.py` → **DEUX** déclarations dans le même fichier :
   - liste `ROLES` (validation create/update user + champ `roles_disponibles` de l'API) ;
   - matrice `DROITS` (ajouter une entrée pour le nouveau rôle).
   Oublier `DROITS` → fallback "FORMATEUR" côté API.
3. `contrats-ui-src/src/context/AuthContext.js` → `getDroitsByRole(role)`.
   C'est CE switch qui pilote réellement l'UI (il n'appelle PAS l'endpoint `/droits`). Rôle absent → tous droits `false` par défaut.
4. `contrats-ui-src/src/pages/Utilisateurs.js` → constante `ROLES` en dur.
   Alimente le `<select>` de création d'utilisateur ET le badge coloré (`roleInfo`, fallback `ROLES[3]`). Oublier ici = le rôle **n'apparaît pas dans la déroulante** (cas vécu chantier DIRECTION) et un user déjà en base s'affiche avec le mauvais badge.

### Pas de migration Alembic
`utilisateurs.role` = `String(30)` libre, aucun CheckConstraint, aucun Enum. La contrainte sur les valeurs de rôle est **purement applicative** (les 4 copies ci-dessus). Ajouter un rôle ne nécessite donc AUCUNE migration.

### Rôle consultatif (lecture seule)
Pour un rôle de consultation : dans `DROITS` et `getDroitsByRole`, tout à `false` SAUF les clés de lecture réellement consommées par ses écrans (ne pas activer un flag « au cas où » — ex. `toutes_prestations` élargit une visibilité non voulue). Côté front, masquer les boutons d'écriture avec le pattern :
`const peutModifier = ['ADMIN','GESTIONNAIRE'].includes(user?.role);` puis `{peutModifier && (…)}`.
Côté backend, NE PAS étendre les `require_role` des routes POST/PUT/DELETE à ce rôle — la barrière 403 reste la vraie sécurité.

### Par ailleurs (lié, mais hors des 4 copies)
Un rôle à **menu dédié** (comme DIRECTION) nécessite aussi une branche dans `contrats-ui-src/src/components/Layout.js` : une constante `MENU_<RÔLE>` + un aiguillage par rôle. Ce n'est pas une copie de la matrice de rôles, mais à ne pas oublier pour que le menu reflète le périmètre voulu.

---

## 14. ATTRIBUTION DES PRESTATIONS PAR FORMATEUR / TECHNICIEN (« owner-scoped »)

Chantier *attribution owner-scoped* : un FORMATEUR ou un TECHNICIEN peut désormais
s'attribuer/réattribuer des prestations depuis les écrans « À planifier » et
« Planifiées », sans passer par un ADMIN/GESTIONNAIRE. Les deux rôles partagent le
même modèle d'ownership (`current_user.formateur_id`).

### 14.1 Visibilité — `GET /api/prestations?include_unassigned=true`
Paramètre optionnel (défaut `False`). Il **n'élargit la visibilité** que si **toutes**
ces conditions sont réunies :
- `include_unassigned=true` **ET** `commande_id` fourni **ET** rôle ∈ {FORMATEUR, TECHNICIEN}
  **ET** `current_user.formateur_id` non nul.

Dans ce cas, la requête est **bornée à la commande** et renvoie : mes prestations
(`formateur_id == moi` ou `agenda_formateur_id == moi`) **+** les prestations
**non affectées** (`formateur_id IS NULL`) de cette commande. **Jamais** les
prestations affectées à un autre intervenant. Hors de ces conditions (pas de
`commande_id`, rôle ADMIN/GESTIO, etc.) le filtre `filter_prestations_for_user`
standard s'applique → **aucune fuite** des NULL en liste globale.
Raison d'être : sans ça, le filtre d'ownership masquerait les prestations NULL et
le self-assign serait impossible depuis l'écran d'affectation.

### 14.2 Attribution — `POST /api/commandes/{id}/affecter-formateurs`
Route ouverte à `ADMIN, GESTIONNAIRE, FORMATEUR, TECHNICIEN`. Pour un rôle
owner-scoped, la **validation d'ownership est faite par prestation**, AVANT tout
side-effect :
- prestation **non affectée** (NULL) → attribuable **uniquement à soi-même** ;
- prestation **à soi** → réattribuable à un formateur actif **ou** libérable (NULL) ;
- prestation **à un autre intervenant** → **403** ;
- ligne no-op (valeur inchangée) → ignorée silencieusement (le front « envoie tout l'état »).
ADMIN/GESTIONNAIRE : comportement **strictement inchangé** (applique tout le payload).
Les raccourcis `from-commande` et `reattribuer-commande` restent **ADMIN/GESTIONNAIRE**.

### 14.3 DETTE ASSUMÉE — visibilité financière des listes
Pour donner aux rôles owner-scoped un point d'entrée vers l'écran d'affectation,
**3 routes GET ont été ouvertes à FORMATEUR/TECHNICIEN SANS filtre** :
`GET /api/commandes/a-planifier`, `GET /api/commandes/planifiees`,
`GET /api/commandes/{id}`. → Ces rôles voient **toutes** ces commandes, **noms
clients et montants inclus**. Choix **explicite et assumé** ; il **aggrave la fuite
financière déjà notée HIGH**. À revisiter si un filtrage des listes par ownership
(ex. ne montrer que les commandes ayant une prestation NULL ou m'appartenant)
devient souhaitable.

### 14.4 NOTE OUVERTE (à investiguer dans un chantier dédié)
Une commande au statut `a_planifier` est *censée* contenir des prestations à
planifier. Or **7 commandes** `a_planifier`/`planifiee` existent **sans aucune
prestation** (lignes uniquement `contrat` / `facturation_directe` / `intitule`).
Constaté **légitime** à ce stade (rien à éclater en prestation), mais à **confirmer
formellement** ou à traiter comme anomalie de validation dans un chantier ultérieur.

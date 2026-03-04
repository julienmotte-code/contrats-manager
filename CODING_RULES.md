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
  "id_status": 2,
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
- `id_status: 2` à la création = Envoyée directement
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

### Séquence complète obligatoire
```bash
cd ~/contrats-ui && npm run build 2>&1 | tail -5
cp -r ~/contrats-ui/build ~/contrats/contrats-ui/
cd ~/contrats && docker compose up -d --build frontend 2>&1 | tail -5
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

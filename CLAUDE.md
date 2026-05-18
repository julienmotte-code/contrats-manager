# CLAUDE.md — Module Gestion Contrats Pluriannuels

## À lire en priorité
- `CODING_RULES.md` — règles obligatoires (imports, dates, FK, Karlia, double dossier React, etc.)
- `PROJECT_CONTEXT.md` — résumé technique
- `README.md` — vue d'ensemble (stack, tables, droits, commandes)

Lire `CODING_RULES.md` **avant toute modification**. Ce fichier-ci ne le remplace pas, il pointe vers lui et fixe la façon de travailler avec moi.

## Communication
- Tutoiement, en français.
- Réponses courtes et directes, pas de récap inutile.
- Si une consigne te paraît ambiguë, demande avant de coder.

## Stack (rappel court)
Backend Python FastAPI + SQLAlchemy + PostgreSQL · Frontend React (CRA) + Tailwind · Docker Compose sur VM Ubuntu `192.168.1.186` · CRM Karlia (API v2) · nginx en reverse proxy.

## Règles de travail

### 1. Double dossier React — CRITIQUE
Les sources React existent à **deux endroits** :
- `~/contrats-ui/src/` → utilisé pour le `npm run build`
- `~/contrats/contrats-ui-src/src/` → versionné dans git

**Toute modification frontend doit être appliquée dans les deux.** Sinon : soit déployé non versionné, soit versionné non déployé.

### 2. Avant d'éditer
- Lire le fichier avec `Read` avant tout `Edit`.
- Vérifier les imports existants (`import api from '../services/api'` etc.) avant d'utiliser une fonction.
- Pour un patch Python, vérifier `found: True` avant d'appliquer.

### 3. Dates côté JS
Toujours `new Date(date + 'T12:00:00')` pour éviter le bug timezone Paris (`Invalid time value`).

### 4. AuthContext
Toute nouvelle variable d'état doit être ajoutée dans le `value={{...}}` du Provider. `droits` initialisé à `true` partout par défaut.

### 5. Nouvelle page React — 4 étapes obligatoires
1. Créer `src/pages/MaPage.js` (dans **les deux** dossiers)
2. Import dans `App.js`
3. `<Route path="..." element={<PrivateRoute><MaPage /></PrivateRoute>} />`
4. Lien dans `Layout.js` (`MENU_COMPLET`)

### 6. Suppression base
Délier toutes les FK avant `db.delete()` (cf. `CODING_RULES.md` §5).

### 7. Karlia
- Clé API active = base, table `parametres`, clé `karlia_api_key`. Jamais hardcoder, jamais lire `.env` pour les tests.
- `id_product` obligatoire dans `products_list`.
- `id_status: 2` à la création = facture envoyée.

## Commandes utiles
```bash
# Backend
cd ~/contrats && docker compose up -d --build backend
docker compose logs backend --tail=20 | grep -i error

# Frontend (séquence complète)
cd ~/contrats-ui && npm run build 2>&1 | tail -5
cp -r ~/contrats-ui/build ~/contrats/contrats-ui/
cd ~/contrats && docker compose up -d --build frontend

# Base
docker compose exec db psql -U contrats_user -d contrats_db

# Git (depuis ~/contrats uniquement)
cd ~/contrats && git add . && git commit -m "message" && git push
```

## Git
- Toujours créer un **nouveau commit** plutôt qu'amender.
- Ne jamais `--no-verify`, ne jamais `push --force` sur `main`.
- Push uniquement depuis `~/contrats/`.

## Checklist post-déploiement
- [ ] `docker compose logs backend --tail=20 | grep -i error` → vide
- [ ] Login OK sur `http://192.168.1.186`
- [ ] Pas de page blanche (F12 Console)
- [ ] Endpoint modifié répond via `curl http://192.168.1.186/api/...`

## Accès
- Module : `http://192.168.1.186` (nginx port 80)
- API : `http://192.168.1.186/api/...` (port 8000 non exposé)
</content>
</invoke>
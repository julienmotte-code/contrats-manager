# Projet — Module Gestion Contrats Pluriannuels
## Stack technique
- Backend : Python FastAPI + SQLAlchemy + PostgreSQL (Docker)
- Frontend : React.js (Create React App) + Tailwind CSS
- Déploiement : Docker Compose sur VM Ubuntu 192.168.1.186
- Accès : http://192.168.1.186 (nginx port 80)
- Backend API : http://192.168.1.186/api (proxy nginx → conteneur port 8000)
- GitHub : https://github.com/julienmotte-code/contrats-manager

## Structure
```
~/contrats/                    # Docker Compose + backend
  backend/app/
    api/                       # Routes FastAPI
      auth.py, contrats.py, facturation.py, indices.py
      utilisateurs.py, parametres.py, clients.py, produits.py
    models/models.py           # Modèles SQLAlchemy
    services/
      karlia_service.py        # Intégration API Karlia
      contrat_service.py       # Logique métier contrats
      revision_service.py      # Calcul révision annuelle Syntec
  CODING_RULES.md              # Règles de développement (LIRE EN PRIORITÉ)
~/contrats-ui/                 # Source React
  src/pages/                   # Pages de l'application
  src/components/Layout.js     # Sidebar + navigation
  src/context/AuthContext.js   # Auth + droits
  src/services/api.js          # Appels API
```

## Fonctionnalités implémentées
- Authentification JWT + gestion utilisateurs (ADMIN/GESTIONNAIRE/CONSULTANT)
- Synchronisation clients/articles depuis API Karlia
- Création/modification/suppression contrats pluriannuels avec avenants
- Familles de contrats : COSOLUCE, CANTINE, DIGITECH, MAINTENANCE, ASSISTANCE_TEL, KIWI_BACKUP
- Révision annuelle : Syntec Août, Syntec Octobre, Manuelle, Prix fixe
- Plan de facturation prévisionnel avec calcul prorata première année
- Émission factures dans Karlia (statut Envoyée directement via id_status:2)
- Gestion indices Syntec (Août/Octobre) par année
- Page facturation : sélection multi-contrats, contrôle indices, blocage années futures

## Base de données (PostgreSQL)
Tables principales :
- contrats (+ famille_contrat, prorate_demi_mois, notes_internes)
- contrat_articles
- plan_facturation (+ montant_annuel_precedent, taux_revision, montant_revise_ht)
- indices_revision (+ annee, mois AOUT/OCTOBRE, famille)
- utilisateurs (role: ADMIN/GESTIONNAIRE/CONSULTANT)
- client_cache, article_cache (sync Karlia)
- parametres (clé API Karlia, etc.)

## API Karlia
- URL : https://karlia.fr/app/api/v2
- Auth : Bearer token (stocké en base table parametres, clé "karlia_api_key")
- Factures : POST /documents avec id_type:4, id_status:2, products_list avec id_product obligatoire
- DNS Docker configuré : /etc/docker/daemon.json → 8.8.8.8

## Commandes utiles
```bash
# Rebuild backend
cd ~/contrats && docker compose up -d --build backend

# Rebuild frontend
cd ~/contrats-ui && npm run build && cp -r build ~/contrats/contrats-ui/
cd ~/contrats && docker compose up -d --build frontend

# Logs
docker compose logs backend --tail=20

# Git push
cd ~/contrats && git add . && git commit -m "message" && git push
```

## Règles importantes
Lire CODING_RULES.md avant toute modification.
Points critiques :
1. Imports frontend : toujours vérifier `import api from '../services/api'`
2. Dates : toujours ajouter T12:00:00 pour éviter erreur timezone
3. AuthContext : `droits` doit être dans le value du Provider
4. Routes : 3 étapes (fichier + import App.js + Route App.js)
5. FK base : délier avant suppression
6. Patches : toujours vérifier `found: True` avant d'appliquer

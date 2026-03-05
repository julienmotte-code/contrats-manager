# Module Gestion Contrats Pluriannuels — SGI Informatique

## Description
Module de gestion des contrats pluriannuels avec facturation automatique dans Karlia CRM.
Développé pour SGI Informatique, il gère les contrats multi-types avec révision annuelle des indices Syntec.

## Stack technique
| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.11 + FastAPI + SQLAlchemy |
| Base de données | PostgreSQL 15 |
| Frontend | React.js 18 (Create React App) + Tailwind CSS |
| Déploiement | Docker Compose (3 conteneurs) |
| Serveur | VM Ubuntu 24 — 192.168.1.186 |
| Reverse proxy | Nginx |
| CRM intégré | Karlia (API v2) |

## Architecture
```
192.168.1.186:80 (nginx)
    ├── /api/* → backend:8000 (FastAPI)
    └── /* → frontend:3000 (React)

Docker Compose :
    contrats-db-1       PostgreSQL
    contrats-backend-1  FastAPI (uvicorn, hot-reload)
    contrats-frontend-1 React (nginx)
```

## Structure du projet
```
~/contrats/                         # Racine du projet (= ce repo)
├── docker-compose.yml
├── .env                            # Variables d'environnement (non versionné)
├── backend/
│   └── app/
│       ├── main.py                 # Point d'entrée FastAPI + routers
│       ├── core/
│       │   ├── config.py           # Settings (env vars)
│       │   └── database.py         # Connexion PostgreSQL
│       ├── models/
│       │   └── models.py           # Modèles SQLAlchemy
│       ├── api/
│       │   ├── auth.py             # JWT login/logout
│       │   ├── contrats.py         # CRUD contrats + avenants
│       │   ├── facturation.py      # Émission factures + révision
│       │   ├── indices.py          # Gestion indices Syntec
│       │   ├── utilisateurs.py     # Gestion utilisateurs + droits
│       │   ├── clients.py          # Cache clients Karlia
│       │   ├── produits.py         # Cache articles Karlia
│       │   ├── parametres.py       # Clé API + config
│       │   └── documents.py        # Documents générés
│       ├── scripts/
│       │   └── gen_modeles.py      # Génère les modèles Word sur la VM
│       └── services/
│           ├── karlia_service.py   # Intégration API Karlia
│           ├── contrat_service.py  # Logique métier contrats
│           ├── revision_service.py # Calcul révision Syntec
│           └── document_service.py  # Génération contrats Word (publipostage)
├── contrats-ui-src/                # Sources React
│   └── src/
│       ├── App.js                  # Routes principales
│       ├── pages/
│       │   ├── Dashboard.js        # Tableau de bord
│       │   ├── Contrats.js         # Liste contrats
│       │   ├── NouveauContrat.js   # Création contrat
│       │   ├── ModifierContrat.js  # Modification contrat
│       │   ├── DetailContrat.js    # Détail + validation
│       │   ├── Facturation.js      # Émission factures
│       │   ├── Indices.js          # Gestion indices Syntec
│       │   ├── Renouvellements.js  # Suivi renouvellements
│       │   ├── Utilisateurs.js     # Gestion utilisateurs
│       │   └── Parametres.js       # Configuration
│       ├── components/
│       │   └── Layout.js           # Sidebar + navigation (droits)
│       ├── context/
│       │   └── AuthContext.js      # Auth JWT + droits utilisateur
│       ├── scripts/
│       │   └── gen_modeles.py      # Génère les modèles Word sur la VM
│       └── services/
│           └── api.js              # Axios + appels API
├── storage/
│   ├── modeles/                    # Modèles Word .docx par famille
│   └── documents_generes/          # Contrats Word générés (non versionné)
├── CODING_RULES.md                 # ⚠️ Lire avant toute modification
└── PROJECT_CONTEXT.md              # Résumé technique rapide
```

## Base de données — Tables principales
| Table | Description |
|-------|-------------|
| `contrats` | Contrats pluriannuels (+ famille_contrat, prorata) |
| `contrat_articles` | Lignes articles par contrat (rang 0=principal, 1-7=annexe) |
| `plan_facturation` | Plan prévisionnel + montants révisés + lien Karlia |
| `indices_revision` | Indices Syntec par année et mois (AOUT/OCTOBRE) |
| `utilisateurs` | Utilisateurs avec rôles (ADMIN/GESTIONNAIRE/CONSULTANT) |
| `client_cache` | Cache clients synchronisé depuis Karlia |
| `article_cache` | Cache articles/produits synchronisé depuis Karlia |
| `parametres` | Configuration (clé API Karlia, etc.) |
| `modeles_documents` | Modèles Word par famille (actif/inactif) |
| `documents_generes` | Historique des contrats Word générés |

## Familles de contrats et révision annuelle
| Famille | Code | Révision | Indice |
|---------|------|----------|--------|
| Cosoluce | COSOLUCE | Automatique | Syntec Août N/N+1 |
| Cantine de France | CANTINE | Automatique | Syntec Octobre N/N+1 |
| Digitech | DIGITECH | Manuelle | Saisie utilisateur |
| Maintenance matériel | MAINTENANCE | Automatique | Syntec Août N/N+1 |
| Assistance Téléphonique | ASSISTANCE_TEL | Automatique | Syntec Août N/N+1 |
| Kiwi Backup | KIWI_BACKUP | Aucune | Prix fixe |

**Formule de révision :** `Prix N = Prix N-1 × (Indice M de N-1 / Indice M de N-2)`
Exemple 2026 (Syntec Août) : `Prix 2026 = Prix 2025 × (Août 2025 / Août 2024)`

## Rôles et droits utilisateurs
| Fonctionnalité | ADMIN | GESTIONNAIRE | CONSULTANT |
|----------------|-------|--------------|------------|
| Tableau de bord | ✅ | ✅ | ✅ |
| Contrats (lecture) | ✅ | ✅ | ✅ |
| Contrats (création/modif) | ✅ | ✅ | ❌ |
| Renouvellements | ✅ | ✅ | ✅ |
| Facturation | ✅ | ✅ | ❌ |
| Indices Syntec | ✅ | ✅ | ❌ |
| Paramètres | ✅ | ❌ | ❌ |
| Utilisateurs | ✅ | ❌ | ❌ |

## Intégration Karlia CRM
- **URL API :** `https://karlia.fr/app/api/v2`
- **Auth :** Bearer token (stocké en base, table `parametres`, clé `karlia_api_key`)
- **Synchronisation :** clients et articles (manuelle + automatique nocturne 2h00)
- **Factures :** créées directement en statut "Envoyée" (`id_status: 2`)
- **Contrainte :** `id_product` obligatoire dans `products_list` pour que le montant soit enregistré
- **DNS Docker :** `/etc/docker/daemon.json` → `{"dns": ["8.8.8.8", "8.8.4.4"]}`

## Commandes utiles
```bash
# Rebuild backend
cd ~/contrats && docker compose up -d --build backend

# Rebuild frontend (depuis les sources)
cd ~/contrats-ui && npm run build
cp -r ~/contrats-ui/build ~/contrats/contrats-ui/
cd ~/contrats && docker compose up -d --build frontend

# Logs
docker compose logs backend --tail=20
docker compose logs backend --tail=20 | grep -i error

# Redémarrage complet
cd ~/contrats && docker compose down && docker compose up -d

# Git push
cd ~/contrats && git add . && git commit -m "message" && git push

# Accès base de données
docker compose exec db psql -U contrats_user -d contrats_db
```

## Variables d'environnement (.env)
```
DATABASE_URL=postgresql://contrats_user:password@db:5432/contrats_db
SECRET_KEY=...
KARLIA_API_KEY=...
KARLIA_API_URL=https://karlia.fr/app/api/v2
TZ=Europe/Paris
```

## Points importants — Pièges connus
Voir `CODING_RULES.md` pour le détail complet.
1. Imports React : toujours vérifier `import api from '../services/api'`
2. Dates : toujours `date + 'T12:00:00'` pour éviter erreur timezone Paris
3. AuthContext : `droits` doit être initialisé avec toutes les clés à `true` ET dans le `value`
4. Nouvelles pages : 4 étapes (fichier + import + Route + menu Layout)
5. FK base : délier toutes les références avant suppression
6. Patches Python : vérifier `found: True` avant d'appliquer

## État du projet (Mars 2026) — v1.3.1
✅ Authentification JWT + gestion utilisateurs avec droits
✅ Synchronisation Karlia (clients + articles)
✅ CRUD contrats pluriannuels + avenants + prorata
✅ Plan de facturation prévisionnel
✅ Révision annuelle par indice Syntec
✅ Émission factures dans Karlia (statut Envoyée)
✅ Gestion indices Syntec Août/Octobre
✅ Interface multi-rôles avec menus dynamiques
✅ Génération contrats Word par publipostage (champs «NomChamp»)
✅ Interface upload/activation modèles Word dans Paramètres
✅ Historique documents générés par contrat

## Notes déploiement
- Les fichiers `storage/documents_generes/` ne devraient pas être versionnés (à ajouter au `.gitignore`)
- Les modèles `storage/modeles/*.docx` sont versionnés comme référence — régénérables via `backend/scripts/gen_modeles.py`
- Clé API Karlia active : table `parametres`, clé `karlia_api_key` (jamais dans `.env` en production)

## Prochaines évolutions prévues
- [ ] Tests unitaires backend
- [ ] Compléter les modèles Word manquants (selon documents SGI originaux)
- [ ] Export PDF des contrats
- [ ] Tableau de bord avec graphiques
- [ ] Notifications renouvellements par email

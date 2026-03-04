# Guide de démarrage — Module Gestion des Contrats
## Installation complète pas à pas

---

## ÉTAPE 1 — Prérequis à installer sur votre machine

### 1.1 Docker Desktop (recommandé — tout-en-un)
Télécharger et installer : https://www.docker.com/products/docker-desktop/
- Windows : installer Docker Desktop → redémarrer
- Mac : installer Docker Desktop
- Linux : `sudo apt install docker.io docker-compose`

### 1.2 Git (pour gérer le code)
Télécharger : https://git-scm.com/downloads

### 1.3 Éditeur de code (facultatif mais recommandé)
VS Code : https://code.visualstudio.com/

---

## ÉTAPE 2 — Récupérer le projet

```bash
# Cloner le dépôt (ou copier le dossier)
git clone <URL_DU_DEPOT> contrats
cd contrats
```

---

## ÉTAPE 3 — Configurer votre clé API Karlia

Dans le dossier `backend/`, créer un fichier `.env` :

```bash
# Sur Windows (PowerShell) :
copy backend\.env.example backend\.env
# Puis ouvrir backend\.env avec notepad et remplir :
#   KARLIA_API_KEY=votre_vraie_cle_ici
#   SECRET_KEY=une_chaine_aleatoire_longue (ex: openssl rand -hex 32)

# Sur Mac/Linux :
cp backend/.env.example backend/.env
nano backend/.env
```

**Important :** Remplir obligatoirement :
- `KARLIA_API_KEY` = votre clé API Karlia
- `SECRET_KEY` = une chaîne aléatoire longue (au moins 32 caractères)

---

## ÉTAPE 4 — Démarrer avec Docker

```bash
# Dans le dossier racine du projet :
docker-compose up -d

# Vérifier que tout tourne :
docker-compose ps
# Vous devez voir : db (healthy) et backend (running)
```

Attendre ~30 secondes au premier démarrage (téléchargement des images).

---

## ÉTAPE 5 — Vérifier que l'API fonctionne

Ouvrir dans votre navigateur :
- http://localhost:8000/api/health  → doit afficher `{"status":"ok"}`
- http://localhost:8000/docs        → Documentation interactive Swagger (utile pour tester)

---

## ÉTAPE 6 — Créer le premier utilisateur administrateur

```bash
# Se connecter au conteneur backend :
docker-compose exec backend python

# Dans Python, taper :
from app.core.database import SessionLocal
from app.models.models import Utilisateur
from passlib.context import CryptContext

db = SessionLocal()
pwd = CryptContext(schemes=["bcrypt"])
admin = Utilisateur(
    login="admin",
    email="votre@email.com",
    nom_complet="Administrateur",
    password_hash=pwd.hash("votre_mot_de_passe"),
    role="ADMIN",
    actif=True,
)
db.add(admin)
db.commit()
print("Admin créé !")
exit()
```

---

## ÉTAPE 7 — Synchroniser les données Karlia

Via la documentation Swagger (http://localhost:8000/docs) :

1. **S'authentifier** : POST /api/auth/token → entrer login/password → copier le token
2. **Cliquer "Authorize"** en haut et coller le token
3. **Synchroniser les clients** : POST /api/clients/synchro
4. **Synchroniser les produits** : POST /api/produits/synchro
5. **Tester** : GET /api/clients → doit retourner vos clients Karlia

---

## ÉTAPE 8 — Tester la connexion Karlia

```
GET http://localhost:8000/api/clients/search?q=nom_client_test
```
→ Doit retourner des résultats depuis Karlia.

---

## ÉTAPE 9 — Premier contrat de test

Via Swagger :
1. POST /api/indices → Ajouter l'indice Syntec actuel
2. POST /api/contrats → Créer un contrat test
3. GET /api/contrats → Vérifier qu'il apparaît
4. POST /api/contrats/{id}/valider → Le valider

---

## Commandes utiles au quotidien

```bash
# Démarrer le module
docker-compose up -d

# Arrêter le module
docker-compose down

# Voir les logs en temps réel
docker-compose logs -f backend

# Redémarrer le backend seul (après modification du code)
docker-compose restart backend

# Sauvegarder la base de données
docker-compose exec db pg_dump -U contrats_user contrats_db > backup_$(date +%Y%m%d).sql

# Restaurer une sauvegarde
docker-compose exec -T db psql -U contrats_user contrats_db < backup_20260301.sql
```

---

## Structure du projet

```
contrats/
├── backend/
│   ├── app/
│   │   ├── main.py              ← Point d'entrée FastAPI
│   │   ├── api/
│   │   │   ├── auth.py          ← Authentification
│   │   │   ├── clients.py       ← Clients Karlia
│   │   │   ├── contrats.py      ← Contrats (CRUD + renouvellements)
│   │   │   ├── facturation.py   ← Traitement en lot
│   │   │   ├── indices.py       ← Indices Syntec
│   │   │   └── produits.py      ← Articles Karlia
│   │   ├── core/
│   │   │   ├── config.py        ← Configuration (.env)
│   │   │   └── database.py      ← Connexion PostgreSQL
│   │   ├── models/
│   │   │   └── models.py        ← Tables de la base de données
│   │   └── services/
│   │       ├── karlia_service.py ← Intégration API Karlia
│   │       └── contrat_service.py ← Logique métier (prorata, révision)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example             ← COPIER en .env et remplir
├── docker-compose.yml
├── data/
│   ├── modeles/                 ← Modèles Word à déposer ici (Phase 4)
│   └── documents/               ← Documents générés
└── GUIDE_DEMARRAGE.md           ← Ce fichier
```

---

## Points d'attention

1. **Quota Karlia** : 100 requêtes/minute maximum. Le module gère automatiquement
   les délais pour le traitement en lot (0,8 sec entre chaque facture = ~75 req/min).

2. **Type "facture" dans Karlia** : L'endpoint Documents de Karlia gère devis, commandes
   et factures. Le champ `type: "invoice"` est utilisé. À valider avec un test réel
   sur votre compte Karlia avant le premier traitement en lot.

3. **Sauvegardes** : Planifier une sauvegarde quotidienne de la base PostgreSQL
   (commande pg_dump ci-dessus).

4. **Phase suivante** : Une fois ce backend validé, on développe le frontend React
   (les écrans de l'interface utilisateur).

---

## En cas de problème

- Logs du backend : `docker-compose logs backend`
- Logs de la BDD : `docker-compose logs db`
- L'API Swagger interactive : http://localhost:8000/docs
- Contacter votre référent technique ou revenir vers Claude avec le message d'erreur exact

# Migrations DB — Alembic

Ce dossier contient les migrations Alembic du module Contrats Manager.

## Workflow standard

Toute évolution de schéma DB DOIT passer par une migration Alembic versionnée.
Plus de SQL ALTER TABLE / DROP / CREATE manuel sur la DB de prod.

### Créer une nouvelle migration

1. Modifier `models.py` si nécessaire (ajout de colonne, contrainte, etc.)
2. Créer la migration MANUELLEMENT (cf. section "Migrations manuelles" ci-dessous) :
   - Copier la dernière migration comme template
   - Incrémenter le numéro (0003, 0004, ...)
   - Renseigner `down_revision` avec le numéro précédent
   - Écrire `upgrade()` et `downgrade()`
3. Tester à blanc sur une DB temporaire (cf. section "Test à blanc")
4. Commit + PR
5. Appliquer en prod avec : `alembic upgrade head`

### Commandes utiles

- `alembic current` → version actuelle de la DB
- `alembic history` → historique des migrations
- `alembic heads` → tête(s) du graphe
- `alembic upgrade head` → appliquer toutes les migrations en attente
- `alembic upgrade +1` → appliquer la migration suivante uniquement
- `alembic downgrade -1` → rollback de la dernière migration
- `alembic downgrade 0001` → rollback jusqu'à une révision donnée

### Convention de naming

Les fichiers de migration doivent suivre le pattern :
`<numero>_<slug_ascii>.py` (ex: `0003_add_user_preferences.py`)

- Numéro à 4 chiffres, incrémental
- Slug en ASCII pur (pas d'accents, espaces remplacés par `_`)
- `revision = '<numero>'` et `down_revision = '<numero_precedent>'`

## Migrations manuelles

**Toutes les migrations sont écrites à la main** dans ce projet, sans utiliser
`alembic revision --autogenerate`.

### Pourquoi ?

`models.py` est aujourd'hui moins riche que la DB :
- Pas de `server_default=...` (seulement `default=...` Python)
- Pas d'`Index(...)` pour les indexes secondaires créés manuellement
- Pas de `comment=...` sur les tables/colonnes

Conséquence : `alembic revision --autogenerate` produit 30+ opérations
parasites (drop d'indexes de performance, drop de server_defaults, etc.)
qui dégraderaient la DB si appliquées. Lors du chantier 1.4, deux migrations
ont été essayées en autogenerate, toutes deux inutilisables.

Tant que la dette `models.py` n'est pas traitée (chantier reporté en Vague 2),
les migrations sont rédigées à la main avec exactement les opérations voulues.

### Template de migration manuelle

```python
"""<description courte>

Revision ID: <numero>
Revises: <numero_precedent>
Create Date: <YYYY-MM-DD>

<description longue : pourquoi cette migration, contexte, ticket/chantier>
"""
from alembic import op
import sqlalchemy as sa


revision = '<numero>'
down_revision = '<numero_precedent>'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Opérations explicites uniquement, pas d'autogenerate
    pass


def downgrade() -> None:
    # Inverse strict de upgrade() pour permettre un rollback
    pass
```

## Test à blanc obligatoire

**Chaque migration DOIT être testée à blanc** sur une DB temporaire avant
d'être appliquée en prod. C'est non négociable.

### Procédure

```bash
# 1. Dump de la DB de prod (schéma + données critiques)
docker compose exec -T db pg_dump -U contrats -d contrats --schema-only > /tmp/schema_prod.sql
docker compose exec -T db pg_dump -U contrats -d contrats --data-only -t <table_concernee> > /tmp/data.sql

# 2. Création DB temporaire
docker compose exec -T db psql -U contrats -d postgres -c "CREATE DATABASE contrats_test_migration;"

# 3. Restore (via stdin car -f cherche dans le conteneur, pas sur l'hôte)
cat /tmp/schema_prod.sql | docker compose exec -T db psql -U contrats -d contrats_test_migration
cat /tmp/data.sql        | docker compose exec -T db psql -U contrats -d contrats_test_migration

# 4. Stamp à la version précédente
docker compose run --rm \
  -e DATABASE_URL="postgresql://contrats:${DB_PASSWORD}@db:5432/contrats_test_migration" \
  backend alembic stamp <version_precedente>

# 5. Test upgrade
docker compose run --rm \
  -e DATABASE_URL="postgresql://contrats:${DB_PASSWORD}@db:5432/contrats_test_migration" \
  backend alembic upgrade head

# 6. Vérifications manuelles via psql (structure conforme aux attentes)

# 7. Test downgrade
docker compose run --rm \
  -e DATABASE_URL="postgresql://contrats:${DB_PASSWORD}@db:5432/contrats_test_migration" \
  backend alembic downgrade -1

# 8. Vérifications manuelles via psql (état revenu identique à avant upgrade)

# 9. Cleanup
docker compose exec -T db psql -U contrats -d postgres -c "DROP DATABASE contrats_test_migration;"
rm -f /tmp/schema_prod.sql /tmp/data.sql
```

La migration n'est appliquée en prod QUE si upgrade ET downgrade passent sans
erreur sur la DB temporaire.

## Application en prod

Une fois la migration testée à blanc et la PR mergée :

```bash
cd ~/contrats
git checkout main
git pull
docker compose build backend
docker compose run --rm backend alembic upgrade head
docker compose up -d backend
docker compose logs backend --tail=20 | grep -i error
```

Toujours vérifier `alembic current` après application pour confirmer la version.

## Notes historiques

### Baseline 0001 (no-op)

La migration `0001` est un no-op intentionnel (`upgrade(): pass`,
`downgrade(): pass`). Elle a été créée et stampée lors du chantier 1.4 pour
intégrer Alembic à une DB existante.

Conséquence : `alembic upgrade head` sur une DB vierge ne recréera PAS le schéma.
Pour créer une nouvelle instance, restaurer d'abord un dump SQL de la prod, puis
`alembic stamp head`, puis appliquer les migrations suivantes.

### Pourquoi pas d'autogenerate ?

Voir section "Migrations manuelles" ci-dessus. Le contournement est tracé dans
les commits `cf8c662` (baseline) et `ded43e2` (0002) de la branche
`chore/alembic-setup`.

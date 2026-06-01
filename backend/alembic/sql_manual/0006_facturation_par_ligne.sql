-- Migration 0006 — facturation par ligne sur commande_lignes
-- Idempotente (IF NOT EXISTS). Équivalent SQL de la révision Alembic
-- 0006_add_facturation_par_ligne_to_commande_lignes.py. Sans danger si les
-- colonnes existent déjà.
--
-- Application directe (hors Alembic) si besoin :
--   docker compose exec -T db psql -U contrats -d contrats -f - < ce_fichier.sql
--
ALTER TABLE commande_lignes ADD COLUMN IF NOT EXISTS facture_karlia_id  VARCHAR(255);
ALTER TABLE commande_lignes ADD COLUMN IF NOT EXISTS facture_karlia_ref VARCHAR(255);
ALTER TABLE commande_lignes ADD COLUMN IF NOT EXISTS date_facturee      TIMESTAMP;

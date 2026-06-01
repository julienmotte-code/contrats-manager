-- Migration 0008 — facturation par prestation sur prestations.
-- Idempotente (IF NOT EXISTS). Équivalent SQL de la révision Alembic
-- 0008_add_facturation_par_prestation.py. Miroir de 0006 (commande_lignes).
--
ALTER TABLE prestations ADD COLUMN IF NOT EXISTS facture_karlia_id  VARCHAR(255);
ALTER TABLE prestations ADD COLUMN IF NOT EXISTS facture_karlia_ref VARCHAR(255);
ALTER TABLE prestations ADD COLUMN IF NOT EXISTS date_facturee      TIMESTAMP;

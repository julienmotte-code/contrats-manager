-- Migration 0007 — backfill facturation par ligne pour commandes déjà
-- facturées au niveau commande (ancien flux). Idempotente (cl.facture_karlia_id
-- IS NULL). Équivalent SQL de la révision Alembic
-- 0007_backfill_facturation_lignes_commandes_facturees.py.
--
-- Périmètre strict : lignes 'facturation_directe' d'une commande facturée
-- (commande.facture_karlia_id NOT NULL) dont la ligne n'est pas encore marquée.
--
UPDATE commande_lignes cl
SET facture_karlia_id  = c.facture_karlia_id,
    facture_karlia_ref = c.facture_karlia_ref,
    date_facturee      = COALESCE(c.updated_at, NOW())
FROM commandes c
WHERE cl.commande_id = c.id
  AND cl.destination = 'facturation_directe'
  AND c.facture_karlia_id IS NOT NULL
  AND cl.facture_karlia_id IS NULL;

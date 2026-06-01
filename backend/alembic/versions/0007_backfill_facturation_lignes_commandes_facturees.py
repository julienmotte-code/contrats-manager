"""backfill facturation par ligne pour commandes deja facturees (commande-level)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-01

Avant la migration 0006, la facturation se faisait AU NIVEAU COMMANDE
(ancien POST /commandes/{id}/facturer) : seules commandes.facture_karlia_id /
facture_karlia_ref et commandes.statut='facturee' étaient renseignés, jamais
les lignes. Conséquence : les lignes 'facturation_directe' de ces commandes
déjà facturées ont facture_karlia_id IS NULL et réapparaissent comme « à
facturer » dans le nouvel endpoint /commandes/lignes-a-facturer → RISQUE DE
DOUBLE FACTURATION dès l'activation du frontend (étape 2 / v3.5.0).

Ce backfill propage la trace de facturation commande → ligne pour ces seules
lignes :
  - facture_karlia_id  ← commandes.facture_karlia_id
  - facture_karlia_ref ← commandes.facture_karlia_ref (peut être '' sur les
                         commandes historiques : Karlia n'a pas renvoyé de
                         référence ; sans incidence, l'anti-doublon repose sur
                         facture_karlia_id non NULL)
  - date_facturee      ← COALESCE(commandes.updated_at, NOW())
                         updated_at est posé par l'ancien facturer_commande au
                         moment de l'émission : c'est le proxy le plus précis
                         disponible (aucun champ date_facturation dédié sur
                         commandes). NOW() = fallback défensif jamais atteint
                         (updated_at a un server_default).

Périmètre strict (WHERE) :
  - cl.destination = 'facturation_directe'
  - c.facture_karlia_id IS NOT NULL   (commande effectivement facturée)
  - cl.facture_karlia_id IS NULL      (ligne pas encore marquée)

Idempotente : la clause cl.facture_karlia_id IS NULL garantit qu'un second
passage ne touche aucune ligne.

Dry-run au moment de la rédaction (2026-06-01) : 3 lignes attendues, 1 par
commande, sur BC26-0030 (699354), BC26-0098 (699697), BC26-0099 (699802).
"""
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE commande_lignes cl
        SET facture_karlia_id  = c.facture_karlia_id,
            facture_karlia_ref = c.facture_karlia_ref,
            date_facturee      = COALESCE(c.updated_at, NOW())
        FROM commandes c
        WHERE cl.commande_id = c.id
          AND cl.destination = 'facturation_directe'
          AND c.facture_karlia_id IS NOT NULL
          AND cl.facture_karlia_id IS NULL
        """
    )


def downgrade():
    # Backfill de données NON réversible de façon sûre : une fois posée, la
    # trace de facturation au niveau ligne est indistinguable d'une facturation
    # par ligne légitime (endpoint /commandes/facturer-lignes). Annuler en
    # masse risquerait d'effacer des marquages corrects. No-op volontaire :
    # restaurer depuis une sauvegarde DB si un rollback est réellement requis.
    pass

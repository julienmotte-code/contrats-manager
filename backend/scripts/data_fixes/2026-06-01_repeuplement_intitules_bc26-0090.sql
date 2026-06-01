-- Data fix ponctuel (2026-06-01) — NON rejouable sur une autre base.
-- IDs spécifiques à la base de production ubuntusgi : ce n'est PAS une migration
-- de schéma (pas dans alembic/versions). Conservé pour traçabilité.
--
-- Contexte : BC26-0090 (ancienne commande, section_karlia jamais marquée) porte
-- 4 lignes d'INTITULÉ à 0€ (titres de section + sous-totaux) qui remontaient à
-- tort dans "Lignes à facturer". On les marque section_karlia=1 (vrai marqueur),
-- seul critère d'exclusion retenu (jamais le montant). Cf. diag terminees-par-lignes.
--
--   1042 "TOTAL ABONNEMENT (1an)"  (avait été facturée par erreur au test visuel)
--   1043 "CERTIFICAT POUR UN AN"
--   1045 "PRESTATION"
--   1047 "TOTAL PRESTATION"
--
-- Backup préalable : backup_cl_repeuplement_intitules_20260601_125240.sql

-- 1) Repeuplement section_karlia=1 sur les 4 intitulés.
UPDATE commande_lignes SET section_karlia = 1
WHERE id IN (1042, 1043, 1045, 1047);

-- 2) Nettoyage de l'artefact de test sur 1042 : le brouillon Karlia 704359
--    (émis sans id_opportunity pendant le test) est supprimé manuellement côté
--    CRM ; un intitulé n'a de toute façon pas à porter un id de facture.
UPDATE commande_lignes
SET facture_karlia_id = NULL, facture_karlia_ref = NULL, date_facturee = NULL
WHERE id = 1042;

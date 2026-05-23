# 03 — Base de données PostgreSQL

Connexion : conteneur `contrats-db-1` (`postgres:16`), base `contrats`, utilisateur `contrats`, mot de passe via variable d'env `DB_PASSWORD`.

Commandes utilisées :
- `docker compose exec -T db psql -U contrats -d contrats -c "\dt"`
- `docker compose exec -T db psql -U contrats -d contrats -c "\d <table>"`
- `SELECT count(*) ...` pour les volumétries.
- `SELECT version_num FROM alembic_version` → **0002**.

## 1. Tables présentes

```
public | alembic_version       | table
public | articles_cache        | table
public | clients_cache         | table
public | commande_lignes       | table
public | commandes             | table
public | contrat_articles      | table
public | contrats              | table
public | documents_generes     | table
public | factures_karlia       | table
public | formateurs            | table
public | indices_revision      | table
public | lots_facturation      | table
public | modeles_documents     | table
public | parametres            | table
public | plan_facturation      | table
public | prestations           | table
public | transmissions_chorus  | table
public | utilisateurs          | table
```

18 tables. Aucune n'est manquante côté DB par rapport aux modèles SQLAlchemy.

## 2. Volumétries

| Table | Lignes |
|---|---|
| alembic_version | 1 |
| articles_cache | 404 |
| clients_cache | 251 |
| commande_lignes | 229 |
| commandes | 144 |
| contrat_articles | 572 |
| contrats | 572 |
| documents_generes | 1 |
| factures_karlia | 32 |
| formateurs | 7 |
| indices_revision | 6 |
| lots_facturation | 0 |
| modeles_documents | 4 |
| parametres | 16 |
| plan_facturation | 1150 |
| prestations | 11 |
| transmissions_chorus | 6 |
| utilisateurs | 12 |

### Statuts vivants

- `contrats.statut` : `EN_COURS = 571`, `TERMINE = 1`.
- `plan_facturation.statut` : `PLANIFIEE = 578`, `EMISE = 571`, `CALCULEE = 1`.
- `factures_karlia.statut_chorus` : `NON_TRANSMISE = 30`, `TRANSMISE = 2`.
- `commandes.statut` : `nouvelle = 131`, `a_planifier = 9`, `facturee = 2`, `planifiee = 1`, `deployee = 1`.
- `utilisateurs.role` : `FORMATEUR = 5`, `GESTIONNAIRE = 3`, `ADMIN = 2`, `TECHNICIEN = 2`. Aucun rôle hors matrice.

### Indices Syntec en base

| Mois | Année | Valeur |
|---|---|---|
| AOUT | 2023 | 305.7000 |
| OCTOBRE | 2023 | 306.7000 |
| AOUT | 2024 | 314.1000 |
| OCTOBRE | 2024 | 315.0000 |
| AOUT | 2025 | 321.1000 |
| OCTOBRE | 2025 | 322.2000 |

### Clés de la table `parametres`

Longueur uniquement (les valeurs ne sont pas affichées).

```
chorus_client_id                            (36)
chorus_client_id_backup_20260522_160258     (36)
chorus_client_secret                        (36)
chorus_client_secret_backup_20260522_160258 (36)
chorus_code_banque                          (0)
chorus_code_service                         (0)
chorus_id_fournisseur                       (0)
chorus_id_utilisateur_courant               (0)
chorus_mode_qualification                   (5)
chorus_siret_emetteur                       (14)
chorus_tech_password                        (13)
chorus_tech_username                        (31)
derniere_synchro                            (16)
derniere_synchro_devis                      (26)
karlia_api_key                              (34)
synchro_stats                               (25)
```

Notes :
- Deux clés `*_backup_20260522_160258` traînent — backup ponctuel à nettoyer si jugé obsolète.
- `chorus_id_fournisseur` et `chorus_id_utilisateur_courant` sont **présents en base mais vides** ; ces clés apparaissent dans `/home/user/contrats-ui/src/pages/Parametres.js` (version build) mais pas dans `contrats-ui-src/src/pages/Parametres.js` (cf. § 04).

## 3. Schéma réel par table (sortie `\d`)

### `alembic_version`
- `version_num VARCHAR(32) NOT NULL`, PK `alembic_version_pkc`.

### `articles_cache`
- `id UUID NOT NULL`, PK ; `karlia_id VARCHAR(100) NOT NULL` UNIQUE.
- `reference VARCHAR(100)`, `designation VARCHAR(500) NOT NULL`, `prix_unitaire_ht NUMERIC(12,4)`, `unite VARCHAR(50)`, `taux_tva NUMERIC(5,2)`, `actif BOOLEAN`, `synchro_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ DEFAULT now()`.

### `clients_cache`
- `id UUID NOT NULL` PK ; `karlia_id VARCHAR(100) NOT NULL` UNIQUE ; `numero_client VARCHAR(20) NOT NULL` (pas d'UNIQUE DB).
- `nom VARCHAR(255) NOT NULL` ; `adresse_ligne1`, `adresse_ligne2 VARCHAR(255)` ; `code_postal VARCHAR(10)`, `ville VARCHAR(100)`, `pays VARCHAR(100)`.
- `email VARCHAR(255)`, `telephone VARCHAR(30)`, `mobile VARCHAR(30)`.
- `siret VARCHAR(14)`, `tva_intracom VARCHAR(20)`, `forme_juridique VARCHAR(100)`.
- `contact_nom VARCHAR(150)`, `contact_prenom VARCHAR(150)`, `contact_fonction VARCHAR(150)`.
- `notes TEXT`, `synchro_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ DEFAULT now()`.

### `commande_lignes`
- `id SERIAL` PK ; `commande_id INT` FK CASCADE → `commandes(id)`.
- `karlia_product_id VARCHAR(50)`, `designation VARCHAR(500)`, `description TEXT`.
- `quantite NUMERIC(10,3) DEFAULT 1`, `unite VARCHAR(50)`, `prix_unitaire_ht NUMERIC(15,2)`, `taux_tva NUMERIC(5,2)`, `montant_ht/tva/ttc NUMERIC(15,2)`.
- `ordre INT DEFAULT 0`, `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` (sans timezone).
- `discount_type VARCHAR(20)`, `discount_value NUMERIC(15,6)`, `discount_percent NUMERIC(15,6)`.
- Index `idx_commande_lignes_commande_id`.
- Référencée par `prestations.commande_ligne_id` (SET NULL).

### `commandes`
- `id SERIAL` PK ; `karlia_document_id INT NOT NULL UNIQUE`.
- `karlia_customer_id INT`, `karlia_opportunity_id INT`, `reference_devis VARCHAR(100)`.
- Snapshot client : `client_nom`, `client_email`, `client_telephone`, `client_adresse TEXT`, `client_siret`.
- Montants : `montant_ht/tva/ttc NUMERIC(15,2)`.
- Dates : `date_devis DATE`, `date_acceptation DATE`, `date_import TIMESTAMP DEFAULT CURRENT_TIMESTAMP`, `date_validation TIMESTAMP`, `created_at`, `updated_at` (tous **sans** timezone).
- Statut : `statut VARCHAR(50) DEFAULT 'nouvelle'`, `type_traitement`, `necessite_contrat BOOL DEFAULT false`, `date_planifiee DATE`, `intervenant_id INT`, `intervenant_nom`, `notes_planification TEXT`.
- FK : `contrat_id UUID → contrats.id ON DELETE SET NULL` ; `formateur_id INT → formateurs.id`.
- `pdf_devis BYTEA` (non utilisé), `pdf_devis_nom`, `pdf_url TEXT`, `created_by INT`, `updated_by INT`.
- `facture_karlia_id VARCHAR(50)`, `facture_karlia_ref VARCHAR(50)`.
- Index : `idx_commandes_formateur`, `idx_commandes_karlia_id`, `idx_commandes_necessite_contrat`, `idx_commandes_statut`.

### `contrat_articles`
- `id UUID` PK ; `contrat_id UUID NOT NULL` FK CASCADE.
- `rang INT NOT NULL`, contrainte `ck_rang_valide CHECK (rang BETWEEN 0 AND 7)`.
- UNIQUE `(contrat_id, rang)` → `uq_contrat_rang`.
- `article_karlia_id VARCHAR(100)`, `designation VARCHAR(500) NOT NULL`, `reference VARCHAR(100)`, `prix_unitaire_ht NUMERIC(12,4)`, `quantite NUMERIC(10,3)`, `unite VARCHAR(50)`, `taux_tva NUMERIC(5,2)`.

### `contrats`
Voir § 02 pour la liste exhaustive ; en DB, les contraintes effectives sont :
- `ck_dates_coherentes CHECK (date_fin > date_debut)`.
- `ck_statut CHECK (statut IN ('EN_COURS','A_RENOUVELER','TERMINE','BROUILLON'))`.
- `ck_type_contrat CHECK (type_contrat IN ('CONTRAT','AVENANT','RENOUVELLEMENT'))`.
- FK : `contrat_parent_id → contrats.id`, `indice_reference_id → indices_revision.id`.
- Référencée par `commandes`, `contrat_articles`, `documents_generes`, `factures_karlia`, `plan_facturation` (CASCADE), `contrats` (self).
- `famille_contrat VARCHAR(50) DEFAULT 'COSOLUCE'`, `prorate_demi_mois BOOL DEFAULT false`, `notes_internes TEXT` — ces 3 colonnes sont bien présentes côté DB et côté model.

### `documents_generes`
- `id UUID` PK ; `contrat_id UUID NOT NULL` FK (sans CASCADE).
- `type_document VARCHAR(50) NOT NULL`, `nom_fichier VARCHAR(500) NOT NULL`, `chemin_docx`, `chemin_pdf VARCHAR(1000)`, `modele_utilise`, `variables_json JSON`, `generated_by`, `generated_at TIMESTAMPTZ DEFAULT now()`.

### `factures_karlia`
- `id UUID DEFAULT gen_random_uuid()` PK ; `karlia_document_id INT NOT NULL UNIQUE`.
- `numero_facture VARCHAR(100) NOT NULL`, `reference VARCHAR(200)`.
- `client_karlia_id INT NOT NULL`, `client_nom VARCHAR(255)`, `client_siret VARCHAR(14)`, `client_code_service VARCHAR(100)`.
- Montants `NUMERIC(15,2)` (`montant_ht NOT NULL`).
- `date_facture NOT NULL`, `date_echeance`.
- `statut_chorus VARCHAR(50) DEFAULT 'NON_TRANSMISE'`, `date_transmission TIMESTAMPTZ`, `chorus_numero_flux`, `chorus_statut_technique`, `chorus_date_statut TIMESTAMPTZ`, `chorus_message_erreur TEXT`.
- FK `contrat_id UUID → contrats.id ON DELETE SET NULL`.
- Indices : `idx_factures_karlia_client`, `idx_factures_karlia_date`, `idx_factures_karlia_statut`.
- Check **DB seulement** : `ck_statut_chorus IN ('NON_TRANSMISE','EN_COURS','TRANSMISE','ACCEPTEE','REJETEE','ERREUR')` — **absent du modèle SQLAlchemy**.

### `formateurs`
- `id SERIAL` PK ; `nom VARCHAR(255) NOT NULL`, `prenom`, `email VARCHAR(255) NOT NULL UNIQUE`, `email_google`, `telephone`, `actif BOOL DEFAULT true`, `couleur VARCHAR(7) DEFAULT '#3788d8'`, `created_at`, `updated_at` TIMESTAMPTZ.
- Référencée par `commandes`, `prestations.formateur_id`, `prestations.agenda_formateur_id`, `utilisateurs.formateur_id`.

### `indices_revision`
- `id UUID` PK ; `date_publication DATE NOT NULL`, `valeur NUMERIC(10,4) NOT NULL`, `commentaire TEXT`, `source_url`, `created_by VARCHAR(100)`, `created_at TIMESTAMPTZ DEFAULT now()`.
- `mois VARCHAR(10) DEFAULT 'AOUT'`, `annee INT`, `famille VARCHAR(50) DEFAULT 'SYNTEC'`.
- UNIQUE `(annee, mois)` → `uq_indices_revision_annee_mois` (ajouté par la migration 0002).
- Référencée par `contrats.indice_reference_id`, `plan_facturation.indice_calcul_id`, `lots_facturation.indice_utilise_id`.

### `lots_facturation`
Toujours présente en base (0 lignes). Colonnes :
- `id UUID` PK, `annee_traitement INT NOT NULL`, `indice_utilise_id UUID` FK → indices_revision.
- `declenche_par VARCHAR(100)`, `declenche_at TIMESTAMPTZ DEFAULT now()`.
- `nb_contrats_traites`, `nb_factures_emises`, `nb_erreurs INT`, `statut VARCHAR(20)`, `termine_at TIMESTAMPTZ`, `rapport_json JSON`.
- **Écart majeur** : la table n'est plus déclarée dans `models.py` et la migration `0002_drop_lots_facturation_fix_indices_uniqueness.py` est marquée comme appliquée (`alembic_version=0002`), mais la table existe toujours. À VÉRIFIER : voir le contenu de la migration pour savoir si le drop a été commenté/sauté.

### `modeles_documents`
- `id UUID` PK ; `type_document VARCHAR(50) NOT NULL`, `nom VARCHAR(200) NOT NULL`, `version VARCHAR(20)`, `chemin_fichier VARCHAR(1000) NOT NULL`, `actif BOOL`, `uploaded_by`, `uploaded_at TIMESTAMPTZ DEFAULT now()`, `description TEXT`.

### `parametres`
- `cle VARCHAR(100)` PK ; `valeur TEXT`, `description TEXT`, `updated_at TIMESTAMPTZ DEFAULT now()`.

### `plan_facturation`
- `id UUID` PK ; `contrat_id UUID NOT NULL` FK CASCADE.
- `numero_facture INT NOT NULL`, `annee_facturation INT NOT NULL`, UNIQUE `(contrat_id, numero_facture)`.
- `date_echeance DATE NOT NULL`, `type_facture VARCHAR(20)`.
- Montants : `montant_ht_prevu`, `montant_annuel_precedent`, `taux_revision NUMERIC(8,6)`, `montant_revise_ht`, `montant_ht_facture NUMERIC(12,2)`.
- FK `indice_calcul_id → indices_revision.id`.
- `facture_karlia_id VARCHAR(100)`, `facture_karlia_ref VARCHAR(100)`, `karlia_synchro_at TIMESTAMPTZ`, `karlia_statut VARCHAR(50)`.
- `statut VARCHAR(30)`, `erreur_message TEXT`, `created_at`, `updated_at`.
- Checks : `ck_type_facture IN ('PRORATE','ANNUELLE')`, `ck_statut_facture IN ('PLANIFIEE','CALCULEE','EMISE','ERREUR')`.

### `prestations`
- `id SERIAL` PK ; `commande_id INT NOT NULL` FK CASCADE.
- `commande_ligne_id INT` FK SET NULL.
- `formateur_id INT` FK.
- `agenda_formateur_id INT` FK → formateurs.id.
- `designation VARCHAR(500) NOT NULL`, `description TEXT`, `duree_jours NUMERIC(5,2) DEFAULT 1`.
- `date_prevue`, `date_planifiee DATE`, `heure_debut TIME`, `heure_fin TIME`, `lieu VARCHAR(500)`.
- `google_event_id VARCHAR(255)`.
- `statut VARCHAR(50) DEFAULT 'a_planifier'`, `notes TEXT`.
- `google_calendar_id VARCHAR(255)`, `google_sync_status VARCHAR(50)`, `google_sync_error TEXT`, `google_synced_at TIMESTAMPTZ`.
- `created_at`, `updated_at TIMESTAMPTZ DEFAULT now()`.
- Index : `idx_prestations_commande`, `idx_prestations_formateur`, `idx_prestations_statut`.

### `transmissions_chorus`
- `id UUID DEFAULT gen_random_uuid()` PK ; `facture_id UUID NOT NULL` FK CASCADE.
- `chorus_id_flux`, `chorus_id_facture VARCHAR(100)`.
- `statut VARCHAR(50) NOT NULL DEFAULT 'EN_ATTENTE'`, `code_retour VARCHAR(50)`, `message_retour TEXT`.
- `payload_json JSONB`, `reponse_json JSONB`.
- `transmis_par VARCHAR(100)`, `transmis_at TIMESTAMPTZ DEFAULT now()`, `is_test BOOL DEFAULT false`.
- Index `idx_transmissions_facture`, `idx_transmissions_statut`.
- Check DB **uniquement** : `ck_statut_transmission IN ('EN_ATTENTE','EN_COURS','SUCCES','ECHEC','ANNULE')`.

### `utilisateurs`
- `id UUID` PK ; `login VARCHAR(100) NOT NULL UNIQUE`, `email VARCHAR(255) NOT NULL UNIQUE`.
- `nom_complet VARCHAR(200)`, `password_hash VARCHAR(500) NOT NULL`, `role VARCHAR(30)`, `actif BOOL`, `derniere_connexion TIMESTAMPTZ`.
- FK `formateur_id INT → formateurs.id`.
- `created_at TIMESTAMPTZ DEFAULT now()`.

## 4. Écarts `models.py` ↔ schéma DB

| Sujet | models.py | DB | Statut |
|---|---|---|---|
| Check `ck_statut_chorus` sur `factures_karlia` | absent | présent | **DB seul** — à recopier dans le modèle si on veut le rejouer en `create_all`. |
| Check `ck_statut_transmission` sur `transmissions_chorus` | absent | présent | idem. |
| Default `id` côté `factures_karlia` / `transmissions_chorus` | `default=uuid.uuid4` (Python) | `gen_random_uuid()` (Postgres) | Cohabitation OK ; le Python prend la main quand on insère par ORM. |
| `commandes.created_at` / `date_import` / `date_validation` | `DateTime` (sans tz indiqué) | `timestamp without time zone` | aligné en intention ; à conserver pour cohérence historique. |
| `commande_lignes.created_at` | `DateTime` | `timestamp without time zone` | idem. |
| Table `lots_facturation` | non modélisée | présente, 0 lignes | À VÉRIFIER — migration 0002 marquée appliquée mais la table existe encore. |
| `Utilisateur.role` default | `"UTILISATEUR"` (Python) | nullable, pas de default DB | Aucun utilisateur n'a ce rôle ; valeur potentiellement piégeuse pour de nouveaux comptes créés sans rôle. |
| `commandes.pdf_devis BYTEA` | déclaré | présent | **non utilisé** dans le code actuel (cf. commit `f71d223`). |
| 4 colonnes Google Calendar sur `prestations` | déclarées | présentes | service Google Calendar retiré du code ; colonnes conservées et partiellement peuplées. |

Aucune table « fantôme » côté code (chaque modèle a sa table). Aucune colonne déclarée dans `models.py` n'est manquante en DB.

# 02 — Backend (FastAPI + SQLAlchemy)

Tout ce qui suit est lu directement dans `backend/app/` au commit de référence.

## 1. Pile technique

Lu dans `backend/requirements.txt` :

| Paquet | Version | Rôle |
|---|---|---|
| fastapi | 0.115.0 | Framework HTTP |
| uvicorn[standard] | 0.30.0 | Serveur ASGI |
| sqlalchemy | 2.0.35 | ORM |
| psycopg2-binary | 2.9.9 | Driver PostgreSQL |
| pydantic | 2.9.2 | Validation |
| pydantic-settings | 2.5.2 | Config |
| httpx | 0.27.2 | Client HTTP (Karlia, Chorus/PISTE) |
| python-jose[cryptography] | 3.3.0 | JWT |
| passlib[bcrypt] | 1.7.4 | Hash mots de passe |
| python-multipart | 0.0.12 | Upload fichiers |
| python-dateutil | 2.9.0 | Dates |
| alembic | 1.13.3 | Migrations |
| apscheduler | 3.10.4 | Synchro Karlia nocturne |
| python-docx | 1.1.2 | Génération Word |
| email-validator | — | Validation EmailStr |

Python 3.12-slim (cf. `backend/Dockerfile`).

## 2. Point d'entrée `app/main.py`

- `Base.metadata.create_all(bind=engine)` au démarrage (création des tables si absentes — cohabite avec Alembic).
- Middleware CORS : `allow_origins = settings.CORS_ORIGINS`, credentials autorisés, méthodes/headers `*`.
- 15 routers branchés via `app.include_router(...)` :

| Préfixe | Module | Tag |
|---|---|---|
| `/api/auth` | `app.api.auth` | Authentification |
| `/api/clients` | `app.api.clients` | Clients |
| `/api/produits` | `app.api.produits` | Produits / Articles |
| `/api/contrats` | `app.api.contrats` | Contrats |
| `/api/facturation` | `app.api.facturation` | Facturation |
| `/api/indices` | `app.api.indices` | Indices Syntec |
| `/api/utilisateurs` | `app.api.utilisateurs` | Utilisateurs |
| `/api/documents` | `app.api.documents` | Documents |
| `/api/parametres` | `app.api.parametres` | Paramètres |
| `/api/audit` | `app.api.audit` | Audit |
| `/api/commandes` | `app.api.commandes` | Commandes |
| `/api/formateurs` | `app.api.formateurs` | Formateurs |
| `/api/prestations` | `app.api.prestations` | Prestations |
| `/api` | `app.api.chorus` (prefix interne `/chorus`) | Chorus Pro |
| `/api/dashboard` | `app.api.dashboard` | Dashboard |

- 3 endpoints racine définis dans `main.py` :
  - `GET /api/health` — public, `{status:"ok",version:"1.0.0"}`.
  - `GET /api/synchro/statut` — `require_authenticated`.
  - `POST /api/synchro/lancer` — `require_role("ADMIN","GESTIONNAIRE")`.
- Job APScheduler `synchro_karlia` : exécuté **au démarrage** + **chaque jour à 02h00** (`CronTrigger(hour=2,minute=0)`). Recharge `karlia.api_key` depuis la table `parametres` à chaque tick.

## 3. Configuration `app/core/config.py`

Toutes les valeurs proviennent de `.env` via Pydantic Settings. Valeurs par défaut (sans `.env`) :

| Clé | Type | Défaut |
|---|---|---|
| `DATABASE_URL` | str | `postgresql://contrats_user:contrats_pass@localhost:5432/contrats_db` |
| `KARLIA_API_URL` | str | `https://karlia.fr/app/api/v2` |
| `KARLIA_API_KEY` | str | `""` (lue ensuite depuis la table `parametres`) |
| `SECRET_KEY` | str | `changez-cette-cle-en-production-32-chars-min` |
| `ALGORITHM` | str | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `480` (8 h) — **non utilisé** : `auth.py` impose 24 h en dur |
| `CORS_ORIGINS` | list[str] | `["http://localhost:3000","http://localhost:5173","https://gestion.sginformatique.fr"]` |
| `UPLOAD_DIR` | str | `./data/modeles` |
| `DOCUMENTS_DIR` | str | `./data/documents` |
| `KARLIA_MAX_REQUESTS_PER_MINUTE` | int | `80` |
| `KARLIA_SYNC_SLEEP_SECONDS` | float | `1.2` |

À vérifier : `ACCESS_TOKEN_EXPIRE_MINUTES` n'est jamais lu dans le code ; `creer_token` (`auth.py:23`) force `timedelta(hours=24)`.

## 4. Connexion DB `app/core/database.py`

- `engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)`.
- `SessionLocal = sessionmaker(autocommit=False, autoflush=False)`.
- `get_db()` : dépendance FastAPI qui ouvre/ferme une session.

## 5. Modèles SQLAlchemy — `app/models/models.py` (496 lignes)

Tous les modèles déclarés, dans l'ordre du fichier. Pour chaque modèle : nom de table, PK, colonnes notables, contraintes, FK et relations.

### `ClientCache` — table `clients_cache`
- PK `id UUID`.
- `karlia_id VARCHAR(100) UNIQUE NOT NULL`.
- `numero_client VARCHAR(20) NOT NULL` — unicité **applicative** (vérifiée dans `main.py:91-93`), pas de contrainte DB.
- `nom NOT NULL` ; adresse (4 colonnes), `email`, `telephone`, `mobile`, `siret`, `tva_intracom`, `forme_juridique`, contact (3 colonnes), `notes`.
- `synchro_at`, `created_at`, `updated_at` (timestamps tz-aware).
- Relation `contrats → Contrat` via `karlia_id`.

### `ArticleCache` — `articles_cache`
- PK `id UUID`, `karlia_id` unique.
- `reference`, `designation NOT NULL`, `prix_unitaire_ht NUMERIC(12,4)`, `unite`, `taux_tva NUMERIC(5,2) default 20.00`, `actif default true`.

### `IndiceRevision` — `indices_revision`
- PK `id UUID`, `date_publication NOT NULL`, `annee INT`, `mois VARCHAR(10) default 'AOUT'`, `famille VARCHAR(50) default 'SYNTEC'`, `valeur NUMERIC(10,4) NOT NULL`, `commentaire`, `source_url`, `created_by`.
- Contrainte `UniqueConstraint('annee','mois')` → index `uq_indices_revision_annee_mois`.

### `Contrat` — `contrats`
- PK `id UUID`. `numero_contrat VARCHAR(100) UNIQUE NOT NULL`.
- `client_karlia_id VARCHAR(100)` — NULL toléré, contrôle applicatif.
- `client_numero`, `client_nom`.
- Dates : `date_debut`, `date_fin` (`NOT NULL`), `nombre_annees INT NOT NULL`.
- Montants : `montant_annuel_ht NUMERIC(12,2) NOT NULL`, `indice_reference_id → indices_revision.id` (nullable).
- Prorata : `prorate_annee1`, `prorate_nb_mois NUMERIC(4,1)`, `prorate_montant_ht NUMERIC(12,2)`, `prorate_validated`, `prorate_note TEXT`, `prorate_demi_mois`.
- `notes_internes TEXT`.
- Famille : `famille_contrat VARCHAR(50) default 'COSOLUCE'`.
- Hiérarchie : `contrat_parent_id → contrats.id`, `type_contrat default 'CONTRAT'`, `numero_avenant INT`.
- Statut : `statut default 'BROUILLON'`, `date_statut_change DATE`, `motif_fin TEXT`, `avenants_fusionnes BOOL`.
- Métadonnées : `created_by`, `created_at`, `updated_at`, `validated_at`.
- Contraintes :
  - `CheckConstraint("date_fin > date_debut")` → `ck_dates_coherentes`.
  - `type_contrat IN ('CONTRAT','AVENANT','RENOUVELLEMENT')` → `ck_type_contrat`.
  - `statut IN ('EN_COURS','A_RENOUVELER','TERMINE','BROUILLON')` → `ck_statut`.
- Relations : `articles`, `plan_facturation`, `documents`, `client`, `indice_reference`, `enfants`, `factures_karlia`.

### `ContratArticle` — `contrat_articles`
- PK `id UUID`. `contrat_id` FK CASCADE. `rang INT NOT NULL` (0 = principal, 1-7 = annexe).
- `article_karlia_id`, `designation NOT NULL`, `reference`, `prix_unitaire_ht NUMERIC(12,4)`, `quantite NUMERIC(10,3) default 1`, `unite`, `taux_tva NUMERIC(5,2) default 20`.
- Contraintes : `rang BETWEEN 0 AND 7` + `UniqueConstraint(contrat_id, rang)`.

### `PlanFacturation` — `plan_facturation`
- PK `id UUID`. `contrat_id` FK CASCADE. `numero_facture INT NOT NULL`, `annee_facturation INT NOT NULL`, `date_echeance NOT NULL`, `type_facture default 'ANNUELLE'`.
- Calcul : `montant_ht_prevu`, `montant_annuel_precedent`, `taux_revision NUMERIC(8,6)`, `montant_revise_ht`, `indice_calcul_id → indices_revision.id`, `montant_ht_facture`.
- Lien Karlia : `facture_karlia_id`, `facture_karlia_ref`, `karlia_synchro_at`, `karlia_statut`.
- Statut : `statut default 'PLANIFIEE'`, `erreur_message`.
- Contraintes : `UniqueConstraint(contrat_id, numero_facture)`, `type_facture IN ('PRORATE','ANNUELLE')`, `statut IN ('PLANIFIEE','CALCULEE','EMISE','ERREUR')`.

### `DocumentGenere` — `documents_generes`
- PK `id UUID`. `contrat_id` FK (sans cascade explicite). `type_document NOT NULL`, `nom_fichier NOT NULL`, `chemin_docx`, `chemin_pdf`, `modele_utilise`, `variables_json JSON`, `generated_by`, `generated_at`.

### `ModeleDocument` — `modeles_documents`
- PK `id UUID`. `type_document NOT NULL`, `nom NOT NULL`, `version`, `chemin_fichier NOT NULL`, `actif default true`, `uploaded_by`, `uploaded_at`, `description`.

### `Utilisateur` — `utilisateurs`
- PK `id UUID`. `login UNIQUE NOT NULL`, `email UNIQUE NOT NULL`, `nom_complet`, `password_hash NOT NULL`, `role default 'UTILISATEUR'`, `actif default true`, `derniere_connexion`, `formateur_id → formateurs.id`, `created_at`.
- **À vérifier** : valeur par défaut DB `'UTILISATEUR'`, alors que la matrice ne connaît que `ADMIN|GESTIONNAIRE|FORMATEUR|TECHNICIEN`. Aucun utilisateur n'a ce rôle en base (cf. § 03).

### `Parametre` — `parametres`
- PK `cle VARCHAR(100)`. `valeur TEXT`, `description TEXT`, `updated_at`.

### `Commande` — `commandes`
- PK `id INTEGER` autoinc. `karlia_document_id INT UNIQUE NOT NULL`.
- `karlia_customer_id`, `karlia_opportunity_id`, `reference_devis`.
- Client snapshot : `client_nom`, `client_email`, `client_telephone`, `client_adresse TEXT`, `client_siret`.
- Montants : `montant_ht`, `montant_tva`, `montant_ttc NUMERIC(15,2)`.
- Dates : `date_devis`, `date_acceptation`, `date_import`, `date_validation`, `created_at`, `updated_at` (timestamps **sans timezone** en DB ; commenté dans le modèle).
- Statut : `statut default 'nouvelle'`, `type_traitement`, `necessite_contrat default false`, `date_planifiee`, `intervenant_id`, `intervenant_nom`, `notes_planification`.
- Liens : `contrat_id → contrats.id ON DELETE SET NULL`, `formateur_id → formateurs.id`.
- PDF : `pdf_devis BYTEA` (colonne **non utilisée** côté code actuel), `pdf_devis_nom`, `pdf_url TEXT`.
- `created_by`, `updated_by` (entiers, jamais peuplés via l'API actuelle).
- `facture_karlia_id`, `facture_karlia_ref`.
- Relations : `lignes`, `contrat`, `formateur`, `prestations`.

### `CommandeLigne` — `commande_lignes`
- PK `id INT`. `commande_id` FK CASCADE.
- `karlia_product_id`, `designation`, `description`, `quantite default 1`, `unite`, `prix_unitaire_ht`, `taux_tva`, `montant_ht`, `montant_tva`, `montant_ttc`.
- Remises Karlia : `discount_type`, `discount_value`, `discount_percent NUMERIC(15,6)`.
- `ordre default 0`, `created_at` (timestamp sans tz).

### `FactureKarlia` — `factures_karlia`
- PK `id UUID` (`default gen_random_uuid()` côté DB). `karlia_document_id INT UNIQUE NOT NULL`.
- `numero_facture NOT NULL`, `reference VARCHAR(200)`.
- Client : `client_karlia_id INT NOT NULL`, `client_nom`, `client_siret VARCHAR(14)`, `client_code_service`.
- Montants : `montant_ht NOT NULL`, `montant_tva`, `montant_ttc`.
- Dates : `date_facture NOT NULL`, `date_echeance`.
- Chorus : `statut_chorus default 'NON_TRANSMISE'`, `date_transmission`, `chorus_numero_flux`, `chorus_statut_technique`, `chorus_date_statut`, `chorus_message_erreur TEXT`.
- Lien `contrat_id → contrats.id ON DELETE SET NULL`.
- `imported_at`, `updated_at`.
- Check DB `ck_statut_chorus` ajouté côté Postgres (cf. § 03) :
  `IN ('NON_TRANSMISE','EN_COURS','TRANSMISE','ACCEPTEE','REJETEE','ERREUR')` — **non déclaré dans models.py**.

### `TransmissionChorus` — `transmissions_chorus`
- PK `id UUID` (`gen_random_uuid()`). `facture_id` FK CASCADE.
- `chorus_id_flux`, `chorus_id_facture`.
- `statut default 'EN_ATTENTE' NOT NULL`, `code_retour`, `message_retour TEXT`.
- `payload_json JSONB`, `reponse_json JSONB`.
- `transmis_par`, `transmis_at`, `is_test BOOL default false`.
- Check DB `ck_statut_transmission IN ('EN_ATTENTE','EN_COURS','SUCCES','ECHEC','ANNULE')` (côté Postgres uniquement).

### `Formateur` — `formateurs`
- PK `id INT` autoinc. `nom NOT NULL`, `prenom`, `email UNIQUE NOT NULL`, `email_google`, `telephone`, `actif default true`, `couleur VARCHAR(7) default '#3788d8'`, `created_at`, `updated_at`.

### `Prestation` — `prestations`
- PK `id INT`. `commande_id` FK CASCADE NOT NULL. `commande_ligne_id` FK SET NULL. `formateur_id` FK.
- `designation NOT NULL`, `description`, `duree_jours NUMERIC(5,2) default 1`, `date_prevue`, `date_planifiee`, `heure_debut TIME`, `heure_fin TIME`, `lieu`, `google_event_id`, `statut default 'a_planifier'`, `notes`.
- `agenda_formateur_id` FK formateurs.id — colonne d'agenda distincte du titulaire (utilisée pour saisie de date).
- 4 colonnes Google Calendar conservées en DB sans service actif : `google_calendar_id`, `google_sync_status`, `google_sync_error`, `google_synced_at`.

## 6. Endpoints HTTP

Pour chaque router : méthode, chemin (préfixé), fonction, dépendance d'auth. Source : `grep -rn "@router\." backend/app/api/`.

### `auth.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| POST | `/api/auth/login` | `login` | public (OAuth2PasswordRequestForm) |
| GET | `/api/auth/me` | `get_me` | `get_current_user` |

JWT HS256, 24 h en dur, payload `{sub, role, id, formateur_id, exp}`. Hash bcrypt.

### `clients.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/clients` | `lister_clients` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/clients/search` | `rechercher_clients_karlia` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/clients/numero-suivant` | `numero_client_suivant` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/clients` | `creer_client` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/clients/{karlia_id}/fiche` | `fiche_client_complete` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/clients/{karlia_id}` | `obtenir_client` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/clients/synchro` | `synchroniser_clients` | `ADMIN, GESTIONNAIRE` |

### `produits.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/produits` | `lister_produits` (`source=cache|karlia`) | `require_authenticated` |
| POST | `/api/produits/synchro` | `synchroniser_articles` | `ADMIN, GESTIONNAIRE` |

### `contrats.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/contrats` | `lister_contrats` (filtres `statut`,`recherche`,`annee`,`familles`,`limit`,`offset`) | `require_authenticated` |
| GET | `/api/contrats/renouvellements` | `contrats_a_renouveler` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/contrats` | `creer_contrat` (calcule prorata + génère plan) | `ADMIN, GESTIONNAIRE` |
| GET | `/api/contrats/{id}` | `obtenir_contrat` | `require_authenticated` |
| POST | `/api/contrats/{id}/valider` | `valider_contrat` (BROUILLON → EN_COURS) | `ADMIN, GESTIONNAIRE` |
| DELETE | `/api/contrats/{id}` | `supprimer_contrat` (BROUILLON seul) | `ADMIN, GESTIONNAIRE` |
| PUT | `/api/contrats/{id}` | `modifier_contrat` (BROUILLON seul, regénère plan) | `ADMIN, GESTIONNAIRE` |
| POST | `/api/contrats/{id}/terminer` | `terminer_contrat` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/contrats/{id}/renouveler` | `renouveler_contrat` (SPONTANE / NOUVEAU_CONTRAT / FIN) | `ADMIN, GESTIONNAIRE` |
| POST | `/api/contrats/renouveler-lot` | `renouveler_lot` (SPONTANE/FIN uniquement) | `ADMIN, GESTIONNAIRE` |

### `facturation.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/facturation/apercu/{annee}` | `apercu_facturation` (filtre `famille`) | `ADMIN, GESTIONNAIRE` |
| POST | `/api/facturation/calculer` | `calculer_factures` (révision + gardes pré-calcul) | `ADMIN, GESTIONNAIRE` |
| POST | `/api/facturation/lancer` | `lancer_facturation` (gardes pré- et post-émission Karlia) | `ADMIN, GESTIONNAIRE` |

### `indices.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/indices/familles` | `lister_familles` | `require_authenticated` |
| GET | `/api/indices` | `lister_indices` | `require_authenticated` |
| GET | `/api/indices/courant` | `indice_courant` (dernier Syntec AOUT) | `require_authenticated` |
| POST | `/api/indices` | `creer_indice` | `ADMIN, GESTIONNAIRE` |
| PUT | `/api/indices/{id}` | `modifier_indice` | `ADMIN, GESTIONNAIRE` |
| DELETE | `/api/indices/{id}` | `supprimer_indice` (délie les FK avant) | `ADMIN, GESTIONNAIRE` |
| GET | `/api/indices/verifier/{famille}/{annee}` | `verifier_indices` | `require_authenticated` |

### `utilisateurs.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/utilisateurs/droits` | `get_droits` (renvoie la matrice DROITS du user courant) | `get_current_user` |
| GET | `/api/utilisateurs` | `lister_utilisateurs` | `ADMIN` |
| POST | `/api/utilisateurs` | `creer_utilisateur` | `ADMIN` |
| PUT | `/api/utilisateurs/{id}` | `modifier_utilisateur` (refus auto-rétrogradation) | `ADMIN` |
| DELETE | `/api/utilisateurs/{id}` | `supprimer_utilisateur` (refus auto-suppression) | `ADMIN` |

### `documents.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/documents/contrat/{id}` | `lister_documents` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/documents/generer/{id}` | `generer_document_contrat` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/documents/telecharger/{doc_id}` | `telecharger` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/documents/modeles` | `lister_modeles` | `require_authenticated` |
| POST | `/api/documents/modeles/upload` | `upload_modele` | `ADMIN` |
| PATCH | `/api/documents/modeles/{id}/activer` | `activer_modele` | `ADMIN` |
| DELETE | `/api/documents/modeles/{id}` | `supprimer_modele` | `ADMIN` |

### `parametres.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/parametres/` | `get_parametres` (masque `karlia_api_key`) | `ADMIN` |
| PUT | `/api/parametres/karlia-api-key` | `update_karlia_api_key` | `ADMIN` |
| POST | `/api/parametres/tester-connexion` | `tester_connexion` (Karlia) | `ADMIN` |
| POST | `/api/parametres/vider-cache` | `vider_cache` | `ADMIN` |
| GET | `/api/parametres/chorus` | `get_chorus_params` (masque secrets) | `ADMIN` |
| PUT | `/api/parametres/chorus` | `update_chorus_params` | `ADMIN` |

### `audit.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/audit/contrat/{id}` | `audit_contrat` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/audit/facturation/{annee}` | `audit_facturation` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/audit/global` | `audit_global` | `ADMIN, GESTIONNAIRE` |

### `commandes.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| POST | `/api/commandes/sync` | `sync_devis` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/stats` | `stats_commandes` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/nouvelles` | `lister_nouvelles` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/a-planifier` | `lister_a_planifier` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/planifiees` | `lister_planifiees` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/terminees` | `lister_terminees` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/contrats-a-creer` | `lister_contrats_a_creer` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/{id}` | `obtenir_commande` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/commandes/{id}/valider` | `valider_commande` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/commandes/{id}/planifier` | `planifier_commande` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/commandes/{id}/terminer` | `terminer_commande` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/commandes/{id}/lier-contrat/{contrat_id}` | `lier_au_contrat` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/commandes/{id}/pdf` | `pdf_commande` (RedirectResponse → URL Karlia) | `ADMIN, GESTIONNAIRE` |
| POST | `/api/commandes/{id}/facturer` | `facturer_commande` | `ADMIN, GESTIONNAIRE` |

### `formateurs.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/formateurs` | `lister_formateurs` | `require_authenticated` |
| POST | `/api/formateurs` | `creer_formateur` | `ADMIN` |
| GET | `/api/formateurs/{id}` | `obtenir_formateur` | `require_authenticated` |
| PUT | `/api/formateurs/{id}` | `modifier_formateur` | `ADMIN` |
| DELETE | `/api/formateurs/{id}` | `supprimer_formateur` | `ADMIN` |

### `prestations.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/prestations` | `lister_prestations` (`filter_prestations_for_user`) | `require_authenticated` |
| GET | `/api/prestations/formateur/{id}` | `lister_par_formateur` | `require_authenticated` |
| POST | `/api/prestations` | `creer_prestation` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/prestations/from-commande/{id}` | `creer_depuis_commande` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/prestations/{id}` | `obtenir_prestation` | `require_authenticated` |
| PUT | `/api/prestations/{id}` | `modifier_prestation` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/prestations/{id}/planifier` | `planifier_prestation` (`check_prestation_ownership`) | `require_authenticated` |
| POST | `/api/prestations/{id}/realiser` | `realiser_prestation` (`check_prestation_ownership`) | `require_authenticated` |
| DELETE | `/api/prestations/{id}` | `supprimer_prestation` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/prestations/reattribuer-commande/{id}` | `reattribuer` | `ADMIN, GESTIONNAIRE` |

### `chorus.py`
Préfixe interne `/chorus` + préfixe externe `/api`.

| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/chorus/test-connexion` | `tester_connexion_chorus` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/chorus/synchro-factures` | `synchroniser_factures_karlia` (type 4, status 2, limit 500) | `ADMIN, GESTIONNAIRE` |
| GET | `/api/chorus/factures` | `lister_factures` (filtres `statut`,`date_debut`,`date_fin`,`search`) | `ADMIN, GESTIONNAIRE` |
| GET | `/api/chorus/factures/{id}` | `obtenir_facture` | `ADMIN, GESTIONNAIRE` |
| PUT | `/api/chorus/factures/{id}/siret` | `mettre_a_jour_siret` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/chorus/transmettre` | `transmettre_factures` (boucle facture par facture) | `ADMIN, GESTIONNAIRE` |
| GET | `/api/chorus/factures/{id}/transmissions` | `historique_transmissions` | `ADMIN, GESTIONNAIRE` |
| POST | `/api/chorus/rechercher-structure` | `rechercher_structure` | `ADMIN, GESTIONNAIRE` |
| GET | `/api/chorus/statistiques` | `statistiques_chorus` | `ADMIN, GESTIONNAIRE` |

À VÉRIFIER : sur la branche `feature/chorus-facturx` (non mergée), un endpoint supplémentaire `POST /api/chorus/factures/{id}/rafraichir-statut` existe (cf. `git log feature/chorus-facturx`), de même qu'une refonte de `/transmettre` vers `deposer/flux` Factur-X. Sur `main`, c'est le code décrit ci-dessus qui s'exécute.

### `dashboard.py`
| Méthode | Chemin | Fonction | Auth |
|---|---|---|---|
| GET | `/api/dashboard/stats` | `dashboard_stats` | `require_authenticated` |

## 7. Services métier (`backend/app/services/`)

### `karlia_service.py` (291 l.) — client httpx Karlia v2
Instance globale `karlia = KarliaService()` créée à l'import.
Méthodes publiques :
- `lister_clients(limit, offset)`
- `obtenir_client(karlia_id)`
- `creer_client(data)`
- `dernier_numero_client()`
- `lister_produits(recherche, limit)`
- `lister_types_documents()`
- `creer_facture(...)`
- `obtenir_document(doc_id)`
- `tester_connexion()`
- `traitement_lot_factures(lots)`

Helpers privés `_get`, `_post`, `_handle_response`, `_client` (httpx.AsyncClient).

### `karlia_devis_service.py` (507 l.) — sync devis acceptés
Classe `KarliaDevisService` :
- `sync_devis_acceptes(db, force_full)` : boucle principale, applique le sleep `KARLIA_SYNC_SLEEP_SECONDS`, retry sur 429 avec backoff `[5, 15, 30]`.
- `get_devis_acceptes(depuis_date)` (filtre type=1, status=2).
- `get_devis_detail`, `get_customer_detail`.
- `_is_opportunity_traitee` / `_marquer_opportunity_traitee` via custom field `66505`.
- `_create_commande`, `_update_commande`, `_parse_karlia_date`, `_parse_tva`.
- Persistance `derniere_synchro_devis` dans `parametres`.
- Historique documenté en tête de fichier : sync 2026-05-20 a saturé Karlia, d'où le rate-limit actuel ; rattrapage `scripts/rattrapage_pdf_url.py`.

### `chorus_service.py` (373 l.) — client OAuth2 PISTE + soumission Chorus Pro
Constantes :
- Sandbox OAuth : `https://sandbox-oauth.piste.gouv.fr/api/oauth/token`
- Prod OAuth : `https://oauth.piste.gouv.fr/api/oauth/token`
- Sandbox API : `https://sandbox-api.piste.gouv.fr/cpro/factures/v1`
- Prod API : `https://api.piste.gouv.fr/cpro/factures/v1`

Classe `ChorusProService` :
- `_get_access_token()` : OAuth2 client_credentials avec `Basic` (tech_username:tech_password) **et** `auth=(client_id, client_secret)`. Cache token (durée − 5 min).
- `_get`, `_post` httpx.
- `tester_connexion()` (récupère un token).
- `rechercher_structure_destinataire(siret)` → POST `/rechercher/structures`.
- `consulter_structure(id)`, `rechercher_services_structure(id)`.
- `soumettre_facture(...)` → POST `/soumettre` avec payload `modeDepot=SAISIE_API`, cadre `A1_FACTURE_FOURNISSEUR`, `modePaiement=VIREMENT`, TVA 20 % par défaut.
- `consulter_statut_facture(id)` → POST `/consulter/facture`.
- `rechercher_factures_emises(date_debut, date_fin, statut)` → POST `/rechercher/factures/fournisseur`.

Factory `get_chorus_service_from_params(params)` : exige `chorus_client_id`, `chorus_client_secret`, `chorus_tech_username`, `chorus_tech_password`, `chorus_siret_emetteur`. Mode qualif/prod selon `chorus_mode_qualification`.

État opérationnel : cf. mémoire utilisateur — module bloqué par 403 PISTE non résolu (cf. fichier `chorus_pro_blocage.md` en MEMORY). Branche `feature/chorus-facturx` en cours de mise au point pour le dépôt Factur-X via `deposer/flux`.

### `contrat_service.py` (141 l.)
- `calculer_prorata(date_debut, montant_annuel_ht, demi_mois=False)` : règle métier "≤15 du mois → ce mois, >15 → mois suivant" ; option ½ mois ajoute `montant/24`.
- `calculer_nombre_annees(date_debut, date_fin)`.
- `generer_plan_facturation(contrat_id, date_debut, date_fin, montant_annuel_ht, prorata)` : retourne la liste des lignes prévues (prorata + N annuelles, échéance 1er janvier).
- `generer_numero_client(nom, dernier_numero)`.

### `document_service.py` (251 l.) — publipostage docx
- Chemins en dur : `STORAGE_DIR = /app/storage`, `MODELES_DIR`, `DOCUMENTS_DIR`.
- `FAMILLE_MODELE` mappe `COSOLUCE`, `CANTINE`, `MAINTENANCE`, `ASSISTANCE_TEL` vers leur fichier modèle.
- `FAMILLE_LABEL` étend à `DIGITECH`, `KIWI_BACKUP` (sans modèle Word actuel).
- `CHAMPS` : dictionnaire de variables → alias (`NomClient` ↔ `NomSite`, etc.).
- `generer_document(contrat, client, db, generated_by)` : sélectionne le modèle, remplace les variables dans paragraphes + tableaux, persiste dans `documents_generes`.
- `lister_documents_contrat(contrat_id, db)`.

### `revision_service.py` (162 l.)
- `FAMILLES_CONTRAT` : liste de référence (7 familles, chacune avec son `revision`).
- `REVISION_PAR_FAMILLE` : `COSOLUCE/MAINTENANCE/ASSISTANCE_TEL → SYNTEC_AOUT`, `CANTINE → SYNTEC_OCTOBRE`, `DIGITECH → MANUELLE`, `KIWI_BACKUP/AUTRE → AUCUNE`.
- `get_regle_revision(famille)`, `get_indice(db, annee, mois)`, `verifier_indices_disponibles(db, famille, annee_facturation)`.
- `calculer_revision(db, famille, annee, montant_precedent, nouveau_montant_manuel=None)` : applique la formule Syntec (indice N-1 / indice N-2) ou prend le manuel pour Digitech.

### `validation_service.py` (270 l.)
- `valider_contrat(db, contrat)` : santé d'un contrat (article principal, plan complet, indices dispos, dates cohérentes).
- `valider_pre_calcul(db, plan, nouveau_montant=None)`.
- `valider_pre_emission(db, plan)` : garde anti double-émission, ID produit Karlia, etc.
- `valider_post_emission(plan, resultat_karlia)` : vérifie cohérence retour Karlia.
- `auditer_annee_facturation(db, annee)` : vue globale d'une année.
- Niveaux : `ERREUR` (bloque), `WARNING` (alerte loguée), `INFO` (ok).

## 8. Authentification & RBAC

### Mécanisme JWT
- `auth.py` : `creer_token({sub, role, id, formateur_id})`, `exp = utcnow + 24h`, algo `HS256`, clé `settings.SECRET_KEY`.
- `OAuth2PasswordBearer(tokenUrl="/api/auth/login")`.
- `get_current_user` : décode, charge `Utilisateur` par `login`, rejette si `actif=false`.

### Helpers (`app/core/security.py`)
- `ROLES = ("ADMIN", "GESTIONNAIRE", "FORMATEUR", "TECHNICIEN")`.
- `require_authenticated` : exige token valide, aucun rôle.
- `require_role(*roles)` : factory, 403 si role hors liste, validation à l'import (`ValueError` si rôle inconnu).
- `check_prestation_ownership(prestation, user)` : ADMIN/GESTIONNAIRE accès total, FORMATEUR/TECHNICIEN doivent matcher `formateur_id` ou `agenda_formateur_id`. 403 si pas de `formateur_id` sur le compte.
- `filter_prestations_for_user(query, user)` : applique le filtre côté SQL pour FORMATEUR/TECHNICIEN.

### Matrice DROITS — source `app/api/utilisateurs.py:DROITS`
| Droit | ADMIN | GESTIONNAIRE | FORMATEUR | TECHNICIEN |
|---|---|---|---|---|
| `contrats_ecriture` | ✅ | ✅ | ❌ | ❌ |
| `contrats_lecture` | ✅ | ✅ | ❌ | ✅ |
| `facturation` | ✅ | ✅ | ❌ | ❌ |
| `indices` | ✅ | ✅ | ❌ | ❌ |
| `commandes` | ✅ | ✅ | ❌ | ❌ |
| `parametres` | ✅ | ❌ | ❌ | ❌ |
| `utilisateurs` | ✅ | ❌ | ❌ | ❌ |
| `formateurs` | ✅ | ✅ | ❌ | ❌ |
| `toutes_prestations` | ✅ | ✅ | ❌ | ❌ |

Cette matrice est dupliquée côté frontend (`contrats-ui-src/src/context/AuthContext.js:getDroitsByRole`). Toute modification doit être synchronisée des deux côtés (le commentaire de `security.py` indique cette obligation).

## 9. Migrations Alembic

- `backend/alembic.ini` + `backend/alembic/env.py`.
- 2 révisions appliquées (DB en `0002`) :
  - `0001_baseline_existing_db.py` (33 l.) — baseline tagué sur l'état existant.
  - `0002_drop_lots_facturation_fix_indices_uniqueness.py` (98 l.) — ajoute `UNIQUE(annee, mois)` sur `indices_revision` + tentative de drop de `lots_facturation`.
- À VÉRIFIER : la table `lots_facturation` existe **toujours** en base (cf. `\dt` § 03), donc la migration `0002` n'a pas effacé la table ou Alembic a marqué la révision sans exécuter l'étape — à inspecter avant tout nettoyage.

## 10. Scripts utilitaires

- `backend/app/scripts/seed_test_data.py`, `seed_mairies.py`, `seed_charge.py` — jeux de données.
- `backend/app/scripts/migrate_clients_fictifs.py` — utilitaire one-shot historique.
- `backend/scripts/gen_modeles.py`, `export_clients_karlia.py` — scripts en racine `backend/scripts/`.
- `scripts/rattrapage_pdf_url.py`, `cleanup_bc_commandes.py` à la racine du repo.
- `scripts/dryrun_facturx_8906.py` (présent en untracked sur `feature/chorus-facturx`, absent de `main`).

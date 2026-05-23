# 01 — Arborescence du dépôt

Généré par :
```
find . -type f \
  -not -path '*/node_modules/*' -not -path '*/.git/*' \
  -not -path '*/__pycache__/*' -not -path '*/build/*' \
  -not -path './contrats-ui/build/*' -not -path './contrats-ui-src/node_modules/*' \
  -not -path './contrats-ui-src/package-lock.json' \
  -not -path './storage/*' -not -path './backups/*' | sort
```

## 1. Arborescence complète (hors deps & artefacts)

```
.
├── .claude/settings.local.json
├── .env                                       (env Docker — masqué, cf. §07)
├── .gitignore
├── BRANCHES.md                                438 l.
├── CHANTIER_2_1_RECAP.md                      178 l.
├── CODING_RULES.md                            228 l.
├── docker-compose.yml                          40 l.
├── Dockerfile.frontend                          3 l.
├── GUIDE_DEMARRAGE.md                         217 l.
├── nginx.conf                                  22 l.
├── PROJECT_CONTEXT.md                          88 l.
├── README.md                                  201 l.
├── TODO_REFONTE.md                            124 l.
├── backend/
│   ├── .env                                   (env legacy — non monté par compose)
│   ├── .env.example                           17 l.
│   ├── Dockerfile                             20 l.
│   ├── requirements.txt                       15 l.
│   ├── alembic.ini                            72 l.
│   ├── alembic/
│   │   ├── env.py                             78 l.
│   │   ├── README.md                          170 l.
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 0001_baseline_existing_db.py   33 l.
│   │       └── 0002_drop_lots_facturation_fix_indices_uniqueness.py  98 l.
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                            205 l.
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── audit.py                        84 l.
│   │   │   ├── auth.py                         70 l.
│   │   │   ├── chorus.py                      544 l.
│   │   │   ├── clients.py                     467 l.
│   │   │   ├── commandes.py                   495 l.
│   │   │   ├── contrats.py                    675 l.
│   │   │   ├── dashboard.py                   145 l.
│   │   │   ├── documents.py                   144 l.
│   │   │   ├── facturation.py                 289 l.
│   │   │   ├── formateurs.py                  229 l.
│   │   │   ├── indices.py                     158 l.
│   │   │   ├── parametres.py                  157 l.
│   │   │   ├── prestations.py                 414 l.
│   │   │   ├── produits.py                     80 l.
│   │   │   └── utilisateurs.py                162 l.
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py                       42 l.
│   │   │   ├── database.py                     26 l.
│   │   │   └── security.py                    116 l.
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── models.py                      496 l.
│   │   ├── scripts/
│   │   │   ├── __init__.py
│   │   │   ├── migrate_clients_fictifs.py     119 l.
│   │   │   ├── seed_charge.py                 219 l.
│   │   │   ├── seed_mairies.py                419 l.
│   │   │   └── seed_test_data.py              352 l.
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── chorus_service.py              373 l.
│   │       ├── contrat_service.py             141 l.
│   │       ├── document_service.py            251 l.
│   │       ├── karlia_devis_service.py        507 l.
│   │       ├── karlia_service.py              291 l.
│   │       ├── revision_service.py            162 l.
│   │       └── validation_service.py          270 l.
│   └── scripts/
│       ├── export_clients_karlia.py           164 l.
│       └── gen_modeles.py                     268 l.
├── contrats-ui-src/                           (sources frontend versionnées)
│   ├── .gitignore
│   ├── package.json                            48 l.
│   ├── package-lock.json
│   ├── README.md                               70 l.
│   ├── tailwind.config.js
│   ├── public/
│   │   ├── favicon.ico   index.html   logo192.png   logo512.png   manifest.json   robots.txt
│   └── src/
│       ├── App.css                             38 l.
│       ├── App.js                              91 l.
│       ├── App.test.js
│       ├── index.css
│       ├── index.js
│       ├── logo.svg
│       ├── reportWebVitals.js
│       ├── setupTests.js
│       ├── components/
│       │   └── Layout.js                      128 l.
│       ├── context/
│       │   └── AuthContext.js                  87 l.
│       ├── pages/
│       │   ├── ChorusProPage.js               496 l.
│       │   ├── Clients.js                     321 l.
│       │   ├── CommandesAPlanifier.js         432 l.
│       │   ├── CommandesPlanifiees.js         309 l.
│       │   ├── CommandesTerminees.js          235 l.
│       │   ├── ContratsACreer.js              322 l.
│       │   ├── Contrats.js                    230 l.
│       │   ├── Dashboard.js                   231 l.
│       │   ├── DetailContrat.js               254 l.
│       │   ├── Facturation.js                 305 l.
│       │   ├── Formateurs.js                  280 l.
│       │   ├── Indices.js                     183 l.
│       │   ├── Login.js                        34 l.
│       │   ├── MesPrestations.js              432 l.
│       │   ├── ModifierContrat.js             219 l.
│       │   ├── NouveauContrat.js              207 l.
│       │   ├── NouvellesCommandes.js          504 l.
│       │   ├── Parametres.js                  377 l.
│       │   ├── Renouvellements.js             289 l.
│       │   ├── TunnelContrat.js               608 l.
│       │   └── Utilisateurs.js                264 l.
│       └── services/
│           ├── api.js                          46 l.
│           └── pdfFetch.js                     57 l.
├── contrats-ui/                               (dossier build externe, hors versioning des sources)
│   └── build/                                 (artefact CRA — non listé ici)
├── docs/
│   ├── DIAGNOSTIC_PDF_COMMANDES.md            261 l.
│   └── etat/                                  (le présent dossier)
├── scripts/
│   ├── cleanup_bc_commandes.py                100 l.
│   ├── dryrun_facturx_8906.py                 208 l.  (UNTRACKED sur main)
│   └── rattrapage_pdf_url.py                  203 l.
├── storage/                                   (volume Docker — modèles & docs générés)
│   ├── documents_generes/
│   └── modeles/
├── backups/                                   (sauvegardes locales)
└── tests/
    └── rbac_check.sh
```

Total fichiers source listés (hors deps / build / storage / backups / .git) : **112**.

## 2. Lignes par fichier source significatif

Top par taille (extraits) :

```
 18508 total
   675 ./backend/app/api/contrats.py
   608 ./contrats-ui-src/src/pages/TunnelContrat.js
   544 ./backend/app/api/chorus.py
   507 ./backend/app/services/karlia_devis_service.py
   504 ./contrats-ui-src/src/pages/NouvellesCommandes.js
   496 ./contrats-ui-src/src/pages/ChorusProPage.js
   496 ./backend/app/models/models.py
   495 ./backend/app/api/commandes.py
   467 ./backend/app/api/clients.py
   432 ./contrats-ui-src/src/pages/MesPrestations.js
   432 ./contrats-ui-src/src/pages/CommandesAPlanifier.js
   419 ./backend/app/scripts/seed_mairies.py
   414 ./backend/app/api/prestations.py
   377 ./contrats-ui-src/src/pages/Parametres.js
   373 ./backend/app/services/chorus_service.py
   352 ./backend/app/scripts/seed_test_data.py
   322 ./contrats-ui-src/src/pages/ContratsACreer.js
   321 ./contrats-ui-src/src/pages/Clients.js
   309 ./contrats-ui-src/src/pages/CommandesPlanifiees.js
   305 ./contrats-ui-src/src/pages/Facturation.js
   291 ./backend/app/services/karlia_service.py
   289 ./contrats-ui-src/src/pages/Renouvellements.js
   289 ./backend/app/api/facturation.py
   280 ./contrats-ui-src/src/pages/Formateurs.js
   270 ./backend/app/services/validation_service.py
   268 ./backend/scripts/gen_modeles.py
   264 ./contrats-ui-src/src/pages/Utilisateurs.js
   261 ./docs/DIAGNOSTIC_PDF_COMMANDES.md
   254 ./contrats-ui-src/src/pages/DetailContrat.js
   251 ./backend/app/services/document_service.py
   235 ./contrats-ui-src/src/pages/CommandesTerminees.js
   231 ./contrats-ui-src/src/pages/Dashboard.js
   230 ./contrats-ui-src/src/pages/Contrats.js
   229 ./backend/app/api/formateurs.py
   228 ./CODING_RULES.md
   219 ./contrats-ui-src/src/pages/ModifierContrat.js
   219 ./backend/app/scripts/seed_charge.py
   217 ./GUIDE_DEMARRAGE.md
   208 ./scripts/dryrun_facturx_8906.py
   207 ./contrats-ui-src/src/pages/NouveauContrat.js
   205 ./backend/app/main.py
   203 ./scripts/rattrapage_pdf_url.py
   201 ./README.md
   183 ./contrats-ui-src/src/pages/Indices.js
   178 ./CHANTIER_2_1_RECAP.md
   170 ./backend/alembic/README.md
   164 ./backend/scripts/export_clients_karlia.py
   162 ./backend/app/services/revision_service.py
   162 ./backend/app/api/utilisateurs.py
   158 ./backend/app/api/indices.py
   157 ./backend/app/api/parametres.py
   145 ./backend/app/api/dashboard.py
   144 ./backend/app/api/documents.py
   141 ./backend/app/services/contrat_service.py
   128 ./contrats-ui-src/src/components/Layout.js
   124 ./TODO_REFONTE.md
   119 ./backend/app/scripts/migrate_clients_fictifs.py
   116 ./backend/app/core/security.py
   100 ./scripts/cleanup_bc_commandes.py
    98 ./backend/alembic/versions/0002_drop_lots_facturation_fix_indices_uniqueness.py
    91 ./contrats-ui-src/src/App.js
    88 ./PROJECT_CONTEXT.md
    87 ./contrats-ui-src/src/context/AuthContext.js
    84 ./backend/app/api/audit.py
    80 ./backend/app/api/produits.py
    78 ./backend/alembic/env.py
    72 ./backend/alembic.ini
    70 ./contrats-ui-src/README.md
    70 ./backend/app/api/auth.py
    57 ./contrats-ui-src/src/services/pdfFetch.js
    48 ./contrats-ui-src/package.json
    46 ./contrats-ui-src/src/services/api.js
    42 ./backend/app/core/config.py
    40 ./docker-compose.yml
    38 ./contrats-ui-src/src/App.css
    34 ./contrats-ui-src/src/pages/Login.js
    33 ./backend/alembic/versions/0001_baseline_existing_db.py
    26 ./backend/app/core/database.py
```

(commandes : `find ... | xargs wc -l | sort -rn`)

## 3. Notes sur l'organisation

- Sources backend dans `backend/app/` ; scripts utilitaires dispersés entre `backend/scripts/`, `backend/app/scripts/` et `scripts/` (racine du repo).
- Sources frontend versionnées dans `contrats-ui-src/`. Le dossier `contrats-ui/` (hors `src/`) n'est **pas** dans git : il sert au build CRA puis fournit `build/` à Docker (cf. §04, §07). Le dossier `~/contrats-ui` (hors repo) contient un miroir partiellement divergent.
- `storage/` est monté en volume par docker-compose et contient les modèles Word + documents générés (non versionné).
- 3 documents racine sont marqués comme historiques et seront remplacés par ce dossier : `BRANCHES.md`, `CHANTIER_2_1_RECAP.md`, `TODO_REFONTE.md`, plus l'éventuel `AUDIT_REFONTE.md` mentionné dans `models.py` (introuvable en lecture directe — supprimé ou jamais committé sur cette branche).

# Chorus Pro / PISTE — Raccordement API OAuth2

Document de suivi du diagnostic d'intégration. Branche `fix/chorus-payload-v5-01`.
Dernière mise à jour : 2026-05-18.

## TL;DR

Le code est conforme à la spec V5.01 et le logging structuré capture tout ce
qu'il faut pour diagnostiquer. **Le blocage n'est plus du ressort applicatif** :
toutes les requêtes authentifiées vers Chorus Pro sont rejetées en 403, alors
qu'OAuth2 PISTE fonctionne correctement. Hypothèse principale : il manque un
raccordement API OAuth2 actif côté portail Chorus Pro
(`https://chorus-pro.gouv.fr`) qui lie notre Client ID PISTE et notre compte
technique à notre SIRET `53189130700021`.

## État au 2026-05-18

### Ce qui fonctionne

- OAuth2 PISTE : `client_id` + `client_secret` → Bearer token obtenu sans erreur
- Le module Chorus Pro **Factures** existe et est routé côté PISTE : la
  requête `POST /cpro/factures/v1/rechercher/factures/fournisseur` renvoie 403
  avec le corps de la requête en écho, ce qui indique que l'URL est valide mais
  qu'une règle d'autorisation applicative la rejette.
- Le payload `soumettre` est conforme à la spec V5.01 (cf. plus bas).
- Le logging dans `transmissions_chorus` capture maintenant l'intégralité de
  l'échange : `status_code`, `headers` (incluant `x-correlationid`),
  `body_text`, `body_json`, et le `last_request` réellement envoyé.

### Ce qui ne fonctionne pas

- Toutes les URLs `POST /cpro/.../recuperer/...` testées renvoient 403 avec
  `body_text = "{}"` : ce pattern indique une **URL non routée** (la spec V5.01
  documente "403 = certificat non reconnu OU ressource non trouvée").
- En conséquence, `chorus_id_fournisseur` et `chorus_id_utilisateur_courant`
  ne peuvent pas être auto-configurés actuellement.

### Différence de comportement entre 403 "URL inconnue" et 403 "non autorisé"

Observation utile à retenir pour les diagnostics futurs :

| Réponse PISTE | Interprétation |
| --- | --- |
| `403` + `body_text = "{}"` | URL non routée côté gateway (endpoint inexistant ou inactif) |
| `403` + body = écho de la requête envoyée | URL valide, mais autorisation refusée au niveau applicatif |

## x-correlationid collectés

À transmettre au support PISTE si réouverture de ticket. Tous datés du
2026-05-18, IP source `81.250.134.116`, Client ID
`a7320f23-4c4b-4955-93be-078a068c4f7c`, SIRET émetteur `53189130700021`,
compte technique `TECH_053189130700021@cpp2017.fr`.

| Endpoint testé | x-correlationid |
| --- | --- |
| `POST /cpro/transverses/v1/recuperer/utilisateurCourant` (cpro-account base64) | `Id-8c6d0b6ae93135bc54114f08 0` |
| `POST /cpro/transverses/v1/recuperer/utilisateurCourant` (cpro-account en clair) | `Id-106f0b6aa5bd3d3ea0271b20 0` |
| `POST /cpro/factures/v1/rechercher/factures/fournisseur` | `Id-5c6e0b6acc72464a79b9715d 0` |
| `POST /cpro/factures/v1/recuperer/structures/fournisseur` | `Id-e36f0b6a5599a5a48602e4dc 0` |
| `POST /cpro/factures/v1/recuperer/structuresActivesPourFournisseur` | `Id-e36f0b6a5799e08ea5f3543b 0` |
| `POST /cpro/transverses/v1/recuperer/structuresActivesPourFournisseur` | `Id-e46f0b6aecdd30da30c112ef 0` |

## Actions à faire côté portail Chorus Pro

À effectuer quand l'accès au compte gestionnaire Chorus Pro pour le SIRET
`53189130700021` sera disponible (`https://chorus-pro.gouv.fr`) :

1. **Vérifier le raccordement API OAuth2** dans `Mon Compte` → `Raccordements
   techniques` (intitulé exact à confirmer selon la version du portail) :
   - Existe-t-il un raccordement de type "API OAuth2 / PISTE" rattaché à notre
     SIRET ?
   - L'ancien applicatif SG Informatique utilise un certificat RGS (raccordement
     pré-2020) : il n'est pas concerné, et il ne faut **pas** y toucher.
2. **Si aucun raccordement OAuth2 n'existe** : en créer un, en y associant le
   Client ID PISTE `a7320f23-4c4b-4955-93be-078a068c4f7c` et le compte
   technique `TECH_053189130700021@cpp2017.fr`.
3. **Vérifier les droits du compte technique** :
   - Le compte technique est-il rattaché à la structure SIRET
     `53189130700021` ?
   - Quels rôles lui sont attribués (au minimum gestionnaire fournisseur pour
     dépôt de factures) ?
   - Est-il actif (non expiré, mot de passe non échu) ?
4. **Vérifier les souscriptions PISTE côté portail PISTE
   (`https://piste.gouv.fr`)** : l'application doit avoir souscrit à au
   moins les modules "Chorus Pro - Factures" et "Chorus Pro - Transverses"
   en environnement Production, avec les scopes nécessaires (au-delà de
   `openid` seul).

## Travail restant côté code, à faire après débloquage du raccordement

Tout ce qui suit est non bloquant : le code actuel sera fonctionnel dès que
les autorisations Chorus Pro seront correctes.

1. **Remplacer `recuperer_utilisateur_courant()`** dans
   `backend/app/services/chorus_service.py` : l'endpoint
   `/transverses/v1/recuperer/utilisateurCourant` n'apparaît pas dans la spec
   V5.01. Le remplacer par la méthode officielle
   **`recupererStructuresActivesPourFournisseur`** (spec V5.01 section
   2.1.1.74). Tableau d'entrée vide, sortie =
   `listeStructures[].idStructureCPP` (`integer`) + `.identifiant` (SIRET,
   `varchar 80`) + `.designationStructure`. L'URL exacte du segment HTTP est à
   confirmer via le Swagger PISTE (`https://developer.aife.economie.gouv.fr/`)
   — nos 3 candidates ont toutes échoué en 403/URL inconnue.
2. **Adapter `auto_config_chorus`** dans `backend/app/api/chorus.py` pour qu'il
   utilise la nouvelle méthode, et filtrer la `listeStructures` par SIRET
   émetteur pour extraire le bon `idStructureCPP` (= `chorus_id_fournisseur`).
3. **`chorus_id_utilisateur_courant`** : à creuser séparément si nécessaire
   (probablement obtenu via un autre endpoint de récupération des utilisateurs
   rattachés à la structure ; à voir si la spec V5.01 expose ça côté API).
4. **Première soumission réelle** : une fois `chorus_id_fournisseur` peuplé,
   lancer un test via le bouton "Test soumission" sur la page Chorus Pro du
   frontend. Vérifier que `transmissions_chorus.is_test = TRUE` et que le
   `reponse_json` contient bien un `status_code = 200` ou un message d'erreur
   métier exploitable.

## Conformité du payload `soumettre` (déjà acquise)

Pour mémoire, le builder de payload dans
`backend/app/services/chorus_service.py` produit désormais une structure
conforme V5.01 (validée par dry-run le 2026-05-18) :

- `fournisseur.idFournisseur` (integer, dans l'objet `fournisseur`)
- Pas de `typeIdentifiantFournisseur` ni `identifiantFournisseur` à la racine
- `ligneTva[].ligneTvaTauxManuel` / `ligneTvaMontantBaseHtParTaux` /
  `ligneTvaMontantTvaParTaux` (et non plus `ligneRecapTva*`)
- `montantTotal.montantTVA` (et non plus `montantTvaTotal`)
- Pas de `montantAcompte`
- `lignePoste[].lignePosteTauxTvaManuel` uniquement, jamais
  `lignePosteTauxTva: null` en parallèle
- `destinataire.codeServiceExecutant` omis par défaut, fourni uniquement si la
  facture le précise (`factures_karlia.client_code_service`)

## Endpoints applicatifs disponibles

- `POST /api/chorus/auto-config` : récupère `idFournisseur` (KO actuellement,
  cf. plus haut)
- `POST /api/chorus/test-soumission` : soumission de test sans consommer de
  numéro Karlia (`is_test = TRUE` en base)
- `POST /api/chorus/transmettre` : soumission réelle
- `GET /api/chorus/test-connexion` : ping OAuth2 PISTE

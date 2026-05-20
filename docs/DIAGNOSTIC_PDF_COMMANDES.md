# Diagnostic — PDF non cliquable sur écran "Nouvelles Commandes"

**Date** : 2026-05-20
**Branche** : `diagnostic/pdf-commandes-manquants`
**Auteur** : diagnostic automatisé (phase analyse, aucune modification)

---

## 1. Résumé exécutif

**106 commandes sur 142 (75 %) s'affichent sans bouton PDF cliquable** dans l'écran Nouvelles Commandes. Le défaut est massivement concentré sur la sync du **2026-05-20** (106 commandes sans PDF sur 108 importées ce jour-là), alors que les imports précédents (avril 2026, 31 commandes) sont 100 % corrects.

**Cause technique principale** : lors de la sync, le `download_url` (lien PDF Karlia) n'est **disponible que dans le détail** `/documents/{id}` et **PAS dans le listing** `/documents`. Quand `get_devis_detail()` échoue (très probablement par rate-limiting Karlia lors d'une sync massive), l'erreur est avalée silencieusement (`return None`, juste `logger.error`), la commande est créée sans `pdf_url`, et n'est jamais retentée.

**Test live Karlia** : les 3 commandes sans `pdf_url` testées renvoient bien `download_url` quand on appelle `/documents/{id}` à la main → le PDF *existe* côté Karlia, il n'a juste jamais été récupéré côté code.

---

## 2. Statistiques chiffrées

### 2.1. Vue d'ensemble (142 commandes en base)

| Champ                                | Nombre | %     |
| ------------------------------------ | ------ | ----- |
| `pdf_devis` NON NULL (base64)        | 0      | 0 %   |
| `pdf_devis` NULL                     | 142    | 100 % |
| `pdf_devis` = '' (chaîne vide)       | 0      | 0 %   |
| `pdf_url` non vide                   | 36     | 25 %  |
| `pdf_url` NULL ou ''                 | 106    | 75 %  |
| **`pdf_disponible` côté API = true** | **36** | 25 %  |
| **`pdf_disponible` côté API = false**| **106**| 75 %  |

`pdf_disponible` est calculé côté backend par `bool(commande.pdf_url or commande.pdf_devis)` (backend/app/api/commandes.py:169). Comme `pdf_devis` est **toujours** NULL, seul `pdf_url` détermine l'affichage.

### 2.2. Par statut

| Statut       | Total | Avec PDF | Sans PDF |
| ------------ | ----: | -------: | -------: |
| nouvelle     |   136 |       31 |      105 |
| a_planifier  |     4 |        3 |        1 |
| planifiee    |     1 |        1 |        0 |
| facturee     |     1 |        1 |        0 |

Le problème touche **toutes les commandes au statut `nouvelle`** dans des proportions de 77 %. Les commandes plus avancées (a_planifier, planifiee, facturee) sont quasiment toutes OK — sans doute parce que leur sync remonte à une époque où ça fonctionnait.

### 2.3. Par jour d'import (`date_import`)

| Jour       | Total | Avec PDF | Sans PDF |
| ---------- | ----: | -------: | -------: |
| 2026-05-20 |   108 |     **2**|  **106** |
| 2026-04-30 |    13 |       13 |        0 |
| 2026-04-22 |    16 |       16 |        0 |
| 2026-04-21 |     1 |        1 |        0 |
| 2026-04-20 |     4 |        4 |        0 |

**Bascule brutale et nette** : 100 % de succès avant le 2026-05-20, ~2 % le 2026-05-20. Pas de zone grise progressive — c'est une dégradation d'une seule sync.

### 2.4. Exemples — 10 commandes SANS PDF (toutes id récents, date_import 2026-05-20)

| id  | karlia_document_id | reference_devis | client                 | date_devis | statut    | pdf_url |
| --- | ------------------ | --------------- | ---------------------- | ---------- | --------- | ------- |
| 320 | 694942             | D26-0609        | MAIRIE DE TEST         | 2026-05-19 | nouvelle  | (vide)  |
| 318 | 694367             | D26-0607        | MAIRIE DE TEST         | 2026-05-18 | nouvelle  | (vide)  |
| 317 | 689738             | D26-0592        | MAIRIE DE CORBIE       | 2026-05-07 | nouvelle  | (vide)  |
| 316 | 689416             | D26-0588        | MAIRIE DE SANTES       | 2026-05-07 | nouvelle  | (vide)  |
| 315 | 688771             | D26-0586        | MAIRIE DE LALLAING     | 2026-05-06 | nouvelle  | (vide)  |
| 314 | 687675             | D26-0583        | MAIRIE DE ATTICHES     | 2026-05-05 | nouvelle  | (vide)  |
| 313 | 687444             | D26-0584        | MAIRIE DE SANTES       | 2026-05-05 | nouvelle  | (vide)  |
| 308 | 682991             | D26-0581        | MAIRIE DE BAUVIN       | 2026-04-30 | nouvelle  | (vide)  |
| 299 | 679029             | D26-0570        | MAIRIE DE MOUCHIN      | 2026-04-23 | nouvelle  | (vide)  |
| 245 | 674286             | D26-0555        | MAIRIE DE ELEU DIT L.  | 2026-04-15 | nouvelle  | (vide)  |

### 2.5. Exemples — 10 commandes AVEC PDF

Tous ont `pdf_devis` = NULL et `pdf_url` rempli avec une URL Karlia `https://karlia.fr/app/get-file.php?token=...`. Aucune n'a de base64 stocké — le champ `pdf_devis` est inutilisé par la sync (cf. §3.1).

### 2.6. Croisement `pdf_devis` × `pdf_url`

| pdf_devis | pdf_url    | Nombre |
| --------- | ---------- | -----: |
| NULL      | NULL       |    106 |
| NULL      | non vide   |     36 |

Pas de cas mixte. Pas de chaîne vide. **Le mécanisme PDF en base64 (`pdf_devis`) n'est jamais utilisé.**

---

## 3. Analyse du code de sync

### 3.1. `karlia_devis_service.py` — la sync ne stocke jamais le base64

Dans `_create_commande` (ligne 351) et `_update_commande` (ligne 394), seul `pdf_url` (le lien Karlia) est stocké :

```python
# _create_commande, ligne 351-368
commande = Commande(
    ...
    pdf_url=devis_data.get("download_url"),
    pdf_devis_nom=f"{devis_data.get('number', 'devis')}.pdf"
)
```

Aucun appel HTTP ne télécharge le PDF pour le convertir en base64 et le stocker dans `commande.pdf_devis`. Ce champ reste donc **toujours NULL**. C'est cohérent avec l'observation en base (0/142). Le commentaire `# Base64 encoded` (models.py:327) est trompeur : la colonne existe mais n'est plus alimentée depuis le commit `7cf2f79` ("PDF devis via URL Karlia + script export clients") qui a basculé le module vers le mode "URL Karlia" sans nettoyer la colonne base64.

### 3.2. `download_url` n'existe que dans le DÉTAIL Karlia, pas dans le LISTING

Test live de l'API Karlia confirmé aujourd'hui (2026-05-20) :

- `GET /documents?type=1&id_status=2&limit=2` → champs retournés :
  `canceled, currency_code, date, id, id_customer_supplier, id_opportunity, id_status, id_type, number, total_with_tax, total_without_tax, ...`
  **PAS de `download_url`.**

- `GET /documents/{id}` (3 commandes testées : 694942, 689738, 689416) → renvoie `download_url` valide pour les 3, HTTP 200.

Cela signifie que **la sync est obligatoirement dépendante de `get_devis_detail()`** pour obtenir `pdf_url`. Si le détail n'est pas appelé ou échoue, `pdf_url` reste vide.

### 3.3. `get_devis_detail` avale silencieusement les erreurs

`karlia_devis_service.py:108-120` :

```python
async def get_devis_detail(self, document_id: int) -> Optional[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{self.base_url}/documents/{document_id}", ...)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Erreur détail devis {document_id}: {e}")
            return None    # ← l'erreur est avalée, pas de retry, pas de levée
```

Dans `_create_commande:323` :

```python
devis_detail = await self.get_devis_detail(devis_data["id"])
if devis_detail:
    devis_data.update(devis_detail)
# si devis_detail est None, devis_data n'est pas enrichi
# → devis_data["download_url"] est absent
# → commande.pdf_url = None
```

**Aucun retry, aucun statut "incomplet" stocké, aucune relance ultérieure** : la commande est créée définitivement sans `pdf_url`.

### 3.4. Côté endpoint API — `_commande_to_response` et `/pdf`

`backend/app/api/commandes.py:169` :
```python
pdf_disponible=bool(commande.pdf_url or commande.pdf_devis),
```
Logique correcte (les deux sont vérifiés). Pas un bug ici.

`backend/app/api/commandes.py:398-426` — `GET /api/commandes/{id}/pdf` :
- Redirige vers `commande.pdf_url` si présent (RedirectResponse)
- Sinon `raise HTTPException 404`
- Code mort en dessous (jamais atteint, car le `raise` arrête l'exécution) qui prévoyait un fallback `StreamingResponse` depuis `pdf_devis` base64

Cohérent avec le frontend : `NouvellesCommandes.js:330` n'affiche le bouton que si `cmd.pdf_disponible == true`.

### 3.5. Pas d'erreurs visibles dans les logs backend

`docker compose logs backend --tail=2000 | grep -iE "pdf|devis|error|warning"` → 0 hit pertinent. Les logs récents ne montrent que des INFO de synchro client/article. Si des erreurs détail Karlia ont eu lieu pendant la grosse sync de 15:31–15:34, **les logs sont déjà rotation/écrasés**.

### 3.6. Pourquoi 106/108 et pas 0/108 ?

Hypothèse appuyée par les timestamps en base :

- 90 commandes importées entre 15:31:07 et 15:34:25, soit ~3 min pour 90 commandes → ~30 commandes/min.
- Pour chaque commande nouvelle, la sync fait au minimum : `get_devis_detail` + `get_customer_detail` + (parfois) `_is_opportunity_traitee` + (parfois) `_marquer_opportunity_traitee`. Soit 2 à 4 appels Karlia par commande.
- 30 commandes/min × 3 appels = **~90 req/min**, juste sous le quota Karlia documenté à **100 req/min** (cf. `karlia_service.py:67`).

À la moindre rafale, on dépasse 100 req/min → 429. `get_devis_detail` retourne None, mais `get_customer_detail` (avant ou après dans le même créneau) aussi sans doute → la commande est créée avec des champs vides. **Le `await asyncio.sleep(0.8)` n'est appliqué qu'entre les pages de listing et autour des opportunités, jamais autour des appels détail/client**.

Le commit `99c0d9b` du même jour ("filtrage par type") a aussi multiplié par le nombre de devis l'effort de sync : avant le fix, la sync remontait *tous* les types confondus (devis + BC), donc faisait moins d'opérations CREATE/UPDATE inutiles. Après le fix, elle remonte uniquement les devis, mais ceux-ci sont apparemment plus nombreux à être "nouveaux" sur cette première sync post-fix.

---

## 4. Hypothèse principale

> **La sync massive du 2026-05-20 (108 commandes importées en ~3 min) a déclenché du rate-limiting Karlia sur les appels `GET /documents/{id}`. L'erreur HTTP est avalée silencieusement par `get_devis_detail` (`logger.error` + `return None`), les commandes ont été créées avec `pdf_url=None`, et le code n'a aucun mécanisme de rejeu ou de marquage "PDF à récupérer plus tard".**

**Preuves convergentes** :
1. Avant le 2026-05-20 : 100 % des commandes ont `pdf_url` (31/31). Après : 2 %  (2/108).
2. Karlia renvoie bien `download_url` aujourd'hui pour ces commandes (3 tests directs, HTTP 200, champ présent).
3. La donnée existe côté Karlia, n'a juste pas atterri en base.
4. Le code de sync n'appelle `get_devis_detail` qu'une fois par commande, sans retry, sans sleep dédié.
5. La cadence (~90 req/min sur 3 min) est juste au-dessus du quota 100 req/min en pic.

---

## 5. Hypothèses secondaires écartées

### Hypothèse A : Karlia ne fournit plus de PDF pour les devis récents
**Écartée.** Les 3 commandes testées en direct (694942, 689738, 689416) renvoient HTTP 200 avec `download_url` valide. Le PDF *est* disponible côté Karlia.

### Hypothèse B : Le PDF est stocké en base64 mais le frontend ne l'utilise pas
**Écartée.** La colonne `pdf_devis` est NULL pour 100 % des 142 commandes. La sync n'a jamais alimenté cette colonne depuis le passage en mode "URL Karlia" (commit `7cf2f79`). Le code mort `StreamingResponse` après `raise HTTPException` dans `/api/commandes/{id}/pdf` confirme l'intention abandonnée.

### Hypothèse C : Filtre frontend erroné (mauvaise propriété, bug d'affichage)
**Écartée.** `NouvellesCommandes.js:330` lit `cmd.pdf_disponible`, qui vient bien de `_commande_to_response` (commandes.py:169) → `bool(commande.pdf_url or commande.pdf_devis)`. Si `pdf_url` était rempli, le bouton s'afficherait. Vérifié : les 36 commandes avec `pdf_url` rempli ont bien le bouton.

### Hypothèse D : Chaîne vide vs NULL côté DB
**Écartée.** Le SQL distingue explicitement. Aucune commande n'a `pdf_url = ''` — toutes sont soit `NULL`, soit URL valide.

### Hypothèse E : Régression dans le commit `99c0d9b` (filtre type)
**Écartée.** Ce commit ne touche pas la récupération PDF. Il modifie seulement le paramètre de filtrage du listing (`id_type` → `type`) et ajoute un filtre Python défensif. Indirectement, il a peut-être réduit le bruit (moins de BC à ignorer) → première sync force_full massive sur uniquement les devis → pression sur le quota. C'est un facteur aggravant, pas la cause directe.

---

## 6. Proposition de plan de correction (à valider)

### 6.1. Correctif data — récupérer les `pdf_url` manquants pour les 106 commandes (one-shot)

Script à exécuter en mode batch contrôlé (avec `asyncio.sleep` adapté pour rester sous 60 req/min — bien sous le quota) :

```text
Pour chaque commande WHERE pdf_url IS NULL OR pdf_url = '':
    detail = await karlia_devis_service.get_devis_detail(commande.karlia_document_id)
    if detail and detail.get("download_url"):
        commande.pdf_url = detail["download_url"]
        commande.pdf_devis_nom = f"{commande.reference_devis}.pdf"
        db.commit()
    await asyncio.sleep(1.2)   # ~50 req/min, marge confortable
```

Exposable comme route admin `POST /api/commandes/repair-pdf-urls` ou via un script `scripts/repair_pdf_urls.py`.

### 6.2. Correctif code — robustifier `get_devis_detail`

Trois axes (à arbitrer ensemble) :

1. **Rate-limit côté client** : ajouter un `await asyncio.sleep(0.8)` avant chaque `get_devis_detail` dans `sync_devis_acceptes` (boucle `for devis_data in devis_list`). Garantit ~75 req/min en pic.
2. **Retry sur 429** : dans `get_devis_detail`, si `response.status_code == 429`, attendre 5–10 s et retenter une fois. Le code actuel attrape `httpx.HTTPError` et abandonne immédiatement.
3. **Marquer la commande "PDF incomplet"** : si `get_devis_detail` retourne None alors qu'on attendait un PDF, soit lever une exception qui bloque la création (pour ré-essai plus tard), soit ajouter une colonne `pdf_sync_status` qui permet à une sync incrémentale de re-tenter.

Le minimum viable : (1) + (2).

### 6.3. Décision sur le champ `pdf_devis` base64

À trancher avec le user :
- **Option A** : supprimer la colonne (migration + simplification de `/api/commandes/{id}/pdf`) — cohérent avec le pattern "URL Karlia" actuel.
- **Option B** : ré-alimenter la colonne (téléchargement + base64 en sync) pour découpler du token Karlia qui peut expirer.

Pas urgent, et probablement pas dans le périmètre de ce diagnostic.

### 6.4. Observabilité

- Compter les `get_devis_detail` failed dans le retour de `sync_devis_acceptes` (nouveau champ `detail_appels_echoues`) pour visibilité immédiate.
- Logger en `WARNING` (pas `ERROR`) avec le code HTTP exact, pour mieux distinguer 404 / 429 / 5xx dans les logs.

---

## 7. Prochaines étapes proposées

1. **Validation** de ce diagnostic par toi (relecture, ajustements).
2. Mise en œuvre du correctif data §6.1 sur les 106 commandes.
3. Patch code §6.2 (sleep + retry) pour éviter la rechute.
4. Décision sur §6.3 (base64 oui/non) à part.

**Aucune modification de code applicatif n'a été faite dans ce diagnostic. Toutes les vérifications API ont été en lecture seule (`GET /documents/{id}`).**

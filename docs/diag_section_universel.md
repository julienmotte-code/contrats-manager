# Diagnostic — Universalité du champ Karlia `section`

**Date :** 2026-05-26
**Branche :** `feat/categories-routage`
**Échantillon :** 10 commandes (47 lignes), 9 clients distincts, mix BC25/BC26.
**Périmètre :** lecture seule. Aucune modification.

## Objectif

Confirmer que `products_list[i].section` est un marqueur fiable et **universel**
pour distinguer les lignes d'intitulé (`'1'`) des vraies lignes (`'0'`) côté
Karlia, avant de l'utiliser comme filtre dans la sync ou le routage côté SGI.

Le diagnostic précédent (`diag_lignes_intitule_karlia.md`) avait validé le
critère sur une seule commande (BC26-0048). Cet élargissement teste 9
commandes supplémentaires.

## Échantillon

| BC | Karlia id | Client | Lignes | `section='1'` |
|---|---:|---|---:|---:|
| BC26-0023 | 677325 | MAIRIE DE GUEMPS | 6 | 4 |
| BC25-0050 | 677637 | MAIRIE DE CAMPAGNE LÈS GUINES | 10 | 4 |
| BC26-0037 | 677593 | MAIRIE DE BLEQUIN | 6 | 4 |
| BC26-0012 | 676859 | MAIRIE DE COURCELLES LES LENS | 1 | 0 |
| BC26-0069 | 681715 | MAIRIE DE MOUCHIN | 5 | 1 |
| BC26-0019 | 677285 | MAIRIE DE ANIZY LE GRAND | 4 | 3 |
| BC26-0062 | 678054 | MAIRIE DE FENAIN | 1 | 0 |
| BC25-0002 | 449263 | MAIRIE DE TEST | 2 | 1 |
| BC25-0042 | 677608 | CCAS DE LALLAING | 6 | 4 |
| BC26-0022 | 677316 | MAIRIE DE CHARLY SUR MARNE | 6 | 4 |
| **Total** | — | — | **47** | **25** |

## Résultats

### Présence et valeurs du champ `section`

- **Présence : 47 / 47** (100 %). Champ jamais absent, jamais NULL.
- **Valeurs distinctes : `'0'` (22) et `'1'` (25). Aucune autre valeur.**

### Répartition

- 8 commandes sur 10 contiennent au moins un intitulé.
- Les 2 commandes sans intitulé (BC26-0012, BC26-0062) sont des BC mono-ligne
  (1 seule entrée dans `products_list`) — comportement attendu : pas besoin
  de section/sous-total quand il n'y a qu'une ligne à traiter.

### Échantillon visuel des lignes `section='1'` hors BC26-0048

Tous cohérents avec la sémantique "intitulé / section / sous-total" :

| BC | Titre |
|---|---|
| BC26-0023 | « Gamme COLORIS : Progiciels Cosoluce : CHORUS » |
| BC26-0023 | « TOTAL ABONNEMENT » |
| BC26-0023 | « Prestations de mise en service à distance » ⚠️ |
| BC26-0023 | « TOTAL PRESTATIONS » |
| BC25-0050 | « Gamme COLORIS : Progiciels Cosoluce : OPTIMA+ » |
| BC26-0037 | « Gamme COLORIS : COLORIA » |

⚠️ **Note sur la ligne 3 de BC26-0023** : titre "Prestations de mise en service
à distance" avec `section='1'`. Deux lectures possibles :

1. Karlia utilise `section='1'` aussi comme **en-tête de groupe** introduisant
   un bloc de vraies lignes filles (pas seulement comme sous-total final).
2. Saisie humaine non-standard côté Karlia.

Quoi qu'il en soit, c'est **l'intention déclarée par l'opérateur Karlia** :
côté SGI on respecte ce flag, on ne reclasse pas. Si la ligne aurait dû être
une vraie prestation, c'est à corriger à la source dans Karlia.

### Faux négatifs œil

**Heuristique testée** : titre composé en majuscules (≥ 60 %) + `id_product=0`
+ `total=0` + `price=0` MAIS `section != '1'`.

→ **0 cas** trouvé sur les 47 lignes. Le critère `section='1'` capte
**tous** les candidats "intitulé évident" sur cet échantillon.

## Verdict

**`section ∈ {'0', '1'}` est universel et fiable sur l'échantillon élargi.**

Aucune valeur déviante, aucun NULL, aucun champ absent. Aucun faux négatif
quand on cherche les intitulés "à l'œil". Le critère peut être utilisé
sereinement en filtre dans la sync ou dans la logique de routage côté SGI.

Une réserve épistémologique : l'échantillon reste **10 commandes sur 82** en
base. Les types de produits/services Karlia inspectés sont variés (Cosoluce,
prestations, formations, sous-traités, locations, etc.) — couverture
qualitative correcte mais pas exhaustive. Pour un correctif définitif côté
sync, il faudrait surveiller les premières exécutions et logger si une
valeur de `section` autre que `'0'/'1'` apparaît.

## Limites & recommandations

- L'échantillon n'inclut pas les avoirs / factures Karlia (type ≠ 2). À tester
  séparément si on doit étendre le filtre à d'autres types de documents.
- Si on persiste `section` localement (option B du diag précédent), prévoir
  une assertion de safety : à la sync, si `section ∉ {'0', '1'}`, logger un
  warning et stocker la valeur brute (chaîne) plutôt que d'inférer.

## Reproductibilité

Script de diag : `scripts/diag_section_universel.py`. Lance avec :

```bash
docker compose cp scripts/diag_section_universel.py backend:/tmp/diag_section_universel.py
docker compose exec -T -e PYTHONPATH=/app backend python3 /tmp/diag_section_universel.py
```

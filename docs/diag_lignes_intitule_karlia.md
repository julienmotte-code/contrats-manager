# Diagnostic — Marqueur des lignes d'intitulé Karlia

**Date :** 2026-05-26
**Branche :** `feat/categories-routage`
**Périmètre :** lecture seule (DB + GET Karlia). Aucune modification.

## Contexte

Certaines lignes de bon de commande Karlia sont des **intitulés / sections /
sous-totaux** à 0,00 € qui ne doivent être ni planifiées, ni facturées, ni
routées vers un contrat. Exemple : BC26-0048 contient 4 telles lignes parmi
17 entrées :

- « Gamme COLORIS : Progiciels Cosoluce : PREMIUM + TANGARA » (ordre 0)
- « ABONNEMENT ANNUEL (LOGICIEL + ASSISTANCE + HEBERGEMENT) » (ordre 8)
- « PRESTATIONS ET FORMATIONS » (ordre 9)
- « TOTAL PRESTATIONS (INSTALLATION + REPRISE DES DONNEES + FORMATION) » (ordre 16)

## Résultat

**Marqueur fiable : champ `section` (string, valeurs `'0'` ou `'1'`)**
exposé par Karlia dans chaque entrée de `/documents/{id}.products_list`.

| `section` | Sémantique | Nombre BC26-0048 |
|:---:|---|---:|
| `'1'` | Ligne d'intitulé / section / sous-total | **4** |
| `'0'` | Ligne réelle (produit ou prestation à traiter) | **13** |

100 % concordance avec ce qu'un humain identifie visuellement comme un intitulé.

## Caractéristiques corrélées (sur les 4 intitulés observés)

Toutes les lignes `section='1'` partagent aussi :

| Champ | Valeur sur intitulés |
|---|---|
| `id_product` | `'0'` |
| `id_unit` | `'0'` |
| `unit` | `''` (vide) |
| `id_vat` | `'-1'` (vraies lignes : ∈ {1, 2, 3, 4}) |
| `chart_of_account` | `{'code': '?', 'title': '?'}` |
| `price_without_tax` | `'0.000000'` |
| `total_without_tax` | `'0.000'` |

Ce sont des **signaux corrélés**, pas des marqueurs indépendants. Aucun n'est
plus fiable que `section` seul, et certains seraient piégeux pris isolément
(cf. faux positifs ci-dessous). `section` est le bon critère.

## Faux positifs des heuristiques alternatives

### Filtre `montant_ht = 0`

**Inutilisable en pratique.** Exemple BC26-0048 ligne 14 :
- Désignation : « Reprise des données TANGARA -- En Option »
- `id_product = '520161'` (vrai produit catalogué SGI Formation)
- `section = '0'` (vraie ligne)
- `price_without_tax = '0.000000'`, `total_without_tax = '0.000'`

C'est une **option non prise**, mais c'est une vraie ligne. Un filtre
`montant=0` la classerait à tort comme intitulé.

### Filtre `id_product = '0'`

**Sémantiquement piégeux.** Karlia accepte les lignes libres (description
saisie sans produit catalogué) qui ont aussi `id_product='0'`. Aujourd'hui
elles sont rares mais peuvent légitimement exister. Filtrer dessus
risquerait d'écarter des lignes valides à terme.

### Filtre `id_vat = '-1'`

Corrélé à `section='1'` sur l'échantillon, mais redondant. Pas indépendamment
spécifié comme marqueur de type côté Karlia, donc fragile à long terme.

## État actuel côté base SGI

Les 4 intitulés sont **stockés tels quels** dans `commande_lignes` (la sync
ne les filtre pas) :

```
SELECT id, karlia_product_id, designation, montant_ht
FROM commande_lignes
WHERE commande_id = 364 AND karlia_product_id = '0';
-- 4 lignes (id 839, 847, 848, 855)
```

La colonne `section` n'est **pas persistée localement** (aucune colonne dédiée
sur `commande_lignes`).

## Conséquences sur l'étape de routage déjà livrée

Avec le routage par défaut implémenté (commit `20265f1`) :
- ces 4 lignes ont `id_product_category = NULL` → `destination_defaut = 'facturation_directe'`
- la destination `facturation_directe` ne déclenche aucune émission automatique
- **effet pratique actuel : neutre** (pas de prestation fantôme, pas de contrat
  forcé, pas de facture émise par ces lignes)

Mais elles polluent :
- les listings de lignes côté futur écran de validation (4 lignes "non
  actionnables" mélangées aux vraies) ;
- un opérateur peut par mégarde router une de ces lignes vers `a_planifier`
  (qui créerait une prestation à 0 €) ou `contrat` (qui forcerait
  `necessite_contrat=True` sans raison).

## Options de correctif (à discuter, NON implémentées dans ce diagnostic)

### Option A — Filtrer à la sync (suppression)

Dans `karlia_devis_service._create_commande` / `_update_commande` : `if section == '1': continue`. Les 4 lignes ne sont jamais stockées.

- ✅ Table propre, aucune logique UI à ajouter
- ❌ Perte de fidélité au document source (audit, reconstruction)
- ❌ Migration : il faut purger les intitulés déjà en base (5+ commandes
  similaires à BC26-0048 probablement)

### Option B — Persister un flag (préférée)

Ajouter `commande_lignes.section_karlia INTEGER` (ou `est_intitule BOOLEAN`)
+ alimenter à la sync depuis `products_list[i].section`. Côté UI/API :
exclure ces lignes des écrans actifs (routage, validation, planification),
mais les conserver en lecture seule pour audit et affichage fidèle au BC.

- ✅ Fidélité audit
- ✅ Affichage possible en gris dans l'UI ("séparateur visuel")
- ❌ +1 colonne, filtres à ajouter aux endpoints actifs

## Limites du diagnostic

Échantillon : **un seul BC (BC26-0048)**. À confirmer en élargissant si
souhaité : `section` est-il `'0'` ou `'1'` partout sur les autres commandes ?
Hypothèse forte que oui (champ natif Karlia, présent sur toutes les entrées
de `products_list`), à vérifier en lecture sur 3-5 BC supplémentaires si tu
veux la sérénité avant de coder le correctif.

## Reproductibilité

Script de diag : `scripts/diag_lignes_intitule.py` (à copier depuis
`/tmp/diag_bc26_0048.py` si tu veux le rejouer ; un seul GET, pas de
rate-limit nécessaire).

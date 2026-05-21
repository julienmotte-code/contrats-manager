# Branches et conventions Git — Module Gestion Contrats

Document de référence pour la gestion des branches du dépôt
[contrats-manager](https://github.com/julienmotte-code/contrats-manager).

> Mis à jour le **21 mai 2026** à la suite du cleanup post-audit
> (chantier 1.1, branche `audit/refonte-v2`).

---

## 1. Branches actives

À cet instant, le dépôt contient **9 branches actives** sur `origin`. Toute
nouvelle branche `feature/*` ou `fix/*` doit avoir une justification écrite
ici dès sa création et être taguée puis supprimée dès qu'elle est mergée.

| Branche | Rôle | Statut |
|---|---|---|
| `main` | Tronc de production | actif |
| `audit/refonte-v2` | Audit complet (2026-05-21) — base pour la refonte | actif (traçabilité) |
| `audit/module-v2.3.0` | Audit précédent (2026-05-18) | conservé pour traçabilité |
| `diag/karlia-facture-statut` | Logs debug `karlia_service.creer_facture` (lié Q1 audit : `id_status`) | actif tant que Q1 non tranchée |
| `feat/stabilisations-v2.3.1` | Ajoute colonnes `discount_*` au modèle `CommandeLigne`, logique remises Karlia, méthode `marquer_facture_envoyee`, `id_status=0` | à intégrer (chantier 1.3 alignement schéma) |
| `feature/google-agenda-planning` | Service Google Calendar pour planifier les prestations | en attente d'arbitrage (Q6 audit) |
| `fix/chorus-payload-v5-01-clean` | Refonte Chorus Pro selon spec V5.01 + logging structuré + dry-run | en attente d'arbitrage (Q5 audit blocage 403 PISTE) |
| `fix/karlia-api-key-centralisation` | Centralisation des accès à la clé API Karlia (anti-pattern : 5 emplacements actuels) | à intégrer (Vague 2.4) |
| `fix/karlia-facture-brouillon-v2` | `id_status=0` au lieu de `1` sur tous les chemins de facturation | en attente d'arbitrage (Q1 audit) |

Toute autre branche **doit être supprimée** dès qu'elle est mergée
(cf. convention legacy ci-dessous).

---

## 2. Tags `legacy/*` — branches archivées

Une branche `feature/*` ou `fix/*` mergée sur `main` n'a plus de raison
de rester ouverte. Avant suppression, on crée un tag `legacy/<nom>` sur
son dernier commit pour préserver la traçabilité (auteur, message, diff
stat) sans polluer la liste des branches actives.

**Convention nommage** : `legacy/<nom-branche-aplati>` — les `/` du nom
de branche sont remplacés par `-` (par cohérence avec les contraintes
de nommage des tags Git).

**Tags actuellement créés** (12, état au 2026-05-21) :

| Tag | Origine | Commentaire |
|---|---|---|
| `legacy/feat-dashboard-stats-endpoint` | `feat/dashboard-stats-endpoint` | mergée via tag `v2.4.2` |
| `legacy/feature-chorus-pro` | `feature/chorus-pro` | mergée via tag `v2.1.0` |
| `legacy/feature-dashboard-refonte` | `feature/dashboard-refonte` | précurseur de `v2.4.2` + correctif familles `AT/CITYWEB` |
| `legacy/feature-ecran-clients` | `feature/ecran-clients` | mergée (vérifié par `git cherry main`) |
| `legacy/feature-generation-contrats-word` | `feature/generation-contrats-word` | mergée |
| `legacy/feature-gestion-commandes` | `feature/gestion-commandes` | mergée via tag `v1.5.0` |
| `legacy/feature-gestion-formateurs` | `feature/gestion-formateurs` | mergée + pattern soft-delete utile à conserver |
| `legacy/feature-renouvellements-multi-selection` | `feature/renouvellements-multi-selection` | mergée (tag git existant `v2-renouvellements-multi-selection`) |
| `legacy/feature-seed-test-data` | `feature/seed-test-data` | mergée (tag git existant `v-seed-test-data`) |
| `legacy/feature-sync-devis-opportunites-traitees` | `feature/sync-devis-opportunites-traitees` | mergée via tag `v2.2.0` |
| `legacy/fix-chorus-payload-v5-01-original` | `fix/chorus-payload-v5-01` | doublon épais de `fix/chorus-payload-v5-01-clean` (archive complète avec tous les commits parasites) |
| `legacy/fix-karlia-factures-brouillon` | `fix/karlia-factures-brouillon` | mergée via tag `v2.4.1` (traçabilité du débat `id_status`) |

**Une branche `feature/contrats-onglets-statut`** a été supprimée
sans tag : aucun commit divergent vs main, aucun diff vs main
(vérifié par `git cherry main` vide et `git diff main...` vide).

### Restaurer une branche archivée

Pour réouvrir une branche legacy en local :

```bash
git fetch --tags
git checkout -b feature/<nom-original> legacy/<nom-aplati>
```

Pour la repousser sur origin et la remettre au travail : `git push -u origin feature/<nom-original>`.

---

## 3. Conventions Git

### 3.1 Création d'une branche

- Préfixer par catégorie : `feature/`, `fix/`, `chore/`, `docs/`,
  `refactor/`, `diag/`, `audit/`.
- Le nom doit décrire le **résultat** (ex `fix/karlia-api-key-centralisation`),
  pas le **moyen** (`fix/refactor-config-py` ❌).
- Une branche par sujet ; pas de branche multi-objectifs.

### 3.2 Avant de supprimer une branche feature ou fix

**Toujours créer un tag `legacy/<nom>` avant suppression**, sauf si
la branche est strictement équivalente à `main` (aucun commit
divergent, aucun diff). Vérifier d'abord :

```bash
git fetch --all --prune
git cherry main origin/<branche>          # vide = tout est dans main
git log main..origin/<branche> --oneline  # vide = aucun commit divergent
git diff main...origin/<branche> --stat   # vide = aucun fichier différent
```

Si toutes les commandes ci-dessus retournent vide, la branche peut
être supprimée sans tag (catégorie C de l'audit).

### 3.3 Procédure standard d'archivage

```bash
# 1. Créer le tag legacy
git tag legacy/<nom-aplati> origin/<branche>

# 2. Pousser le tag
git push origin legacy/<nom-aplati>

# 3. Supprimer la branche sur origin
git push origin --delete <branche>

# 4. Supprimer la branche en local
git branch -D <branche>
```

### 3.4 Branches `legacy/*` (interdiction de travail)

Les branches préfixées `legacy/` n'existent pas (uniquement des **tags**).
Si un tag `legacy/<nom>` apparaît, il signifie qu'il préserve l'état
d'une ancienne branche. **Ne jamais travailler directement dessus** :
toujours créer une nouvelle branche `feature/...` à partir du tag si
nécessaire (cf. section 2 "Restaurer une branche archivée").

### 3.5 Branches `audit/*`

Les branches `audit/*` sont **conservées indéfiniment** comme références
horodatées de l'état du dépôt à un instant donné. Elles ne sont jamais
mergées sur main. Leur contenu fait foi pour reconstituer l'état du
projet à la date de l'audit correspondant.

### 3.6 Synchronisation local ↔ origin

Avant tout cleanup ou refactoring :

```bash
git fetch --all --prune
git status                                       # working tree clean ?
# Vérifier qu'aucune branche locale n'a de commits non poussés :
for b in $(git branch | sed 's/[* ]//g'); do
  if git rev-parse --verify --quiet "origin/$b" >/dev/null 2>&1; then
    ahead=$(git rev-list --count "origin/$b..$b" 2>/dev/null)
    [ "$ahead" != "0" ] && echo "⚠ $b : $ahead commit(s) en local non poussé(s)"
  fi
done
```

---

## 4. Tags non-`legacy/`

Les autres tags du dépôt suivent un schéma de versioning :

- `v<MAJOR>.<MINOR>.<PATCH>` (ex `v2.4.6`) — releases stables
- `v<MAJOR>.<MINOR>.<PATCH>.<HOTFIX>` (ex `v2.4.6.1`) — hotfix sur une release
- `v<MAJOR>.<MINOR>.<PATCH>-pre-<nom>` — snapshots pré-mergé
- `v-<nom>` ou `v<MAJOR>-<nom>` — tags exceptionnels nominaux

> Note : des sauts volontaires existent dans la séquence (ex `v2.4.2 → v2.4.5`).
> Ne pas signaler ces sauts comme des anomalies — ils sont intentionnels.

---

## 5. Historique des cleanups

| Date | Avant | Après | Tags legacy créés | Référence |
|---|---|---|---|---|
| 2026-05-21 | 22 branches origin | 9 branches origin | 12 | Chantier 1.1 / branche `audit/refonte-v2` |

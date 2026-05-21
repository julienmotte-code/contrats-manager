#!/usr/bin/env bash
#
# tests/rbac_check.sh — Vérification du gating RBAC côté backend.
#
# Authentifie 4 comptes test_* (un par rôle) et appelle un endpoint donné avec
# chaque token. Affiche le code HTTP retourné pour chacun.
#
# Usage :
#   ./tests/rbac_check.sh GET  /api/contrats
#   ./tests/rbac_check.sh POST /api/contrats               # body vide ({})
#   ./tests/rbac_check.sh POST /api/contrats '{"foo":"bar"}'
#   ./tests/rbac_check.sh POST /api/contrats @body.json    # @ = fichier
#
# Comptes nécessaires (créés une fois pour toute la Vague 2) :
#   test_admin / test_gestionnaire / test_formateur / test_technicien
#   password identique pour les 4 : Test123!
#
# Variables d'environnement optionnelles :
#   RBAC_BASE    URL de base (défaut : http://localhost)
#   RBAC_PASS    password commun  (défaut : Test123!)

set -uo pipefail

BASE="${RBAC_BASE:-http://localhost}"
PASS="${RBAC_PASS:-Test123!}"

if [[ $# -lt 2 ]]; then
    cat <<EOF
Usage: $0 <METHOD> <PATH> [BODY]

Exemples :
  $0 GET  /api/contrats
  $0 POST /api/contrats '{"numero_contrat":"X"}'
  $0 POST /api/contrats @/tmp/body.json
EOF
    exit 2
fi

METHOD="$1"
ENDPOINT="$2"
BODY="${3:-}"

# ── Récupération des tokens ─────────────────────────────────────────────────
declare -A TOKENS
for ROLE in admin gestionnaire formateur technicien; do
    LOGIN="test_${ROLE}"
    TOKEN=$(curl -sS -X POST "${BASE}/api/auth/login" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=${LOGIN}&password=${PASS}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null)
    if [[ -z "$TOKEN" ]]; then
        echo "ERREUR : impossible d'obtenir un token pour ${LOGIN}" >&2
        echo "  → vérifier que le compte existe et que le password vaut '${PASS}'" >&2
        exit 1
    fi
    TOKENS["$ROLE"]="$TOKEN"
done

# ── Appel de l'endpoint pour chaque rôle ────────────────────────────────────
echo "→ ${METHOD} ${BASE}${ENDPOINT}"

ROLE_LABELS=("ADMIN" "GESTIONNAIRE" "TECHNICIEN" "FORMATEUR")
ROLE_KEYS=("admin" "gestionnaire" "technicien" "formateur")

RESULTS=()
for i in "${!ROLE_KEYS[@]}"; do
    KEY="${ROLE_KEYS[$i]}"
    LABEL="${ROLE_LABELS[$i]}"
    TOK="${TOKENS[$KEY]}"

    CURL_ARGS=(-sS -o /dev/null -w "%{http_code}" -X "$METHOD" "${BASE}${ENDPOINT}"
        -H "Authorization: Bearer ${TOK}")

    if [[ -n "$BODY" ]]; then
        CURL_ARGS+=(-H "Content-Type: application/json")
        if [[ "$BODY" == @* ]]; then
            CURL_ARGS+=(--data "@${BODY:1}")
        else
            CURL_ARGS+=(--data "$BODY")
        fi
    fi

    HTTP_CODE=$(curl "${CURL_ARGS[@]}")
    RESULTS+=("${LABEL}: ${HTTP_CODE}")
done

# Affichage en ligne unique
( IFS=" | "; echo "  ${RESULTS[*]}" )

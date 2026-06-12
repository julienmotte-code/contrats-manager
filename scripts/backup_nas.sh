#!/usr/bin/env bash
#
# backup_nas.sh — Sauvegarde complète et chiffrée de Gestion SGI vers le NAS (CIFS)
#
# Une archive auto-portante par exécution :
#   db.dump        : pg_dump -Fc de la base 'contrats' (restaurable via pg_restore)
#   storage.tar.gz : répertoire applicatif ./storage (documents générés, modèles)
#   config/        : .env, docker-compose.yml, Dockerfile.frontend, backend/Dockerfile,
#                    daemon.json, cloudflared/ (indispensables à une restauration)
# Archive chiffrée GPG AES256 (contient des secrets).
# Rotation : 14 quotidiennes + 8 hebdomadaires (dimanche).
# Exécuté en root via /etc/cron.d/backup-nas. Aucun secret codé en dur ici :
#   passphrase GPG   -> /root/.nas_backup_passphrase (root, 600)
#   credentials CIFS -> /etc/cifs-credentials-nas    (root, 600, via fstab)
#
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# --- Configuration ---
PROJECT_DIR="/home/user/contrats"
DB_SERVICE="db"
DB_NAME="contrats"
DB_USER="contrats"
NAS_MOUNT="/mnt/nas-sauvlinux"
DEST_ROOT="${NAS_MOUNT}/gestion-sgi"
DEST_DAILY="${DEST_ROOT}/daily"
DEST_WEEKLY="${DEST_ROOT}/weekly"
PASSPHRASE_FILE="/root/.nas_backup_passphrase"
RETAIN_DAILY=14
RETAIN_WEEKLY=8
LOG_FILE="/var/log/backup-nas.log"

log()  { echo "$(date '+%Y-%m-%d %H:%M:%S') [backup-nas] $*" | tee -a "$LOG_FILE"; }
fail() { log "ERREUR: $*"; exit 1; }

STAMP="$(date '+%Y%m%d_%H%M%S')"
DOW="$(date '+%u')"   # 1=lundi .. 7=dimanche
WORKDIR="$(mktemp -d /tmp/backup-nas.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

log "=== Démarrage sauvegarde ${STAMP} ==="

# --- Pré-vérifications ---
[ -f "$PASSPHRASE_FILE" ] || fail "passphrase GPG absente: $PASSPHRASE_FILE"
command -v gpg >/dev/null || fail "gpg introuvable"
command -v docker >/dev/null || fail "docker introuvable dans le PATH"

if ! mountpoint -q "$NAS_MOUNT"; then
  log "NAS non monté, tentative de montage..."
  mount "$NAS_MOUNT" || fail "montage NAS impossible ($NAS_MOUNT)"
fi
mountpoint -q "$NAS_MOUNT" || fail "NAS toujours pas monté"
mkdir -p "$DEST_DAILY" "$DEST_WEEKLY"

# --- 1) Dump base ---
log "Dump PostgreSQL (pg_dump -Fc)..."
cd "$PROJECT_DIR"
docker compose exec -T "$DB_SERVICE" pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$WORKDIR/db.dump" \
  || fail "pg_dump a échoué"
[ -s "$WORKDIR/db.dump" ] || fail "dump vide"
log "Dump OK ($(du -h "$WORKDIR/db.dump" | cut -f1))"

# --- 2) Storage ---
log "Archivage de storage/..."
tar czf "$WORKDIR/storage.tar.gz" -C "$PROJECT_DIR" storage || fail "tar storage a échoué"

# --- 3) Config / secrets ---
log "Collecte de la configuration..."
mkdir -p "$WORKDIR/config/cloudflared"
cp "$PROJECT_DIR/.env"                "$WORKDIR/config/.env"
cp "$PROJECT_DIR/docker-compose.yml"  "$WORKDIR/config/docker-compose.yml"
cp "$PROJECT_DIR/Dockerfile.frontend" "$WORKDIR/config/Dockerfile.frontend"
cp "$PROJECT_DIR/backend/Dockerfile"  "$WORKDIR/config/backend.Dockerfile"
cp /etc/docker/daemon.json            "$WORKDIR/config/daemon.json"
cp -r /etc/cloudflared/.              "$WORKDIR/config/cloudflared/" 2>/dev/null \
  || log "AVERTISSEMENT: /etc/cloudflared non copié"

# --- 4) Assemblage + chiffrement ---
ARCHIVE="gestion-sgi_${STAMP}.tar.gz"
log "Assemblage de l'archive..."
tar czf "$WORKDIR/$ARCHIVE" -C "$WORKDIR" db.dump storage.tar.gz config
log "Chiffrement GPG (AES256)..."
gpg --batch --yes --passphrase-file "$PASSPHRASE_FILE" --cipher-algo AES256 -c \
    -o "$WORKDIR/${ARCHIVE}.gpg" "$WORKDIR/$ARCHIVE" || fail "chiffrement GPG a échoué"

# --- 5) Dépôt NAS ---
log "Copie vers le NAS (daily)..."
cp "$WORKDIR/${ARCHIVE}.gpg" "$DEST_DAILY/${ARCHIVE}.gpg"; sync
if [ "$DOW" = "7" ]; then
  log "Dimanche -> copie hebdomadaire..."
  cp "$WORKDIR/${ARCHIVE}.gpg" "$DEST_WEEKLY/${ARCHIVE}.gpg"; sync
fi
log "Déposé: $DEST_DAILY/${ARCHIVE}.gpg ($(du -h "$DEST_DAILY/${ARCHIVE}.gpg" | cut -f1))"

# --- 6) Rotation ---
prune() {
  local dir="$1" keep="$2" i=0 f
  local files=()
  mapfile -t files < <(find "$dir" -maxdepth 1 -name 'gestion-sgi_*.tar.gz.gpg' -printf '%T@ %p\n' 2>/dev/null | sort -rn | cut -d' ' -f2-)
  for f in "${files[@]}"; do
    i=$((i+1))
    if [ "$i" -gt "$keep" ]; then
      log "Rotation: suppression $(basename "$f")"
      rm -f "$f"
    fi
  done
}
prune "$DEST_DAILY"  "$RETAIN_DAILY"
prune "$DEST_WEEKLY" "$RETAIN_WEEKLY"

log "=== Sauvegarde ${STAMP} terminée avec succès ==="

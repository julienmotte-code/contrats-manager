# Restauration depuis le NAS

Sauvegardes dans `//192.168.1.222/sauvlinux/gestion-sgi/{daily,weekly}/`,
archives chiffrées `gestion-sgi_AAAAMMJJ_HHMMSS.tar.gz.gpg`.
Passphrase GPG : `/root/.nas_backup_passphrase` (à conserver aussi hors machine).

## 1. Récupérer et déchiffrer
    sudo mount /mnt/nas-sauvlinux   # si pas déjà monté
    ARCHIVE=/mnt/nas-sauvlinux/gestion-sgi/daily/gestion-sgi_AAAAMMJJ_HHMMSS.tar.gz.gpg
    sudo gpg --batch --passphrase-file /root/.nas_backup_passphrase -o /tmp/restore.tar.gz -d "$ARCHIVE"
    mkdir -p /tmp/restore && tar xzf /tmp/restore.tar.gz -C /tmp/restore

## 2. Restaurer la base (ATTENTION : écrase les données actuelles)
    cd /home/user/contrats
    cat /tmp/restore/db.dump | docker compose exec -T db pg_restore -U contrats -d contrats --clean --if-exists

## 3. Restaurer les fichiers applicatifs
    tar xzf /tmp/restore/storage.tar.gz -C /home/user/contrats

## 4. Configuration / secrets
Fichiers de `/tmp/restore/config/` (.env, docker-compose.yml, Dockerfiles,
daemon.json, cloudflared/) pour reconstruire une instance from scratch.
Les replacer aux bons emplacements puis : `docker compose up -d --build`.

## Nettoyage
    rm -rf /tmp/restore /tmp/restore.tar.gz

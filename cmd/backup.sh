#!/bin/sh
# Daily backup of the "gestao" stack: Postgres dump + MinIO files -> restic repo on Google Drive.
# Installed on the server as /usr/local/sbin/gestao-backup, run by root's cron at 03:00.
# Restore steps: cmd/RESTORE.md
set -eu

export RESTIC_REPOSITORY='rclone:gdrive:gestao-backup'
export RESTIC_PASSWORD_FILE=/root/.config/restic/gestao.pass
DIR=/var/backups/gestao
# Optional dead-man switch (healthchecks.io ping URL): alerts when a backup fails OR doesn't run
HC_URL=$(cat /root/.config/restic/gestao.hc 2>/dev/null || true)

ping() { [ -z "$HC_URL" ] || curl -fsS -m 10 --retry 3 "$HC_URL$1" >/dev/null || true; }
trap 'ping /fail' EXIT  # cleared at the end: any error on the way reports a failure
ping /start
echo "== $(date '+%F %T') backup start"

mkdir -p "$DIR"
DB=$(docker ps -q -f name=gestao_database | head -1)
[ -n "$DB" ] || { echo 'database container not found'; exit 1; }
# Plain SQL on purpose (not -Fc): restic dedups + compresses it, so each day only uploads
# what changed. A compressed dump differs entirely every day and would be stored whole.
docker exec "$DB" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' > "$DIR/gestao.sql.tmp"
mv "$DIR/gestao.sql.tmp" "$DIR/gestao.sql"

# ponytail: raw MinIO data dir (single drive); consistent enough at 3am, restored as a whole dir
MINIO=$(docker volume inspect gestao_minio_data --format '{{.Mountpoint}}')
restic backup --tag daily --host ohenriquecedor "$DIR/gestao.sql" "$MINIO"

restic forget --tag daily --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
# Sundays: verify the repo and re-read a sample of the stored data
[ "$(date +%u)" != 7 ] || restic check --read-data-subset=10%

trap - EXIT
ping ''
echo "== $(date '+%F %T') backup ok"

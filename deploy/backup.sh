#!/usr/bin/env bash
# Back up the production database on the VPS. Run it by hand or from cron (see the guide):
#   ./deploy/backup.sh
# Keeps the last KEEP_DAYS days (default 14) in BACKUP_DIR (default ~/picksnap-backups).
# The files contain client data: they are readable by you only. A backup that lives only
# on the same server is not enough, so copy the folder somewhere else as well.
set -euo pipefail
cd "$(dirname "$0")/.."
dir="${BACKUP_DIR:-$HOME/picksnap-backups}"
keep="${KEEP_DAYS:-14}"
project="${COMPOSE_PROJECT:-}"
compose=(docker compose ${project:+-p "$project"} --env-file deploy/.env.production -f deploy/docker-compose.prod.yml)

umask 077
mkdir -p "$dir"
out="$dir/photo-$(date -u +%Y%m%dT%H%M%SZ).dump"
# The maintenance role is a superuser, so row-level security does not hide any studio's rows.
"${compose[@]}" exec -T db pg_dump -U photo -d photo --format=custom --no-owner --no-privileges > "$out"

# A dump that cannot be listed is not a backup.
if ! "${compose[@]}" exec -T db pg_restore --list < "$out" > /dev/null; then
  rm -f "$out"
  echo "Backup failed: the dump could not be read back." >&2
  exit 1
fi
find "$dir" -name 'photo-*.dump' -mtime +"$keep" -delete
echo "Backup written: $out ($(du -h "$out" | cut -f1))"

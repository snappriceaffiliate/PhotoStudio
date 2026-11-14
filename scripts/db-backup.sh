#!/usr/bin/env bash
# Take a full backup of the database in PostgreSQL's custom format.
#   DATABASE_URL=postgres://... ./scripts/db-backup.sh [output-file]
# Managed databases already keep daily backups; this is for an extra off-site copy and
# for restore drills. Store the file somewhere private: it contains client data.
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL}"
out="${1:-backup-$(date -u +%Y%m%dT%H%M%SZ).dump}"
# Tenant tables use row-level security. The app role is not a superuser, so the dump runs
# with the policies on and the bypass setting the platform uses for cross-studio work.
PGOPTIONS="-c app.bypass_rls=on" pg_dump --enable-row-security --format=custom --no-owner \
  --no-privileges --dbname="$DATABASE_URL" --file="$out"
echo "Backup written to $out ($(du -h "$out" | cut -f1))"

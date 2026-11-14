#!/usr/bin/env bash
# Restore drill: load a backup into a scratch database, compare row counts with the live
# database, then drop the scratch copy. Never points at the live database for writing.
#   DATABASE_URL=postgres://... SCRATCH_URL=postgres://.../restore_check ./scripts/db-restore-check.sh backup.dump
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL (the live database, read only here)}"
: "${SCRATCH_URL:?Set SCRATCH_URL (an empty scratch database, dropped afterwards)}"
dump="${1:?Pass the backup file}"
if [ "$DATABASE_URL" = "$SCRATCH_URL" ]; then echo "SCRATCH_URL must not be the live database"; exit 1; fi

# Writing rows into tables with forced row-level security needs the same bypass setting.
PGOPTIONS="-c app.bypass_rls=on" pg_restore --no-owner --no-privileges --exit-on-error \
  --dbname="$SCRATCH_URL" "$dump"

# Row-level security hides rows unless the bypass setting is on for this session.
counts() {
  psql "$1" -Atq -v ON_ERROR_STOP=1 <<'SQL'
SET app.bypass_rls = 'on';
SELECT 'studios', count(*) FROM studios_studio
UNION ALL SELECT 'users', count(*) FROM accounts_user
UNION ALL SELECT 'events', count(*) FROM events_event
UNION ALL SELECT 'photos', count(*) FROM photos_photo
UNION ALL SELECT 'client logins', count(*) FROM clients_clientaccess
UNION ALL SELECT 'selections', count(*) FROM clients_selection
UNION ALL SELECT 'subscriptions', count(*) FROM billing_subscription
UNION ALL SELECT 'audit entries', count(*) FROM audit_auditentry;
SQL
}
live=$(counts "$DATABASE_URL"); restored=$(counts "$SCRATCH_URL")
paste -d'|' <(echo "$live") <(echo "$restored" | cut -d'|' -f2) | awk -F'|' '{printf "%-15s live %8s  restored %8s  %s\n", $1, $2, $3, ($2==$3?"ok":"DIFFERENT")}'
if [ "$live" != "$restored" ]; then echo "Restore check FAILED (counts differ; did data change after the backup?)"; exit 1; fi
echo "Restore check passed."

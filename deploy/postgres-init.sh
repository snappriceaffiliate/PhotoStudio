#!/bin/sh
# Runs once, when the database volume is first created.
# The app connects as photo_app, which is NOT a superuser, so PostgreSQL row-level security
# always applies to it (the second layer that keeps studios apart). "photo" is only for
# maintenance.
set -eu
psql -v ON_ERROR_STOP=1 -v app_password="$APP_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE photo_app LOGIN PASSWORD :'app_password';
ALTER DATABASE photo OWNER TO photo_app;
SQL

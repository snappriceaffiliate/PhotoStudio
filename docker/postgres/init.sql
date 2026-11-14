-- Runs once, when the local database volume is first created.
-- The app connects as photo_app, which is NOT a superuser, so PostgreSQL row-level
-- security applies to it. The "photo" superuser is only for maintenance.
CREATE ROLE photo_app LOGIN PASSWORD 'photo_app' CREATEDB;
ALTER DATABASE photo OWNER TO photo_app;

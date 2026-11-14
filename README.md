# Photo Selection Portal

Studios share a shoot online; clients pick the photos to print; the studio gets the list of
selected files. Photos are compressed in the browser so every stored preview and thumbnail is
at most 100 KB. RAW originals never leave the studio's computer.

Stack: React (Vite) + Django 5.2 + Django REST Framework + PostgreSQL, Procrastinate for
background jobs, Cloudflare R2 for storage. One monolith: Django serves the built React app.

## Run it locally

Needs Docker.

```bash
cp .env.example .env
docker compose up --build
```

| What | Where |
| --- | --- |
| App (Vite dev server) | http://localhost:5173 |
| Django API and admin | http://localhost:8000 |
| Email inbox (Mailpit) | http://localhost:8025 |
| Local S3 storage (SeaweedFS) | http://localhost:8333, keys `devkey` / `devsecret` |
| PostgreSQL | localhost:5433, database `photo`; app role `photo_app` / `photo_app` |

The web container runs migrations and creates the storage bucket on start. Local storage uses
SeaweedFS as an S3-compatible stand-in for R2, because MinIO no longer publishes images.

The app connects as `photo_app`, which is **not** a PostgreSQL superuser, so row-level security
applies (see `backend/apps/core/tenancy.py`). If you created the database volume before this
role existed, reset it once with `docker compose down -v`.

### Demo data

```bash
docker compose exec web python manage.py seed_demo
```

Creates two studios with an owner, a staff member and two events each, plus a platform admin.
All demo accounts use the password `demo-pass-2026` (override with `DEMO_PASSWORD`).

| Account | Email |
| --- | --- |
| Studio 1 owner / staff | `owner@lensandlight.test` / `staff@lensandlight.test` |
| Studio 2 owner / staff | `owner@goldenhour.test` / `staff@goldenhour.test` |
| Platform admin (Django admin) | `admin@platform.test` |

Emails sent by the app (verification, password reset, staff invitations) appear in Mailpit.
The client gallery is at http://localhost:5173/gallery/login; share an event from its page to get a login.
The Sprint 0 spike page is at http://localhost:5173/dev/spikes (development only).

## Deploying

See [docs/deployment.md](docs/deployment.md) for what hosting needs, the environment variables and
the first-deploy checklist.

## Tests and checks

```bash
docker compose exec web pytest                                    # backend tests
docker compose exec web python manage.py makemigrations --check   # no missing migrations
cd backend && uv run ruff check . && uv run ruff format --check . # backend lint
cd frontend && npm run lint && npm test && npm run build          # frontend
```

CI runs all of these on every pull request (`.github/workflows/ci.yml`) and builds the
production image.

## Layout

```text
backend/            Django project
  config/           settings (all from environment variables), urls, wsgi
  apps/core/        tenant scoping and row-level security, storage, health check, SPA view
  apps/studios/     Studio (the tenant)
  apps/accounts/    users (email login, Owner and Staff roles), auth and staff API
  apps/events/      events and albums (row-level security on)
  apps/photos/      upload manifest, signed upload URLs, 100 KB check, photo list, clean-up job
  apps/clients/     client logins, gallery API, selections (limit enforced), submission
  apps/notifications/ emails, sent as background jobs
  apps/spikes/      Sprint 0 storage spike endpoints (only when SPIKES_ENABLED=true)
frontend/           React app (TypeScript, Vite, React Router)
  src/pages/        sign-in, sign-up, password, email confirmation, events, event, staff screens
  src/gallery/      client gallery: login, grid, swipe viewer, select, notes, submit
  src/upload/       folder uploader: compress, upload, confirm in batches; pause and resume
  src/auth/         logged-in user state
  src/compression/  RAW preview extraction, WebP compression to 100 KB, worker pool
  src/api/          API client (session cookie and CSRF)
docker/             Dockerfile (dev and production targets), local DB role, SeaweedFS, R2 CORS template
docs/               deployment guide
```

## Sprint 0 spikes

The spike page (http://localhost:5173/dev/spikes) is used to settle the Sprint 0 exit criteria.

1. **Compression.** Choose a folder of real RAW and JPEG files from the studios' cameras. The page
   extracts each RAW file's embedded JPEG preview, compresses a preview (about 1600 px) and a
   thumbnail (about 400 px) to WebP under 100 KB, and reports success by file type, sizes, quality
   and time per photo. Click a row to judge quality full screen. **Download CSV report** saves the
   results to share with the team.
2. **Storage.** Uploads five previews straight to storage with signed URLs, has the server check
   each size (anything over 100 KB is refused or deleted), and shows them through 15-minute signed
   delivery URLs.

Still to do in Sprint 0: run the compression page on real camera files from at least three brands,
review image quality with studios, test on Safari (WebP encoding support), and choose the hosting
provider, then point staging at a real R2 bucket.

## Production image

```bash
docker build -f docker/Dockerfile --target production -t photo-selection .
```

The same image runs the web process (Gunicorn, the default command) and the worker
(`python manage.py procrastinate worker`).

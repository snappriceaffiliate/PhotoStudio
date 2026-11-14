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
| PostgreSQL | localhost:5433, user / password / db `photo` |

The web container runs migrations and creates the storage bucket on start. Local storage uses
SeaweedFS as an S3-compatible stand-in for R2, because MinIO no longer publishes images.

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
  apps/core/        tenant-scoped base models, storage access, health check, jobs
  apps/studios/     Studio (the tenant)
  apps/spikes/      Sprint 0 storage spike endpoints (only when SPIKES_ENABLED=true)
frontend/           React app (TypeScript, Vite)
  src/compression/  RAW preview extraction, WebP compression to 100 KB, worker pool
  src/api/          API clients
docker/             Dockerfile (dev and production targets), SeaweedFS dev credentials
```

## Sprint 0 spikes

The app currently opens on the spike page, used to settle the Sprint 0 exit criteria.

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

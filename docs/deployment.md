# Deployment guide

The app ships as **one Docker image** (`docker/Dockerfile`, target `production`). Any platform
that can run a Docker image as a web service plus a second process (the worker), next to a
managed PostgreSQL database, can host it: for example Render, Railway, Fly.io, DigitalOcean App
Platform, Google Cloud Run, or AWS App Runner / ECS. Pick a region close to Indian studios and
clients (Mumbai, or Singapore if Mumbai is not offered).

## What is needed from you

| Item | Used for | Notes |
| --- | --- | --- |
| Hosting platform account and project | Web process and worker | Two services from the same image |
| Managed PostgreSQL 16 or 17 | All data, sessions, job queue, rate limits | Daily backups and point-in-time recovery if offered |
| Cloudflare R2 bucket (one for staging, one for production) | Compressed previews and thumbnails | Private bucket; never public |
| R2 API token (Access Key ID and Secret) for each bucket | Signed upload and download URLs | "Object Read & Write" permission, limited to that bucket |
| Cloudflare account ID | R2 endpoint address | `https://<account_id>.r2.cloudflarestorage.com` |
| Domain name, for example `app.yourproduct.in` | The app address | DNS pointed at the hosting platform |
| Transactional email service (Amazon SES, Resend or Brevo) | Verification, password and invitation emails | SMTP host, port, username, password; verified sending domain |
| Sentry project (optional, recommended) | Error tracking | The DSN |
| Razorpay key ID, key secret and webhook secret | Subscriptions | Test mode first, then live mode |

## Database setup

The app must connect as a PostgreSQL role that is **not a superuser**. Superusers skip
row-level security, which is the second layer of tenant isolation (see
`backend/apps/core/tenancy.py`). Most managed databases already give you a non-superuser role.
Run this once as the admin user if you need to create one:

```sql
CREATE ROLE photo_app LOGIN PASSWORD '<strong password>';
CREATE DATABASE photo OWNER photo_app;
```

Check it with `SELECT rolsuper FROM pg_roles WHERE rolname = current_user;` while connected as the
app role: it must return `false`.

## R2 setup

1. Create the bucket (for example `photo-selection-prod`), with public access **off**.
2. Create an API token with Object Read & Write on that bucket only.
3. Add a CORS rule so browsers can upload straight to the bucket. Start from
   `docker/r2-cors.json` and replace the origin with the app's real address.
4. Add a lifecycle rule that deletes objects under the `incoming/` prefix after 1 day. Browsers
   upload there first; checked images are copied to their final place.

## Razorpay setup

Do this once in test mode, check a payment end to end, then repeat in live mode for production.

1. Create API keys in the Razorpay Dashboard and set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`.
2. Create a webhook pointing to `https://<domain>/api/v1/billing/webhook` with a secret of your choice
   (set it as `RAZORPAY_WEBHOOK_SECRET`). Subscribe it to the `subscription.*` events: authenticated,
   activated, charged, completed, updated, pending, halted, cancelled, paused, resumed.
3. Confirm the plan prices and limits in Django admin (Billing > Plans), then create the matching
   Razorpay plans: `python manage.py sync_razorpay_plans`. Plan IDs differ between test and live mode,
   so run it in each environment.
4. Subscribe from the Billing screen with a Razorpay test card, and check in Django admin that the
   subscription is Active and a `subscription.charged` webhook was received.

Prices are monthly, in rupees, and editable in the admin. Changing a price after customers subscribe
needs a new Razorpay plan; existing subscribers stay on the old one.

## Processes

| Process | Command | Notes |
| --- | --- | --- |
| Release (before each deploy) | `python manage.py migrate --noinput` | Run once per deploy, not by every container |
| Web | image default: `gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3` | Health check path: `/api/health` |
| Worker | `python manage.py procrastinate worker` | Same image, same environment variables |

## Environment variables

| Variable | Example | Required |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | a long random string | Yes |
| `DJANGO_DEBUG` | `false` | Yes |
| `DJANGO_ALLOWED_HOSTS` | `app.yourproduct.in` | Yes |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://app.yourproduct.in` | Yes |
| `APP_URL` | `https://app.yourproduct.in` | Yes, used in email links |
| `DATABASE_URL` | `postgres://photo_app:...@host:5432/photo` | Yes |
| `S3_ENDPOINT_INTERNAL` | `https://<account_id>.r2.cloudflarestorage.com` | Yes |
| `S3_ENDPOINT_PUBLIC` | same as above | Yes |
| `S3_BUCKET` | `photo-selection-prod` | Yes |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | from the R2 API token | Yes |
| `S3_REGION` | `auto` | Yes |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | from the email service | Yes |
| `EMAIL_USE_TLS` | `true` | Yes |
| `DEFAULT_FROM_EMAIL` | `Your Product <noreply@yourproduct.in>` | Yes |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | from Razorpay API keys (test or live) | For payments |
| `RAZORPAY_WEBHOOK_SECRET` | the secret you set on the webhook | For payments |
| `TRIAL_DAYS` | `30` | Optional |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | from Sentry; `staging` or `production` | Recommended |
| `DJANGO_HSTS_SECONDS` | `3600` at first, `31536000` once HTTPS is stable | Optional |
| `NUM_PROXIES` | `1` (proxies in front of the app) | Yes; wrong values break rate limits |
| `CSP_ENFORCE` | `false` until checked on staging, then `true` | Recommended |
| `DJANGO_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_HSTS_PRELOAD` | `true` once every subdomain is HTTPS-only | Optional |
| `SPIKES_ENABLED` | leave unset | Never in production |
| `DJANGO_SECURE_COOKIES` | leave unset | Never in production (local load tests only) |

Staging only: `ALLOW_DEMO_SEED=true` and `DEMO_PASSWORD` let `python manage.py seed_demo` create
demo studios.

## First deploy checklist

- [ ] Database created with a non-superuser app role
- [ ] R2 bucket private, API token scoped to it, CORS rule set to the app origin
- [ ] Environment variables set on both the web and worker services
- [ ] Release command runs migrations
- [ ] `https://<domain>/api/health` returns `{"status": "ok", "database": "ok"}`
- [ ] Create the first platform admin: `python manage.py createsuperuser`, then `python manage.py setup_admin_2fa <email>`
- [ ] Sign up a test studio, receive the verification email, and log in
- [ ] Razorpay webhook set up and `sync_razorpay_plans` run
- [ ] Sentry receives a test error
- [ ] Work through the "Before going live" list in `docs/security.md`

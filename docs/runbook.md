# Operations runbook

Routine tasks and what to do when something goes wrong. Commands run in the web container
(or the hosting platform's shell) unless stated otherwise.

## Platform admin

| Task | How |
| --- | --- |
| Create the first admin | `python manage.py createsuperuser` |
| Turn on the authenticator code (required to open the admin) | `python manage.py setup_admin_2fa admin@example.com`, then scan the QR code |
| Admin lost their phone | Run `setup_admin_2fa` again; the old code stops working |

## Backups and restore drill

The managed database keeps daily backups with point-in-time recovery. In addition:

1. Take a copy: `DATABASE_URL=... ./scripts/db-backup.sh backup.dump`
   (needs `pg_dump` 17; store the file privately, it contains client data).
2. Check it restores: create an empty scratch database owned by the app role, then
   `DATABASE_URL=... SCRATCH_URL=.../scratch ./scripts/db-restore-check.sh backup.dump`.
   It compares row counts table by table and prints "Restore check passed".
3. Drop the scratch database afterwards.

Both scripts switch on the row-level security bypass for their session; without it, a backup
taken with the app's role would fail. Run the drill monthly and after any schema change.

Photo previews are not backed up: studios keep the originals and can upload again.

## Load test

```bash
docker compose exec web python manage.py seed_load_test --photos 3000
uvx locust -f loadtest/locustfile.py --host https://staging.example --headless -u 60 -r 10 -t 90s
```

On staging, set `ALLOW_DEMO_SEED=true` and `THROTTLE_SCALE=1000` for the test only, then
remove them. Baseline on a laptop (production image, 3 workers, 60 users, 3,000 photos):
0 errors, median 23 ms, 95th percentile 56 ms, 99th percentile 190 ms.

## Incidents

| Situation | Response |
| --- | --- |
| A client's gallery login leaked | Event screen › Client › New password (ends open sessions), or Turn off access |
| A staff member left | Staff screen › Remove (their sessions end at once) |
| A studio reports someone else's photos | Treat as a data incident: check the audit log in the admin, keep logs, contact the studio, review tenant isolation |
| Razorpay shows a payment the app did not record | Admin › Billing › Webhook events: check the event arrived and was processed; set the subscription by hand if needed and note it |
| Secret key or storage keys exposed | Rotate them in the hosting platform's settings and redeploy. A new `DJANGO_SECRET_KEY` logs everyone out and invalidates open reset links |
| Storage costs jump | Check the R2 `incoming/` lifecycle rule is in place; abandoned uploads are cleaned nightly |

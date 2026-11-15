# Deploying to a VPS

One server runs everything: PostgreSQL, the web app, the background worker and Caddy (which
handles HTTPS). Photos live in Cloudflare R2 and email goes through an email service, so the
server stays small. The files are in `deploy/`; `docs/deployment.md` explains each setting.

## What you need before starting

| Item | Notes |
| --- | --- |
| A VPS | Ubuntu 24.04, at least 2 GB memory and 2 vCPUs, 40 GB disk. Pick a region near your clients (Mumbai if offered). |
| A domain | For example `app.yourname.in`. HTTPS, and therefore the login cookies, need a real domain. |
| R2 bucket and key | The bucket passes `check_storage` (see `docs/deployment.md`). |
| Email service SMTP login | With the sending domain verified. |
| Razorpay test keys | Optional for the first deploy. Without them, studios stay on their free trial. |

## 1. Point the domain at the server

At your domain's DNS settings add an **A record**: name `app` (or whatever you chose), value
the server's public IP address. Check it from your computer:

```bash
dig +short app.yourname.in
```

It must print the server's address before you go further (it can take a few minutes).

## 2. Secure the server

Log in as root once, then:

```bash
adduser deploy && usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

Open a **second** terminal and check `ssh deploy@<server ip>` works before the next step.
Then turn off password logins and the root login, and switch on the firewall and automatic
security updates:

```bash
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443 && sudo ufw --force enable
sudo apt-get update && sudo apt-get install -y fail2ban unattended-upgrades git
```

Only ports 22, 80 and 443 are open. The database has no published port at all.

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
```

Log out and in again, then check `docker compose version`.

## 4. Get the code and create the settings

```bash
git clone https://github.com/snappriceaffiliate/PhotoStudio.git
cd PhotoStudio
./deploy/make-env.sh app.yourname.in
nano deploy/.env.production
```

`make-env.sh` creates the file with random secrets, readable by you only. Fill in the
storage section (endpoint, bucket, access key, secret), the email section and, when you have
them, the Razorpay keys. Never put this file in Git (it is ignored) and never paste it into
a chat.

## 5. Start it

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml up -d --build
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml ps
```

The first build takes a few minutes. All four services (`db`, `web`, `worker`, `caddy`)
should be running, with `web` healthy. Caddy asks Let's Encrypt for the certificate on the
first visit; this needs port 80 open and the DNS record from step 1.

To save typing, add this to `~/.bashrc` and log in again:

```bash
alias pick='docker compose --env-file ~/PhotoStudio/deploy/.env.production -f ~/PhotoStudio/deploy/docker-compose.prod.yml'
```

The rest of this guide uses `pick`, for example `pick ps` and `pick logs -f web`.

## 6. Check it works

1. Open `https://app.yourname.in/api/health`. It shows `{"status": "ok", "database": "ok"}`.
2. Open `https://app.yourname.in`. The login screen loads, with a padlock.
3. Check the storage settings the app is really using, including browser uploads from your
   domain. Add `https://app.yourname.in` to `AllowedOrigins` in the R2 bucket's CORS policy
   first, then run:

   ```bash
   pick exec web python manage.py check_storage --origin https://app.yourname.in
   ```

   Every line should say ok. The cleanup-rule note is confirmed in the Cloudflare dashboard.
4. Create the first platform admin, then give it the authenticator code:

   ```bash
   pick exec web python manage.py createsuperuser
   pick exec web python manage.py setup_admin_2fa you@example.com
   ```

5. Sign up a test studio, confirm the email arrives in a real inbox, create an event, upload
   a few photos, share it, and open the gallery on your phone.
6. Work through "Before going live" in `docs/security.md` and the must-pass cases in the
   "PickSnap: Test Cases" document.

If you use Razorpay, create the webhook (`https://app.yourname.in/api/v1/billing/webhook`)
and run `pick exec web python manage.py sync_razorpay_plans`, as in `docs/deployment.md`.

## 7. Backups

Run a backup by hand to see it work, then schedule it:

```bash
./deploy/backup.sh
crontab -e
```

Add the line below (a backup at 02:30 every night, keeping 14 days):

```
30 2 * * * cd /home/deploy/PhotoStudio && ./deploy/backup.sh >> /home/deploy/backup.log 2>&1
```

A backup on the same server is lost with the server, so also copy `~/picksnap-backups` to
another place regularly (your own computer, or a second R2 bucket with `rclone`). Practise a
restore with `scripts/db-restore-check.sh` (see `docs/runbook.md`) before you need it.

## 8. Watching it

- Add `https://app.yourname.in/api/health` to a free uptime checker (UptimeRobot or similar)
  that emails you when it fails.
- Turn on the provider's snapshot or backup feature for the whole server as well.
- Add a Sentry project and set `SENTRY_DSN` in `deploy/.env.production` to see errors.
- Logs: `pick logs -f web`, `pick logs -f worker`, `pick logs caddy`.

## Updating to a new version

```bash
cd ~/PhotoStudio
git pull
./deploy/backup.sh
pick up -d --build
pick ps
```

The web container applies database changes when it starts. Check `/api/health` afterwards.
Studios in the middle of an upload can resume it by choosing the folder again.

**Roll back:** `git log --oneline` to find the previous good version, `git checkout <id>`,
and `pick up -d --build`. If a database change must be undone, restore the backup taken
just before the update (`pg_restore`, see the runbook).

## Changing a setting

Edit `deploy/.env.production`, then `pick up -d` (this restarts the services whose settings
changed). Changing `DJANGO_SECRET_KEY` logs everybody out and ends open reset links.

## When something fails

| Symptom | Look at |
| --- | --- |
| The site does not load, or the browser warns about the certificate | `pick logs caddy`: usually the DNS record is wrong, or port 80 is blocked by a firewall at the provider |
| 400 Bad Request on every page | `DJANGO_ALLOWED_HOSTS` does not list the domain exactly as typed |
| Login works but the next page logs you out | `DJANGO_CSRF_TRUSTED_ORIGINS` and `APP_URL` must start with `https://` and match the domain |
| Uploads fail in the browser but not in `check_storage` | The R2 CORS policy does not include the domain |
| No emails arrive | `pick logs worker`, then the SMTP login and the verified sending domain |
| `web` keeps restarting | `pick logs web`: a missing setting (for example `DJANGO_SECRET_KEY`) is named in the message |
| Everyone shares one rate limit | `NUM_PROXIES` must be 1 (Caddy is the one proxy) |

## What this setup does not do

It is one server: if it goes down, the service is down until it is back. That is normal for
a first launch. The database, the worker and the app all share the server's memory, so watch
memory and disk (`docker stats`, `df -h`) as studios are added, and move the database to a
managed service when the number of studios grows.

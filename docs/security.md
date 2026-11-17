# Security notes

How the app protects studio and client data, what the MVP hardening review found, and the
risks accepted for now. Update this file when any of it changes.

## How data is protected

| Area | Protection |
| --- | --- |
| Studios kept apart | Every query is scoped to the logged-in studio in Django, and PostgreSQL row-level security enforces the same rule in the database (`apps/core/tenancy.py`). The app's database role is not a superuser, so the policies always apply. Tests cover both layers. |
| Studio logins | Argon2 password hashes, email confirmation, HTTP-only and Secure cookies, CSRF checks, limits of 20 tries per account per hour and 30 per IP address per minute. |
| Client logins | Generated passwords (about 59 bits) and usernames with a 6-character random part. Lockout after 5 wrong tries, with the same answer for unknown, wrong and locked logins. Sessions end when the studio resets the password or turns access off. |
| Platform admin | Password plus an authenticator-app code (django-otp). Cross-studio access in the admin only after both steps. |
| Photos | Private bucket. Uploads go to one-time incoming keys; the server checks size (40 KB) and that each file is really WebP, then copies it to a final key no upload link can write to. Viewing uses signed links that expire after 15 minutes. |
| Payments | Checkout confirmations are checked against the stored subscription, accepted once per payment, and only when Razorpay reports the subscription active. Webhooks are signature-checked and de-duplicated. A paid plan without renewal runs out after its period plus 7 days. |
| Exports | CSV cells that could run as spreadsheet formulas are neutralised. The copy scripts keep file names as data: the Windows script reads them from data lines, so `&`, `%` and similar characters are never run as commands. Titles and names in script comments are reduced to plain characters. Paths with control characters or `| * ? " < >` are refused at upload. |
| Browser | HSTS, `nosniff`, no framing, same-origin referrers, a restrictive Permissions-Policy and a Content-Security-Policy (report-only until checked on staging). |
| Abuse | Sharing galleries and inviting staff need a confirmed email. Plan limits cap events, photos and people. |
| Secrets | The app will not start in production without `DJANGO_SECRET_KEY`. Keys live only in the hosting platform's environment settings. |

## Hardening review, 14 November 2026

An independent review of the code found these issues; all are fixed and covered by tests in
`backend/tests/test_hardening.py`:

1. **High.** A replayed Checkout confirmation could re-activate a cancelled or lapsed plan.
2. **High.** File names containing `&` could run commands from the Windows copy script.
3. **Medium.** Line breaks in an event title or client name could add commands to the copy scripts.
4. **Medium.** Rate limits could be bypassed with a forged `X-Forwarded-For` header, and were counted per email-and-IP pair instead of separately.
5. **Medium.** Predictable client usernames let strangers lock clients out, and the lockout message confirmed which usernames existed.
6. **Medium.** An upload link could be reused after the server checked the photo, replacing it with anything of any size.
7. **Low-medium.** Resetting a client's password did not end sessions already open.
8. **Low-medium.** A missing secret key fell back silently to a public development value.
9. **Low.** Upload sessions accepted files after finishing, including for archived events.
10. **Low.** A malformed album filter caused a server error instead of a 400.

Known before the review and also fixed: CSV formula injection, size-only upload checks, no
Content-Security-Policy, no second factor for the platform admin, and unconfirmed accounts able
to send invitations.

## Accepted risks (revisit before or after launch)

- **Sign-up reveals whether an email is registered.** Accepted for now: rate limits apply, and a
  generic answer would confuse studios who mistype. Revisit if abuse appears.
- **The app's database role can turn on the row-level security bypass.** This protects against a
  forgotten filter in code, not against SQL injection (none is known; all queries use the Django
  ORM or parameters). A later step: run platform jobs with a separate database role that has
  `BYPASSRLS`, and remove the bypass setting from the app role's reach.
- **Watermarks and the missing download button do not stop screenshots.** Studios are told this.
- **The Windows copy script** has been checked as text and against injection, but has not yet been
  run on a studio PC. Do that before launch.
- **Clients' gallery passwords travel by email.** This is the plan's design; studios can also send
  them by WhatsApp and reset them at any time.

## Before going live

- [ ] Set `NUM_PROXIES` to the hosting platform's proxy depth (usually 1) and confirm the logged client IPs are real.
- [ ] Browse the app on staging with the browser console open; if the Content-Security-Policy reports nothing important, set `CSP_ENFORCE=true`.
- [ ] Add the R2 lifecycle rule that deletes `incoming/` objects after 1 day.
- [ ] Turn on the platform admin's authenticator code: `python manage.py setup_admin_2fa <email>`.
- [ ] Run a restore drill against the staging database (see `docs/runbook.md`).

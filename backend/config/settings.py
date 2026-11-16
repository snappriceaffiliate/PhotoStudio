"""Django settings. Every environment-specific value comes from environment variables.

See docs/deployment.md for the full list and what each environment needs.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes"}


def env_list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
_DEV_SECRET_KEY = "dev-only-insecure-key-change-me"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _DEV_SECRET_KEY)
if not DEBUG and SECRET_KEY in ("", _DEV_SECRET_KEY):
    # A public key would let anyone forge sessions and password-reset links.
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a long random value.")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173")

# Public address of the app, used in links inside emails.
APP_URL = os.environ.get("APP_URL", "http://localhost:5173").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "procrastinate.contrib.django",
    "apps.core",
    "apps.studios",
    "apps.accounts",
    "apps.events",
    "apps.photos",
    "apps.clients",
    "apps.audit",
    "apps.billing",
    "apps.notifications",
    "apps.spikes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.core.tenancy.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.security.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# The app must connect as a PostgreSQL role that is NOT a superuser, or row-level
# security is silently skipped. See apps/core/tenancy.py.
DATABASES = {
    "default": dj_database_url.config(
        default="postgres://photo_app:photo_app@localhost:5433/photo", conn_max_age=60
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Shared by every web container: used for rate limits. Table created by a migration.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Password reset and staff invitation links stay valid for 3 days.
PASSWORD_RESET_TIMEOUT = 3 * 24 * 60 * 60
EMAIL_VERIFICATION_MAX_AGE = 3 * 24 * 60 * 60

SESSION_COOKIE_AGE = 30 * 24 * 60 * 60  # 30 days, renewed on use
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Production hardening. The app runs behind the hosting platform's HTTPS proxy.
SECURE = not DEBUG
# Cookies are HTTPS-only outside DEBUG. DJANGO_SECURE_COOKIES=false exists only for local
# load tests over plain HTTP; never set it on a real server.
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", SECURE)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", SECURE)
SECURE_REDIRECT_EXEMPT = [r"^api/health$"]
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0" if DEBUG else "3600"))
# Turn these on once every subdomain of the product domain is served over HTTPS.
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
# Content-Security-Policy starts report-only; see apps/core/security.py.
CSP_ENFORCE = env_bool("CSP_ENFORCE", False)
# Platform admin: password plus an authenticator-app code (django-otp).
OTP_TOTP_ISSUER = "PickSnap admin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# In the production image the built React app is copied here and collected as static files.
FRONTEND_DIST = BASE_DIR / "frontend_dist"
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []
# The copy tool (a separate small app) is built into the production image and served at /copy/.
COPY_TOOL_DIST = BASE_DIR / "copy_tool_dist"
if COPY_TOOL_DIST.exists():
    WHITENOISE_ROOT = COPY_TOOL_DIST
    WHITENOISE_INDEX_FILE = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # Per account (any IP) and per IP (any account). THROTTLE_SCALE multiplies every
    # limit, for load tests only.
    "DEFAULT_THROTTLE_RATES": {
        scope: f"{int(count) * int(os.environ.get('THROTTLE_SCALE', '1'))}/{period}"
        for scope, (count, period) in {
            "login_account": (20, "hour"),
            "login_ip": (30, "min"),
            "client_login_account": (30, "hour"),
            "client_login_ip": (30, "min"),
            "signup_ip": (10, "hour"),
            "password_reset_account": (5, "hour"),
            "password_reset_ip": (20, "hour"),
        }.items()
    },
    # Hosting platforms add one proxy hop; the client IP is the last X-Forwarded-For entry.
    # A value the client sends itself is ignored. Set to the real number of proxies.
    "NUM_PROXIES": int(os.environ.get("NUM_PROXIES", "1")),
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

# Email: Mailpit locally, a transactional email service over SMTP in staging and production.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "PickSnap <noreply@localhost>")

# Object storage: SeaweedFS locally, Cloudflare R2 in staging and production.
# The internal endpoint is used by the server; the public endpoint is the host
# the browser talks to, so signed URLs are signed for that host.
S3_ENDPOINT_INTERNAL = os.environ.get("S3_ENDPOINT_INTERNAL", "http://localhost:8333")
S3_ENDPOINT_PUBLIC = os.environ.get("S3_ENDPOINT_PUBLIC", S3_ENDPOINT_INTERNAL)
S3_BUCKET = os.environ.get("S3_BUCKET", "photos-dev")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "devkey")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "devsecret")
S3_REGION = os.environ.get("S3_REGION", "auto")

# Every stored preview and thumbnail must be at most 100 KB.
MAX_IMAGE_BYTES = 100 * 1024
SIGNED_URL_SECONDS = 15 * 60
# Upper bound on photos in one event, until plan limits arrive with billing (Sprint 4).
MAX_PHOTOS_PER_EVENT = int(os.environ.get("MAX_PHOTOS_PER_EVENT", "15000"))
# Photos left PENDING longer than this (abandoned uploads) are cleaned up by a nightly job.
STALE_UPLOAD_HOURS = 48
# Images of archived events are deleted after this many days; the selection list is kept.
ARCHIVE_RETENTION_DAYS = int(os.environ.get("ARCHIVE_RETENTION_DAYS", "90"))

# Billing (Razorpay). Without keys the app runs: studios stay on their trial and the
# billing screen says payments are not set up yet.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "30"))

# Sharing galleries with clients. Until an email service is set up, studios share by WhatsApp
# only and do not have to confirm their own email first. Turn both on once email works.
CLIENT_EMAIL_SHARING = env_bool("CLIENT_EMAIL_SHARING", False)
REQUIRE_VERIFIED_EMAIL_TO_SHARE = env_bool("REQUIRE_VERIFIED_EMAIL_TO_SHARE", False)
# After a payment problem or the end of a paid period, studios keep working this long.
BILLING_GRACE_DAYS = 7

# Sprint 0 spike endpoints. Never enable in production.
SPIKES_ENABLED = env_bool("SPIKES_ENABLED", False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# Error tracking: set SENTRY_DSN in staging and production.
if os.environ.get("SENTRY_DSN"):
    import sentry_sdk

    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
        send_default_pii=False,
    )

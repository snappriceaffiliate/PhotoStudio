import pytest
from django.core.cache import cache
from django.db import connection

from apps.accounts.models import User
from apps.core import tenancy
from apps.studios.models import Studio

PASSWORD = "a-strong-test-pass-91"


@pytest.fixture(autouse=True)
def _plain_http(settings):
    """The test client speaks plain HTTP. Outside DEBUG (as in CI) the production
    setting would redirect every request to HTTPS, so switch it off for tests."""
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture(autouse=True)
def _clean_state(request):
    """Reset rate-limit counters and tenant settings so tests never leak into each other."""
    yield
    if "django_db" in request.keywords or "db" in request.fixturenames:
        cache.clear()
        tenancy.clear()


@pytest.fixture
def make_studio(db):
    def _make(slug: str, owner_email: str | None = None):
        with tenancy.bypass_rls():
            studio = Studio.objects.create(name=slug.title(), slug=slug)
            owner = User.objects.create_user(
                email=owner_email or f"owner@{slug}.test",
                password=PASSWORD,
                full_name=f"Owner {slug}",
                studio=studio,
                role=User.Role.OWNER,
            )
        return studio, owner

    return _make


@pytest.fixture
def api(client):
    """Django test client with JSON defaults and CSRF checks on, like the real browser."""
    from django.test import Client

    c = Client(enforce_csrf_checks=True)

    def request(method: str, path: str, data=None):
        c.get("/api/v1/auth/csrf")
        token = c.cookies["csrftoken"].value
        return getattr(c, method)(
            path, data, content_type="application/json", HTTP_X_CSRFTOKEN=token
        )

    c.json = request
    return c


def is_superuser_connection() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        return cursor.fetchone()[0]

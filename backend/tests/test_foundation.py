import importlib

import pytest

from apps.core.models import TenantQuerySet
from apps.studios.models import Studio


@pytest.mark.django_db
def test_health_reports_database_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_studio_gets_uuid_primary_key():
    studio = Studio.objects.create(name="Lens and Light", slug="lens-and-light")
    assert len(str(studio.pk)) == 36


def test_tenant_queryset_refuses_missing_studio():
    with pytest.raises(ValueError):
        TenantQuerySet(model=Studio).for_studio(None)


def test_spike_routes_only_exist_when_enabled(settings):
    import config.urls

    try:
        settings.SPIKES_ENABLED = False
        routes = [str(p.pattern) for p in importlib.reload(config.urls).urlpatterns]
        assert not any("spike" in r for r in routes)
        settings.SPIKES_ENABLED = True
        routes = [str(p.pattern) for p in importlib.reload(config.urls).urlpatterns]
        assert any("spike" in r for r in routes)
    finally:
        importlib.reload(config.urls)


@pytest.mark.django_db  # the tenant middleware touches the database on every request
class TestStorageSpike:
    @pytest.fixture(autouse=True)
    def spike_urls(self, settings):
        settings.ROOT_URLCONF = "tests.urls_with_spikes"

    def test_upload_url_refuses_images_over_100_kb(self, client):
        response = client.post(
            "/api/v1/spike/upload-url",
            {"filename": "a.webp", "content_type": "image/webp", "size": 100 * 1024 + 1},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "limit" in str(response.json()["size"])

    def test_upload_url_signs_a_put_for_a_safe_key(self, client):
        response = client.post(
            "/api/v1/spike/upload-url",
            {"filename": "DSC 0001 (2).webp", "content_type": "image/webp", "size": 80_000},
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["key"].startswith("spike/")
        assert body["key"].endswith("/DSC_0001_2_.webp")
        assert "X-Amz-Signature=" in body["upload_url"]

    def test_upload_url_refuses_other_file_types(self, client):
        response = client.post(
            "/api/v1/spike/upload-url",
            {"filename": "a.cr2", "content_type": "image/x-canon-cr2", "size": 10},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_confirm_refuses_keys_outside_the_spike_prefix(self, client):
        response = client.post(
            "/api/v1/spike/confirm", {"key": "../other/secret"}, content_type="application/json"
        )
        assert response.status_code == 400


@pytest.mark.django_db
def test_copy_without_a_slash_goes_to_the_copy_tool(client):
    response = client.get("/copy?event=abc")
    assert response.status_code == 302
    assert response["Location"] == "/copy/?event=abc"


@pytest.mark.django_db
def test_a_missing_copy_tool_file_is_a_404_not_the_studio_app(client):
    assert client.get("/copy/assets/nothing.js").status_code == 404

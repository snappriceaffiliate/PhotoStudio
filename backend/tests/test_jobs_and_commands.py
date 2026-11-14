"""Background jobs, the health check, storage helpers and the management commands."""

import io
from datetime import timedelta

import pytest
from botocore.exceptions import ClientError
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import Http404
from django.test import RequestFactory
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User
from apps.billing import razorpay
from apps.billing.models import Plan
from apps.core import storage, tenancy
from apps.core import tasks as core_tasks
from apps.core import views as core_views
from apps.core.management.commands import check_storage as check_cmd
from apps.core.management.commands import ensure_bucket as ensure_cmd
from apps.events.models import Event
from apps.notifications import tasks as mail_tasks
from apps.photos import tasks
from apps.photos.models import Photo
from apps.studios.models import Studio

from .test_clients import make_event

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------------ nightly jobs


def add_photo(studio, event, name, status):
    return Photo.objects.create(
        studio=studio,
        event=event,
        relative_path=name,
        original_filename=name,
        status=status,
        preview_key=f"k/{name}/p.webp",
        thumb_key=f"k/{name}/t.webp",
    )


def test_cleanup_removes_only_old_unfinished_uploads(make_studio, monkeypatch):
    studio, _ = make_studio("alpha")
    event = make_event(studio, photos=1)  # one finished photo that must stay
    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", deleted.append)
    with tenancy.bypass_rls():
        stale_pending = add_photo(studio, event, "a.jpg", Photo.Status.PENDING)
        stale_failed = add_photo(studio, event, "b.jpg", Photo.Status.FAILED)
        add_photo(studio, event, "c.jpg", Photo.Status.PENDING)  # still being uploaded
        Photo.objects.filter(pk__in=[stale_pending.pk, stale_failed.pk]).update(
            updated_at=timezone.now() - timedelta(hours=49)
        )

        assert tasks.cleanup_stale_uploads(timestamp=0) == 2

        left = set(Photo.objects.filter(event=event).values_list("relative_path", flat=True))
    assert "a.jpg" not in left and "b.jpg" not in left and "c.jpg" in left and len(left) == 2
    assert sorted(deleted) == [
        "k/a.jpg/p.webp",
        "k/a.jpg/t.webp",
        "k/b.jpg/p.webp",
        "k/b.jpg/t.webp",
    ]


def test_cleanup_runs_cleanly_with_nothing_to_do(db):
    assert tasks.cleanup_stale_uploads(timestamp=0) == 0


def test_recently_archived_events_keep_their_images(make_studio, monkeypatch):
    studio, _ = make_studio("alpha")
    event = make_event(studio, photos=2)
    monkeypatch.setattr(storage, "delete_object", lambda key: pytest.fail("must keep images"))
    with tenancy.bypass_rls():
        Event.objects.filter(pk=event.pk).update(
            status=Event.Status.ARCHIVED, archived_at=timezone.now() - timedelta(days=10)
        )
        assert tasks.remove_archived_images(timestamp=0) == 0
        assert Photo.objects.filter(event=event, status=Photo.Status.READY).count() == 2


def test_ping_task_echoes_its_message():
    assert core_tasks.ping() == "pong"
    assert core_tasks.ping("hello") == "hello"


def test_email_task_sends_one_plain_text_message():
    mail_tasks.send_email("a@example.com", "Subject", "Body text")
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert (sent.to, sent.subject, sent.body) == (["a@example.com"], "Subject", "Body text")


# ------------------------------------------------------------------ health and app shell


def test_health_reports_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_a_database_failure_as_503(client, monkeypatch):
    class Broken:
        def cursor(self):
            raise RuntimeError("database is down")

    monkeypatch.setattr(core_views, "connection", Broken())
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error"}


def test_app_shell_is_served_from_the_build_folder(settings, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>PickSnap</title>")
    settings.FRONTEND_DIST = tmp_path
    response = core_views.spa(RequestFactory().get("/events"))
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-cache"
    assert b"PickSnap" in b"".join(response.streaming_content)


def test_app_shell_is_a_404_when_the_app_was_not_built(settings, tmp_path):
    settings.FRONTEND_DIST = tmp_path
    with pytest.raises(Http404):
        core_views.spa(RequestFactory().get("/events"))


# ------------------------------------------------------------------ storage helpers


def missing(operation="HeadObject"):
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, operation)


class FakeClient:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def head_object(self, **kw):
        if self.fail:
            raise missing()
        return {"ContentLength": 4321}

    def get_object(self, **kw):
        if self.fail:
            raise missing("GetObject")
        return {"Body": io.BytesIO(b"RIFF....WEBP")}

    def put_object(self, **kw):
        self.calls.append(("put", kw))

    def copy_object(self, **kw):
        self.calls.append(("copy", kw))

    def delete_object(self, **kw):
        self.calls.append(("delete", kw))


def test_webp_detection_needs_the_riff_and_webp_markers():
    assert storage.is_webp(b"RIFF\x10\x00\x00\x00WEBPVP8 ")
    assert not storage.is_webp(b"RIFF\x10\x00\x00\x00WAVEfmt ")
    assert not storage.is_webp(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00")
    assert not storage.is_webp(b"RIFF")
    assert not storage.is_webp(b"")


def test_signed_links_name_the_key_and_carry_a_signature():
    for url in (
        storage.signed_download_url("studios/s1/logo/x.webp"),
        storage.signed_upload_url("incoming/e1/n1/p.webp", "image/webp"),
    ):
        assert "X-Amz-Signature=" in url and "X-Amz-Expires=" in url
    assert "studios/s1/logo/x.webp" in storage.signed_download_url("studios/s1/logo/x.webp")


def test_object_size_and_prefix_for_missing_objects(monkeypatch):
    monkeypatch.setattr(storage, "internal_client", lambda: FakeClient(fail=True))
    assert storage.object_size("nope") is None
    assert storage.read_prefix("nope") == b""


def test_object_size_and_prefix_for_stored_objects(monkeypatch):
    monkeypatch.setattr(storage, "internal_client", lambda: FakeClient())
    assert storage.object_size("k") == 4321
    assert storage.read_prefix("k") == b"RIFF....WEBP"


def test_put_copy_and_delete_use_the_configured_bucket(monkeypatch, settings):
    client = FakeClient()
    monkeypatch.setattr(storage, "internal_client", lambda: client)
    storage.put_object("a", b"data", "image/webp")
    storage.copy_object("incoming/a", "final/a")
    storage.delete_object("a")
    assert [name for name, _ in client.calls] == ["put", "copy", "delete"]
    assert all(kw["Bucket"] == settings.S3_BUCKET for _, kw in client.calls)
    assert client.calls[1][1]["CopySource"]["Key"] == "incoming/a"
    assert client.calls[1][1]["ContentType"] == "image/webp"


# ------------------------------------------------------------------ management commands


class TestSyncRazorpayPlans:
    def test_needs_keys(self, settings):
        settings.RAZORPAY_KEY_ID = settings.RAZORPAY_KEY_SECRET = ""
        with pytest.raises(CommandError, match="RAZORPAY_KEY_ID"):
            call_command("sync_razorpay_plans")

    def test_creates_plans_once_and_leaves_existing_ones(self, settings, monkeypatch):
        settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = "rzp_test_1", "secret"
        created = []
        monkeypatch.setattr(
            razorpay,
            "create_plan",
            lambda name, amount: created.append((name, amount)) or f"plan_{len(created)}",
        )
        with tenancy.bypass_rls():
            Plan.objects.update(razorpay_plan_id="")
            Plan.objects.filter(code="studio").update(razorpay_plan_id="plan_keep")
            public = Plan.objects.filter(is_public=True).count()

            call_command("sync_razorpay_plans", stdout=io.StringIO())
            assert len(created) == public - 1
            assert Plan.objects.get(code="studio").razorpay_plan_id == "plan_keep"
            assert not Plan.objects.filter(is_public=True, razorpay_plan_id="").exists()

            call_command("sync_razorpay_plans", stdout=io.StringIO())
        assert len(created) == public - 1  # a second run creates nothing


class TestSetupAdmin2fa:
    @pytest.fixture
    def platform_admin(self):
        with tenancy.bypass_rls():
            return User.objects.create_superuser(
                email="admin@platform.test", password="x-strong-pass-91", full_name="Admin"
            )

    def test_unknown_email_is_refused(self):
        with pytest.raises(CommandError, match="No platform admin"):
            call_command("setup_admin_2fa", "nobody@platform.test")

    def test_studio_owners_cannot_get_admin_codes(self, make_studio):
        _, owner = make_studio("alpha")
        with pytest.raises(CommandError, match="No platform admin"):
            call_command("setup_admin_2fa", owner.email)

    def test_creates_a_confirmed_code_and_replaces_it_when_run_again(self, platform_admin):
        out = io.StringIO()
        call_command("setup_admin_2fa", " ADMIN@platform.test ", stdout=out)
        first = TOTPDevice.objects.get(user=platform_admin)
        assert first.confirmed and "otpauth://totp/" in out.getvalue()
        assert "Two-step login is on" in out.getvalue()

        call_command("setup_admin_2fa", "admin@platform.test", stdout=io.StringIO())
        second = TOTPDevice.objects.get(user=platform_admin)  # exactly one device remains
        assert second.key != first.key


class TestSeedDemo:
    def test_refuses_outside_debug_without_the_flag(self, monkeypatch):
        monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)
        with pytest.raises(CommandError, match="Refusing to seed"):
            call_command("seed_demo")
        assert not Studio.objects.filter(slug="lens-and-light").exists()

    def test_creates_the_demo_studios_once(self, monkeypatch):
        monkeypatch.setenv("ALLOW_DEMO_SEED", "true")
        monkeypatch.setenv("DEMO_PASSWORD", "demo-test-pass-5150")
        for _ in range(2):  # running again must not duplicate anything
            call_command("seed_demo", stdout=io.StringIO())
        with tenancy.bypass_rls():
            assert Studio.objects.filter(slug__in=["lens-and-light", "golden-hour"]).count() == 2
            assert Event.objects.filter(studio__slug="lens-and-light").count() == 2
            owner = User.objects.get(email="owner@lensandlight.test")
            assert owner.check_password("demo-test-pass-5150") and owner.email_verified
            assert User.objects.filter(email="admin@platform.test", is_superuser=True).count() == 1


class TestEnsureBucket:
    def test_leaves_an_existing_bucket_alone(self, monkeypatch):
        client = type("C", (), {"head_bucket": lambda s, **k: {}})()
        monkeypatch.setattr(ensure_cmd, "internal_client", lambda: client)
        out = io.StringIO()
        call_command("ensure_bucket", stdout=out)
        assert "exists" in out.getvalue()

    def test_creates_a_missing_bucket(self, monkeypatch, settings):
        created = []

        class C:
            def head_bucket(self, **kw):
                raise missing()

            def create_bucket(self, **kw):
                created.append(kw["Bucket"])

        monkeypatch.setattr(ensure_cmd, "internal_client", lambda: C())
        call_command("ensure_bucket", stdout=io.StringIO())
        assert created == [settings.S3_BUCKET]


# ------------------------------------------------------------------ check_storage


class FakeS3:
    def __init__(self, lifecycle=True, reject_keys=False):
        self.objects, self.lifecycle, self.reject_keys = {}, lifecycle, reject_keys

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.reject_keys:
            raise ClientError({"Error": {"Code": "SignatureDoesNotMatch"}}, "PutObject")
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://r2.test/{Params['Key']}?X-Amz-Signature=1"

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def get_bucket_lifecycle_configuration(self, Bucket):
        if not self.lifecycle:
            raise ClientError({"Error": {"Code": "NoSuchLifecycleConfiguration"}}, "Get")
        return {
            "Rules": [
                {"Status": "Enabled", "Filter": {"Prefix": "incoming/"}, "Expiration": {"Days": 1}}
            ]
        }


def web(cors=True, private=True):
    def http(method, url, headers=None, data=None):
        if method == "GET":
            if "?" in url or not private:
                return 200, {}, check_cmd.WEBP_TEST
            return 403, {}, b""
        if method == "PUT":
            return 200, {}, b""
        if cors:
            return 204, {"Access-Control-Allow-Origin": headers["Origin"]}, b""
        return 403, {}, b""

    return http


@pytest.fixture
def run_check(monkeypatch):
    def run(fake, http, origins=("https://app.example.com",), key="a" * 32, secret="b" * 64):
        monkeypatch.setattr(check_cmd.boto3, "client", lambda *a, **k: fake)
        monkeypatch.setattr(check_cmd, "_http", http)
        monkeypatch.setattr("builtins.input", lambda prompt="": key)
        monkeypatch.setattr(check_cmd.getpass, "getpass", lambda prompt="": secret)
        out = io.StringIO()
        try:
            call_command(
                "check_storage",
                endpoint="https://acct.r2.test",
                bucket="b1",
                origin=list(origins),
                stdout=out,
            )
        finally:
            run.output = out.getvalue()

    return run


class TestCheckStorage:
    def test_a_good_bucket_passes_and_leaves_nothing_behind(self, run_check):
        fake = FakeS3()
        run_check(fake, web())
        assert "Storage is ready for the app" in run_check.output
        assert "FAIL" not in run_check.output
        assert fake.objects == {}  # the test objects were deleted

    def test_missing_cors_fails(self, run_check):
        with pytest.raises(CommandError, match="1 check"):
            run_check(FakeS3(), web(cors=False))
        assert "FAIL  Browsers at https://app.example.com" in run_check.output

    def test_a_public_bucket_fails(self, run_check):
        with pytest.raises(CommandError):
            run_check(FakeS3(), web(private=False))
        assert "FAIL  Bucket is private" in run_check.output

    def test_missing_cleanup_rule_fails(self, run_check):
        with pytest.raises(CommandError):
            run_check(FakeS3(lifecycle=False), web())
        assert "FAIL  Cleanup rule" in run_check.output

    def test_without_an_origin_cors_is_skipped_with_a_note(self, run_check):
        run_check(FakeS3(), web(), origins=())
        assert "CORS not checked" in run_check.output

    def test_wrong_credentials_stop_the_check_early(self, run_check):
        with pytest.raises(CommandError, match="key, secret, endpoint or bucket"):
            run_check(FakeS3(reject_keys=True), web())
        assert "FAIL  Server can write and read" in run_check.output

    def test_key_lengths_are_checked_before_anything_is_sent(self, run_check):
        with pytest.raises(CommandError, match="32 characters"):
            run_check(FakeS3(), web(), key="short")
        with pytest.raises(CommandError, match="64 characters"):
            run_check(FakeS3(), web(), secret="short")

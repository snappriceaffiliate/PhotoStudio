"""The small Razorpay client: what it sends, how it reports failures, and signature checks."""

import base64
import hashlib
import hmac
import io
import json
import urllib.error

import pytest

from apps.billing import razorpay

KEY_ID, KEY_SECRET, WEBHOOK_SECRET = "rzp_test_abc", "key-secret", "webhook-secret"


@pytest.fixture
def keys(settings):
    settings.RAZORPAY_KEY_ID = KEY_ID
    settings.RAZORPAY_KEY_SECRET = KEY_SECRET
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET


class Reply:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


@pytest.fixture
def sent(keys, monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        return Reply({"id": "id_1", "status": "created"})

    monkeypatch.setattr(razorpay.urllib.request, "urlopen", fake_urlopen)
    return requests


def body_of(request) -> dict:
    return json.loads(request.data)


def test_nothing_is_sent_until_keys_are_set(settings, monkeypatch):
    settings.RAZORPAY_KEY_ID = settings.RAZORPAY_KEY_SECRET = ""
    monkeypatch.setattr(
        razorpay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not call Razorpay")
    )
    assert razorpay.configured() is False
    with pytest.raises(razorpay.RazorpayError, match="not set up"):
        razorpay.create_plan("Studio", 249900)


def test_requests_use_basic_auth_and_the_documented_address(sent):
    razorpay.fetch_subscription("sub_1")
    request = sent[0]
    token = base64.b64encode(f"{KEY_ID}:{KEY_SECRET}".encode()).decode()
    assert request.full_url == "https://api.razorpay.com/v1/subscriptions/sub_1"
    assert request.get_method() == "GET" and request.data is None
    assert request.get_header("Authorization") == f"Basic {token}"


def test_create_plan_is_monthly_in_rupees_and_returns_the_id(sent):
    assert razorpay.create_plan("Studio", 249900) == "id_1"
    assert sent[0].full_url.endswith("/plans") and sent[0].get_method() == "POST"
    assert body_of(sent[0]) == {
        "period": "monthly",
        "interval": 1,
        "item": {"name": "Studio", "amount": 249900, "currency": "INR"},
    }


def test_create_subscription_carries_the_studio_in_notes(sent):
    razorpay.create_subscription("plan_1", notes={"studio_id": "s1", "plan": "studio"})
    body = body_of(sent[0])
    assert body["plan_id"] == "plan_1" and body["total_count"] == razorpay.MONTHLY_TOTAL_COUNT
    assert body["notes"] == {"studio_id": "s1", "plan": "studio"}


def test_cancel_stops_at_cycle_end_by_default(sent):
    razorpay.cancel_subscription("sub_1")
    assert sent[0].full_url.endswith("/subscriptions/sub_1/cancel")
    assert body_of(sent[0]) == {"cancel_at_cycle_end": True}


def test_razorpay_error_text_is_passed_on(keys, monkeypatch):
    def refuse(request, timeout):
        body = io.BytesIO(json.dumps({"error": {"description": "Plan is inactive"}}).encode())
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, body)

    monkeypatch.setattr(razorpay.urllib.request, "urlopen", refuse)
    with pytest.raises(razorpay.RazorpayError, match="Plan is inactive"):
        razorpay.fetch_subscription("sub_1")


def test_unreadable_error_falls_back_to_the_status_code(keys, monkeypatch):
    def fail(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 502, "Bad Gateway", {}, io.BytesIO(b"<html>")
        )

    monkeypatch.setattr(razorpay.urllib.request, "urlopen", fail)
    with pytest.raises(razorpay.RazorpayError, match="returned 502"):
        razorpay.fetch_subscription("sub_1")


def test_network_failure_gives_a_friendly_message(keys, monkeypatch):
    def down(request, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(razorpay.urllib.request, "urlopen", down)
    with pytest.raises(razorpay.RazorpayError, match="Could not reach Razorpay"):
        razorpay.fetch_subscription("sub_1")


def hex_hmac(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def test_payment_signature_must_match_payment_and_subscription(keys):
    good = hex_hmac(KEY_SECRET, b"pay_1|sub_1")
    assert razorpay.payment_signature_valid("pay_1", "sub_1", good)
    assert not razorpay.payment_signature_valid("pay_2", "sub_1", good)
    assert not razorpay.payment_signature_valid("pay_1", "sub_2", good)
    assert not razorpay.payment_signature_valid("pay_1", "sub_1", "")
    assert not razorpay.payment_signature_valid("pay_1", "sub_1", None)


def test_webhook_signature_covers_the_raw_body(keys):
    body = b'{"event": "subscription.charged"}'
    good = hex_hmac(WEBHOOK_SECRET, body)
    assert razorpay.webhook_signature_valid(body, good)
    assert not razorpay.webhook_signature_valid(body + b" ", good)
    assert not razorpay.webhook_signature_valid(body, hex_hmac("other", body))
    assert not razorpay.webhook_signature_valid(body, "")


def test_signatures_are_refused_when_secrets_are_missing(settings):
    settings.RAZORPAY_KEY_SECRET = settings.RAZORPAY_WEBHOOK_SECRET = ""
    # An empty secret must never turn into a signature anyone could compute.
    forged = hex_hmac("", b"pay_1|sub_1")
    assert not razorpay.payment_signature_valid("pay_1", "sub_1", forged)
    assert not razorpay.webhook_signature_valid(b"{}", hex_hmac("", b"{}"))

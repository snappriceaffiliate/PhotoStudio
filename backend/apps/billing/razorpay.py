"""Minimal Razorpay REST client for Subscriptions (https://razorpay.com/docs/api/payments/subscriptions/).

Verified against Razorpay's docs on 2026-11-14:
- Basic auth with key_id:key_secret, base URL https://api.razorpay.com/v1.
- Checkout signature for subscriptions: HMAC-SHA256 hex of "<payment_id>|<subscription_id>"
  with the key secret, using the subscription ID stored on our side.
- Webhook signature: HMAC-SHA256 hex of the raw body with the webhook secret, sent in the
  X-Razorpay-Signature header; X-Razorpay-Event-Id identifies each event for de-duplication.
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from django.conf import settings

# Razorpay charges a subscription for at most 10 years; monthly plans therefore use 120.
MONTHLY_TOTAL_COUNT = 120


class RazorpayError(Exception):
    pass


def configured() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _request(method: str, path: str, body: dict | None = None) -> dict:
    if not configured():
        raise RazorpayError("Payments are not set up yet.")
    token = base64.b64encode(
        f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()
    ).decode()
    request = urllib.request.Request(
        f"{settings.RAZORPAY_API_BASE}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read())["error"]["description"]
        except Exception:  # noqa: BLE001 - fall back to the status code
            detail = f"Razorpay returned {exc.code}"
        raise RazorpayError(detail) from exc
    except urllib.error.URLError as exc:
        raise RazorpayError("Could not reach Razorpay. Try again in a minute.") from exc


def create_plan(name: str, amount_paise: int) -> str:
    plan = _request(
        "POST",
        "/plans",
        {
            "period": "monthly",
            "interval": 1,
            "item": {"name": name, "amount": amount_paise, "currency": "INR"},
        },
    )
    return plan["id"]


def create_subscription(plan_id: str, notes: dict) -> dict:
    return _request(
        "POST",
        "/subscriptions",
        {
            "plan_id": plan_id,
            "total_count": MONTHLY_TOTAL_COUNT,
            "customer_notify": True,
            "notes": notes,
        },
    )


def fetch_subscription(subscription_id: str) -> dict:
    return _request("GET", f"/subscriptions/{subscription_id}")


def cancel_subscription(subscription_id: str, at_cycle_end: bool = True) -> dict:
    return _request(
        "POST", f"/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": at_cycle_end}
    )


def _hmac(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def payment_signature_valid(payment_id: str, subscription_id: str, signature: str) -> bool:
    if not settings.RAZORPAY_KEY_SECRET:
        return False
    expected = _hmac(settings.RAZORPAY_KEY_SECRET, f"{payment_id}|{subscription_id}".encode())
    return hmac.compare_digest(expected, signature or "")


def webhook_signature_valid(raw_body: bytes, signature: str) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    return hmac.compare_digest(_hmac(settings.RAZORPAY_WEBHOOK_SECRET, raw_body), signature or "")

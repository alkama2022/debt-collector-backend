"""Paystack helper — real when PAYSTACK_SECRET_KEY set, mock otherwise."""
import requests
from django.conf import settings
from decimal import Decimal

PAYSTACK_BASE = "https://api.paystack.co"

def _headers():
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def initialize_payment(email: str, amount_minor: int, reference: str, metadata: dict, callback_url: str = ""):
    """Initialize Paystack transaction. Returns {authorization_url, access_code, reference} or mock."""
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not key:
        # Mock mode — return frontend pay URL as authorization
        return {
            "authorization_url": f"{metadata.get('pay_url', '')}#{reference}",
            "access_code": f"mock_{reference}",
            "reference": reference,
            "mock": True,
        }
    payload = {
        "email": email or "customer@collectnaija.mock",
        "amount": amount_minor,
        "reference": reference,
        "metadata": metadata,
    }
    if callback_url:
        payload["callback_url"] = callback_url
    resp = requests.post(f"{PAYSTACK_BASE}/transaction/initialize", json=payload, headers=_headers(), timeout=15)
    data = resp.json()
    if not resp.ok or not data.get("status"):
        raise ValueError(f"Paystack init failed: {data}")
    return data["data"]

def verify_payment(reference: str):
    """Verify transaction with Paystack. Returns {status, amount, reference, paid_at} or mock pending."""
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not key:
        # In mock mode, caller decides — we return pending so webhook/mock manual can mark successful
        return {"status": "mock", "reference": reference, "amount": 0, "gateway_response": "mock_pending"}
    resp = requests.get(f"{PAYSTACK_BASE}/transaction/verify/{reference}", headers=_headers(), timeout=15)
    data = resp.json()
    if not resp.ok:
        raise ValueError(f"Paystack verify failed: {data}")
    return data["data"]

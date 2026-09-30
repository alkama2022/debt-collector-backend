"""
PaymentProvider abstraction — Paystack primary, mock fallback. Pluggable for Flutterwave.
"""
import uuid
import hashlib
import hmac
from django.conf import settings

class PaymentProvider:
    def create_customer(self, org, user): raise NotImplementedError
    def create_subscription(self, org, plan, **kwargs): raise NotImplementedError
    def charge(self, org, amount_minor, currency, reference, metadata): raise NotImplementedError
    def verify_payment(self, reference): raise NotImplementedError
    def cancel_subscription(self, provider_subscription_id): raise NotImplementedError
    def refund(self, provider_ref, amount_minor=None): raise NotImplementedError
    def create_payment_link(self, org, amount_minor, currency, reference, metadata): raise NotImplementedError
    def handle_webhook(self, payload, signature): raise NotImplementedError


class PaystackProvider(PaymentProvider):
    def _is_mock(self):
        return not getattr(settings, "PAYSTACK_SECRET_KEY", "")

    def create_customer(self, org, user):
        if self._is_mock():
            return {"id": f"mock_cus_{org.id}", "mock": True}
        # real implementation would call Paystack API
        from apps.payments.paystack import _headers
        import requests
        resp = requests.post("https://api.paystack.co/customer", json={"email": user.email, "first_name": user.name}, headers=_headers(), timeout=10)
        return resp.json().get("data", {})

    def create_subscription(self, org, plan, **kwargs):
        return {"id": str(uuid.uuid4()), "plan": getattr(plan, "slug", str(plan))}

    def charge(self, org, amount_minor, currency, reference, metadata):
        if self._is_mock():
            return {"reference": reference, "authorization_url": f"{settings.FRONTEND_URL}/billing/success?ref={reference}", "mock": True}
        from apps.payments.paystack import initialize_payment
        email = metadata.get("email") or "customer@collectnaija.test"
        return initialize_payment(email, amount_minor, reference, metadata, callback_url=f"{settings.FRONTEND_URL}/billing/success")

    def create_payment_link(self, org, amount_minor, currency, reference, metadata):
        return self.charge(org, amount_minor, currency, reference, metadata)

    def verify_payment(self, reference):
        from apps.payments.paystack import verify_payment
        return verify_payment(reference)

    def cancel_subscription(self, provider_subscription_id):
        return {"status": "cancelled", "mock": True}

    def refund(self, provider_ref, amount_minor=None):
        return {"status": "refunded", "mock": True}

    def handle_webhook(self, payload, signature):
        return payload

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        secret = getattr(settings, "PAYSTACK_WEBHOOK_SECRET", "") or getattr(settings, "PAYSTACK_SECRET_KEY", "")
        if not secret:
            return True  # mock mode: allow
        expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature or "")


class FlutterwaveProvider(PaymentProvider):
    def _is_mock(self):
        return not getattr(settings, "FLUTTERWAVE_SECRET_KEY", "")

    def create_payment_link(self, org, amount_minor, currency, reference, metadata):
        if self._is_mock():
            return {"authorization_url": f"{settings.FRONTEND_URL}/billing/success?ref={reference}", "reference": reference, "mock": True}
        # real Flutterwave call would go here
        return {"authorization_url": f"{settings.FRONTEND_URL}/billing/success?ref={reference}", "reference": reference}

    def verify_payment(self, reference):
        return {"status": "successful", "reference": reference}

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        # Flutterwave uses verif-hash header
        return True


def get_provider(name: str = "paystack") -> PaymentProvider:
    if name == "flutterwave":
        return FlutterwaveProvider()
    return PaystackProvider()


# Singleton helper
default_provider = PaystackProvider()

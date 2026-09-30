from rest_framework import serializers
from .models import Payment, Receipt
from apps.tenancy.org import get_org

# Frontend sends human-readable method names; map them to the provider enum
_METHOD_TO_PROVIDER = {
    "bank transfer":   "manual",
    "bank_transfer":   "manual",
    "cash":            "manual",
    "card":            "manual",
    "pos":             "manual",
    "cheque":          "manual",
    "mobile money":    "manual",
    "mobile_money":    "manual",
    "other":           "manual",
    "online payment":  "manual",
    "online_payment":  "manual",
    "paystack":        "paystack",
    "flutterwave":     "flutterwave",
}


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id", "org", "invoice", "amount", "currency",
            "status", "provider", "method",
            "provider_ref", "idempotency_key",
            "notes", "verified_at", "created_at",
        ]
        read_only_fields = ["id", "org", "verified_at", "created_at"]

    def validate(self, data):
        # Normalise provider: if caller sends a human-readable method string
        # (e.g. "Bank transfer", "Cash") coerce it to provider=manual and
        # store the original string in the `method` field.
        raw_provider = (data.get("provider") or "").strip()
        normalised = _METHOD_TO_PROVIDER.get(raw_provider.lower())
        if normalised:
            if not data.get("method"):
                data["method"] = raw_provider  # preserve original label
            data["provider"] = normalised
        elif raw_provider and raw_provider not in ("paystack", "flutterwave", "manual"):
            # Unknown value: store as method, set provider=manual
            if not data.get("method"):
                data["method"] = raw_provider
            data["provider"] = "manual"
        return data

    def create(self, validated_data):
        request = self.context.get("request")
        org = get_org(request) if request else None
        if org is None and request and hasattr(request, "user") and request.user.is_authenticated:
            m = request.user.memberships.select_related("org").first()
            org = m.org if m else None
        if org is None:
            raise serializers.ValidationError({"org": "Organization context required."})
        validated_data["org"] = org
        if not validated_data.get("idempotency_key") and request:
            hdr = (
                request.headers.get("X-Idempotency-Key")
                or request.headers.get("Idempotency-Key")
            )
            if hdr:
                validated_data["idempotency_key"] = hdr
        return super().create(validated_data)


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = ["id", "org", "payment", "receipt_number", "issued_at", "amount", "currency"]
        read_only_fields = ["id", "issued_at"]

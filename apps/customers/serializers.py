from rest_framework import serializers
from .models import Customer
from apps.tenancy.org import get_org


def _language_qs():
    try:
        from apps.languages.models import Language
        return Language.objects.filter(active=True)
    except Exception:
        from django.db.models import QuerySet as _QS
        # fallback empty qs - will be replaced in __init__
        return Customer.objects.none()


class CustomerSerializer(serializers.ModelSerializer):
    customer_code = serializers.CharField(required=False, allow_blank=True)
    preferred_language = serializers.SlugRelatedField(
        slug_field="code", queryset=_language_qs(), required=False, allow_null=True
    )
    voice_language = serializers.SlugRelatedField(
        slug_field="code", queryset=_language_qs(), required=False, allow_null=True
    )

    class Meta:
        model = Customer
        fields = [
            "id", "org", "customer_code", "name", "phone", "email",
            "outstanding", "overdue", "prefs", "communication_preference", "opt_out",
            "preferred_language", "voice_language", "language_detection_enabled", "language_updated_at",
            "created_at", "deleted_at",
        ]
        read_only_fields = ["id", "org", "outstanding", "overdue", "created_at", "deleted_at", "language_updated_at"]

    def create(self, validated_data):
        request = self.context.get("request")
        org = get_org(request) if request else None
        if org is None and request and hasattr(request, "user") and request.user.is_authenticated:
            m = request.user.memberships.select_related("org").first()
            if m:
                org = m.org
        if org is None:
            raise serializers.ValidationError({"org": "Organization context required. Provide X-Org-Id header."})
        validated_data["org"] = org
        if not validated_data.get("customer_code"):
            import uuid as _uuid
            validated_data["customer_code"] = f"CUS-{str(_uuid.uuid4())[:8].upper()}"
        return super().create(validated_data)

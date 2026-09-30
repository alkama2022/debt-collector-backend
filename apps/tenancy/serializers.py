from rest_framework import serializers
from django.utils.text import slugify
from .models import Organization


def _unique_slug(name: str, exclude_id=None) -> str:
    """Generate a unique slug from a name, appending a counter on collision."""
    base = slugify(name)[:50] or "org"
    slug = base
    counter = 1
    qs = Organization.objects.all()
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


class OrganizationSerializer(serializers.ModelSerializer):
    # slug is auto-generated from name on create; read-only after that
    slug = serializers.SlugField(read_only=True)
    # role of the requesting user in this org (populated by the view)
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "slug", "name", "country", "currency", "timezone", "is_demo", "created_at", "role"]
        read_only_fields = ["id", "slug", "created_at", "is_demo"]

    def get_role(self, obj):
        request = self.context.get("request")
        if request and hasattr(request, "user") and request.user.is_authenticated:
            from .models import Membership
            m = Membership.objects.filter(org=obj, user=request.user).first()
            return m.role if m else None
        return None

    def create(self, validated_data):
        validated_data["slug"] = _unique_slug(validated_data.get("name", "org"))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Re-slug only if name changed and slug wasn't explicitly provided
        if "name" in validated_data and validated_data["name"] != instance.name:
            validated_data.setdefault("slug", _unique_slug(validated_data["name"], exclude_id=instance.pk))
        return super().update(instance, validated_data)

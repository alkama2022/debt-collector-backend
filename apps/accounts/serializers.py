from rest_framework import serializers
from .models import User
from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify
import uuid


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    name = serializers.CharField(required=False, allow_blank=True, default="")
    org_name = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value.lower()

    def create(self, validated_data):
        from apps.tenancy.models import Organization, Membership

        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            name=validated_data.get("name", ""),
        )

        # Create the organization and make the user its owner
        org_name = (validated_data.get("org_name") or "").strip() or user.name or user.email.split("@")[0]
        # Generate a unique slug
        base_slug = slugify(org_name)[:50] or "org"
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization.objects.create(name=org_name, slug=slug)
        Membership.objects.create(org=org, user=user, role=Membership.Role.OWNER)

        return user

class UserSerializer(serializers.ModelSerializer):
    org = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "is_active", "is_staff", "date_joined", "org"]
        read_only_fields = fields

    def get_org(self, obj):
        membership = obj.memberships.select_related("org").filter(
            org__deleted_at__isnull=True
        ).order_by("created_at").first()
        if membership:
            org = membership.org
            return {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "country": org.country,
                "currency": org.currency,
                "timezone": org.timezone,
                "role": membership.role,
            }
        return None

from rest_framework import serializers
from .models import Language, OrganizationLanguageSettings


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = [
            "code",
            "name",
            "native_name",
            "locale",
            "text_supported",
            "speech_to_text_supported",
            "text_to_speech_supported",
            "active",
            "quality_status",
            "version",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class OrganizationLanguageSettingsSerializer(serializers.ModelSerializer):
    # Accept codes on write, return expanded on read
    dashboard_language = serializers.SlugRelatedField(
        slug_field="code", queryset=Language.objects.filter(active=True), required=False
    )
    default_customer_language = serializers.SlugRelatedField(
        slug_field="code", queryset=Language.objects.filter(active=True), required=False
    )
    fallback_language = serializers.SlugRelatedField(
        slug_field="code", queryset=Language.objects.filter(active=True), required=False
    )
    supported_languages = serializers.SlugRelatedField(
        slug_field="code", queryset=Language.objects.filter(active=True), many=True, required=False
    )

    # Read-only expanded
    dashboard_language_detail = LanguageSerializer(source="dashboard_language", read_only=True)
    default_customer_language_detail = LanguageSerializer(source="default_customer_language", read_only=True)
    fallback_language_detail = LanguageSerializer(source="fallback_language", read_only=True)
    supported_languages_detail = LanguageSerializer(source="supported_languages", many=True, read_only=True)

    class Meta:
        model = OrganizationLanguageSettings
        fields = [
            "id",
            "org",
            "dashboard_language",
            "default_customer_language",
            "ai_communication_mode",
            "fallback_language",
            "supported_languages",
            "dashboard_language_detail",
            "default_customer_language_detail",
            "fallback_language_detail",
            "supported_languages_detail",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "org", "created_at", "updated_at"]

    def validate(self, attrs):
        # Ensure fallback is in supported or active registry
        return attrs

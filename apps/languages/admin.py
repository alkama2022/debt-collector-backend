from django.contrib import admin
from .models import Language, OrganizationLanguageSettings, CustomerLanguageHistory


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "native_name", "locale", "active", "quality_status", "version", "text_supported", "speech_to_text_supported", "text_to_speech_supported")
    list_filter = ("active", "quality_status", "text_supported", "speech_to_text_supported", "text_to_speech_supported")
    search_fields = ("code", "name", "native_name", "locale")
    ordering = ("code",)


@admin.register(OrganizationLanguageSettings)
class OrganizationLanguageSettingsAdmin(admin.ModelAdmin):
    list_display = ("org", "dashboard_language", "default_customer_language", "fallback_language", "ai_communication_mode")
    list_filter = ("ai_communication_mode",)
    filter_horizontal = ("supported_languages",)


@admin.register(CustomerLanguageHistory)
class CustomerLanguageHistoryAdmin(admin.ModelAdmin):
    list_display = ("org", "customer", "from_lang", "to_lang", "reason", "detected_confidence", "changed_by", "created_at")
    list_filter = ("reason",)
    search_fields = ("customer__name", "customer__customer_code")
    readonly_fields = ("created_at",)

from django.contrib import admin
from .models import CommunicationEvent, CommunicationPreference

@admin.register(CommunicationEvent)
class CommunicationEventAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "status", "customer", "invoice", "org", "scheduled_for", "created_at")
    list_filter = ("channel", "status")
    search_fields = ("template_id", "provider_msg_id")

@admin.register(CommunicationPreference)
class CommunicationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("customer", "channel", "enabled", "org")
    list_filter = ("channel", "enabled")

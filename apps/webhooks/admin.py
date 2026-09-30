from django.contrib import admin
from .models import WebhookEvent

@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "provider", "processed", "error_code", "created_at")
    list_filter = ("provider", "processed")
    search_fields = ("event_id",)

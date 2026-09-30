from django.contrib import admin
from .models import VoiceCall, CallAttempt

@admin.register(VoiceCall)
class VoiceCallAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "status", "to_number", "duration_seconds", "org", "created_at")
    list_filter = ("status",)

@admin.register(CallAttempt)
class CallAttemptAdmin(admin.ModelAdmin):
    list_display = ("call", "attempt_number", "status", "error_code", "created_at")

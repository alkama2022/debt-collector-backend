from django.contrib import admin
from .models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "target_type", "target_id", "ip", "created_at")
    list_filter = ("action", "target_type")
    search_fields = ("action", "target_id")
    readonly_fields = ("id", "actor", "action", "target_type", "target_id", "before", "after", "ip", "user_agent", "created_at")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

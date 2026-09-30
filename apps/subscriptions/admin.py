from django.contrib import admin
from .models import Subscription

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("org", "plan", "status", "current_period_end", "updated_at")
    list_filter = ("plan", "status")
    search_fields = ("org__name", "org__slug")

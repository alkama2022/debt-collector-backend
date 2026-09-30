from django.contrib import admin
from .models import CollectionPolicy, Campaign

@admin.register(CollectionPolicy)
class CollectionPolicyAdmin(admin.ModelAdmin):
    list_display = ("org", "max_contacts_per_day", "max_contacts_per_week", "updated_at")

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name",)

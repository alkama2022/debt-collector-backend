from rest_framework import serializers
from .models import CollectionPolicy, Campaign

class CollectionPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = CollectionPolicy
        fields = ["id", "org", "reminder_intervals", "quiet_hours_start", "quiet_hours_end", "max_contacts_per_day", "max_contacts_per_week", "escalate_after_attempts", "auto_pause_on_payment", "created_at", "updated_at"]
        read_only_fields = ["id", "org", "created_at", "updated_at"]

class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = ["id", "org", "name", "status", "description", "config", "started_at", "ended_at", "created_at", "updated_at"]
        read_only_fields = ["id", "org", "created_at", "updated_at"]

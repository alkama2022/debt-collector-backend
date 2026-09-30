from rest_framework import serializers
from .models import WebhookEvent

class WebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEvent
        fields = ["id", "provider", "event_id", "payload", "signature", "processed", "error_code", "created_at"]
        read_only_fields = fields

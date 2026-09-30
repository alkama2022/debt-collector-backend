from rest_framework import serializers
from .models import VoiceCall, CallAttempt

class CallAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = CallAttempt
        fields = ["id", "org", "call", "attempt_number", "status", "provider_response", "error_code", "created_at"]
        read_only_fields = ["id", "org", "created_at"]

class VoiceCallSerializer(serializers.ModelSerializer):
    attempts = CallAttemptSerializer(many=True, read_only=True)
    class Meta:
        model = VoiceCall
        fields = ["id", "org", "customer", "invoice", "status", "provider_call_id", "from_number", "to_number", "duration_seconds", "recording_url", "cost_minor", "created_at", "updated_at", "attempts"]
        read_only_fields = ["id", "org", "created_at", "updated_at"]

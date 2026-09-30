from rest_framework import serializers
from .models import AuditLog, AICommunicationAudit


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ["id", "actor", "action", "target_type", "target_id", "before", "after", "ip", "user_agent", "created_at"]
        read_only_fields = fields


class AICommunicationAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AICommunicationAudit
        fields = [
            "id", "org", "customer", "conversation", "comm_event", "voice_call",
            "language_selected", "language_detected", "secondary_language",
            "detection_confidence", "language_source", "channel", "ai_model",
            "prompt_version", "template_id", "request_summary", "response_text",
            "translation_status", "staff_translation", "voice_provider", "voice_id",
            "stt_confidence", "call_status", "recording_url", "outcome",
            "escalated", "escalation_reason", "handled_by", "corrected",
            "tokens", "cost_minor", "created_at",
        ]
        read_only_fields = fields

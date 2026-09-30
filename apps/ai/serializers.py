from rest_framework import serializers
from .models import AIConversation, AIMessage, AIAgentAction, PromiseToPay


class AIMessageSerializer(serializers.ModelSerializer):
    """
    §32/§33 — expose the original message and any staff translation as
    separate, clearly-labelled fields. `content` is always the customer's
    original words; a translation never overwrites it.
    """

    language_code = serializers.SerializerMethodField()
    detected_language_code = serializers.SerializerMethodField()
    secondary_language_code = serializers.SerializerMethodField()

    class Meta:
        model = AIMessage
        fields = [
            "id", "conversation", "role", "content", "tokens", "created_at",
            # language trace (§6/§7/§27)
            "language", "language_code", "detected_language",
            "detected_language_code", "language_confidence",
            "secondary_language", "secondary_language_code",
            "is_code_switched", "was_language_switch", "escalated",
            # staff rendering (§33)
            "staff_translation", "staff_translation_language",
            "staff_translation_confidence",
        ]
        read_only_fields = ["id", "created_at"]

    def get_language_code(self, obj):
        return obj.language.code if obj.language_id else None

    def get_detected_language_code(self, obj):
        return obj.detected_language.code if obj.detected_language_id else None

    def get_secondary_language_code(self, obj):
        return obj.secondary_language.code if obj.secondary_language_id else None


class AIAgentActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAgentAction
        fields = ["id", "conversation", "tool", "input", "output", "tokens", "cost_minor", "prompt_version", "created_at"]
        read_only_fields = ["id", "created_at"]


class PromiseToPaySerializer(serializers.ModelSerializer):
    class Meta:
        model = PromiseToPay
        fields = ["id", "org", "conversation", "customer", "invoice", "promise_date", "amount", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class AIConversationSerializer(serializers.ModelSerializer):
    messages = AIMessageSerializer(many=True, read_only=True)
    conversation_language_code = serializers.SerializerMethodField()
    preferred_language_code = serializers.SerializerMethodField()

    class Meta:
        model = AIConversation
        fields = [
            "id", "org", "customer", "invoice", "state", "channel",
            "created_at", "updated_at", "messages",
            # language memory (§20)
            "preferred_language", "preferred_language_code",
            "conversation_language", "conversation_language_code",
            "language_source", "language_switch_count", "code_switch_count",
            "language_updated_at",
        ]
        read_only_fields = [
            "id", "org", "created_at", "updated_at",
            "conversation_language", "language_source",
            "language_switch_count", "code_switch_count", "language_updated_at",
        ]

    def get_conversation_language_code(self, obj):
        return obj.conversation_language.code if obj.conversation_language_id else None

    def get_preferred_language_code(self, obj):
        return obj.preferred_language.code if obj.preferred_language_id else None

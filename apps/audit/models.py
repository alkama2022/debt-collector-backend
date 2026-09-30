import uuid
from django.db import models
from django.conf import settings

# S34 - "Do not store more sensitive content than necessary. Apply
# appropriate retention policies."
#
# The windows live in policy.py so they can be asserted without booting the
# ORM. Voice recordings and verbatim transcripts are the most sensitive data
# the platform handles, so they get the shortest retention. Structured
# metadata (which language, which model, what confidence) is kept far longer
# because S24 quality reporting needs it and it identifies no one.
from .policy import (  # noqa: F401  (re-exported for callers)
    RETENTION_DAYS_METADATA,
    RETENTION_DAYS_RECORDING,
    RETENTION_DAYS_TRANSCRIPT,
    RETENTION_POLICY,
)


class AICommunicationAudit(models.Model):
    """
    §34 — one row per AI communication, recording exactly what was decided.

    This is deliberately separate from the generic AuditLog above. AuditLog
    answers "who changed this record?"; this answers "why did the AI say that,
    in which language, and did a human have to step in?" — the questions a
    collections dispute and the language dashboard both depend on.
    """

    class Outcome(models.TextChoices):
        SENT = "sent", "Sent"
        RECEIVED = "received", "Received"
        ESCALATED = "escalated", "Escalated"
        HANDLED_BY_HUMAN = "human_handoff", "Handled By Human"
        FAILED = "failed", "Failed"

    class EscalationReason(models.TextChoices):
        LOW_CONFIDENCE = "low_confidence", "Low Confidence"
        NO_NATIVE_VOICE = "no_native_voice", "No Native Voice"
        CUSTOMER_REQUEST = "customer_request", "Customer Request"
        DISPUTE = "dispute", "Dispute"
        STT_UNRELIABLE = "stt_unreliable", "Speech Recognition Unreliable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="ai_comm_audits")

    # Who and where
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_comm_audits")
    conversation = models.ForeignKey("ai.AIConversation", on_delete=models.CASCADE, null=True, blank=True, related_name="ai_comm_audits")
    comm_event = models.ForeignKey("comms.CommunicationEvent", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_comm_audits")
    voice_call = models.ForeignKey("voice.VoiceCall", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_comm_audits")

    # Language decisions
    language_selected = models.CharField(max_length=10, blank=True, default="", help_text="Language used for the reply")
    language_detected = models.CharField(max_length=10, blank=True, default="", help_text="Language detected from customer input")
    secondary_language = models.CharField(max_length=10, blank=True, default="", help_text="Second language present (code-switch, S27)")
    detection_confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    language_source = models.CharField(max_length=24, blank=True, default="", help_text="How the language was chosen (S5)")

    # Channel + model
    channel = models.CharField(max_length=16, blank=True, default="")
    ai_model = models.CharField(max_length=64, blank=True, default="", help_text="e.g. gpt-4o-mini")
    prompt_version = models.CharField(max_length=64, blank=True, default="")
    template_id = models.CharField(max_length=64, blank=True, default="")

    # Content — minimised on purpose
    request_summary = models.TextField(blank=True, default="", help_text="Redacted/truncated input")
    response_text = models.TextField(blank=True, default="", help_text="What the AI actually sent")
    translation_status = models.CharField(max_length=24, blank=True, default="", help_text="none | generated | staff_viewed")
    staff_translation = models.TextField(blank=True, default="", help_text="Staff-facing rendering (S33)")

    # Voice
    voice_provider = models.CharField(max_length=32, blank=True, default="")
    voice_id = models.CharField(max_length=64, blank=True, default="")
    stt_confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    call_status = models.CharField(max_length=16, blank=True, default="")
    recording_url = models.CharField(max_length=256, blank=True, default="", help_text="Expires per retention policy")

    # Outcome + human oversight
    outcome = models.CharField(max_length=24, choices=Outcome.choices, blank=True, default="")
    escalated = models.BooleanField(default=False)
    escalation_reason = models.CharField(max_length=24, choices=EscalationReason.choices, blank=True, default="")
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_comm_handled")
    corrected = models.BooleanField(default=False, help_text="A human edited the AI output before sending")

    tokens = models.IntegerField(null=True, blank=True)
    cost_minor = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_communication_audits"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org", "created_at"]),
            models.Index(fields=["org", "language_selected"]),
            models.Index(fields=["customer", "created_at"]),
            models.Index(fields=["org", "escalated"]),
        ]

    def save(self, *args, **kwargs):
        # Immutable, like AuditLog — a communication record must not be
        # retroactively edited.
        if self.pk and AICommunicationAudit.objects.filter(pk=self.pk).exists():
            raise ValueError("AICommunicationAudit is immutable and cannot be updated")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.channel} {self.outcome} [{self.language_selected}] {self.created_at}"

    @property
    def content_expires_at(self):
        """When the verbatim content on this row should be purged."""
        from datetime import timedelta
        from django.utils import timezone
        return self.created_at + timedelta(days=RETENTION_DAYS_TRANSCRIPT)


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    action = models.CharField(max_length=64, help_text="e.g. customer.create, invoice.update")
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=128, blank=True, default="")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"]), models.Index(fields=["actor"])]

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            # immutable: prevent updates
            raise ValueError("AuditLog is immutable and cannot be updated")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.action} by {self.actor} at {self.created_at}"

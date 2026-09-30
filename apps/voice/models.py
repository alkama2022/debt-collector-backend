import uuid
from django.db import models
from apps.tenancy.models import TenantModel, TenantManager

class VoiceManager(TenantManager):
    pass

class VoiceCall(TenantModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RINGING = "ringing", "Ringing"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        NO_ANSWER = "no_answer", "No Answer"
        BUSY = "busy", "Busy"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_calls")
    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_calls")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    provider_call_id = models.CharField(max_length=128, blank=True, default="")
    from_number = models.CharField(max_length=32, blank=True, default="")
    to_number = models.CharField(max_length=32, blank=True, default="")
    duration_seconds = models.IntegerField(null=True, blank=True)
    recording_url = models.URLField(blank=True, default="")
    cost_minor = models.IntegerField(null=True, blank=True)

    # ── Language (§9/§10/§22) ───────────────────────────────────────────
    # The voice agent must know which language to speak before it dials, and
    # must not speak a customer's language with another language's voice.
    language = models.ForeignKey(
        "languages.Language",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="voice_calls",
        help_text="Language the agent spoke on this call",
    )
    language_source = models.CharField(
        max_length=24, blank=True, default="",
        help_text="customer_voice_pref | customer_pref | conversation | org_default | fallback",
    )
    voice_id = models.CharField(max_length=64, blank=True, default="", help_text="TTS voice actually used")
    voice_provider = models.CharField(max_length=32, blank=True, default="")
    voice_usable = models.BooleanField(
        default=True, help_text="False when no native voice existed and we should not have called (§22)",
    )
    detected_language = models.CharField(
        max_length=10, blank=True, default="",
        help_text="Language detected from the customer's speech (§10)",
    )
    stt_confidence = models.DecimalField(
        max_digits=4, decimal_places=3, null=True, blank=True,
        help_text="Speech-to-text confidence for the last turn (§10)",
    )
    language_switch_count = models.PositiveIntegerField(default=0, help_text="Spoken language switches (§9 step 6)")
    escalated = models.BooleanField(default=False, help_text="Agent handed off to a human (§23)")
    escalation_reason = models.CharField(max_length=32, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VoiceManager()

    class Meta:
        db_table = "voice_calls"
        indexes = [
            models.Index(fields=["org", "status"]),
            models.Index(fields=["org", "language"]),
        ]

    def __str__(self):
        return f"Call {self.id} {self.status}"

class CallAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.RESTRICT, related_name="call_attempts")
    call = models.ForeignKey(VoiceCall, on_delete=models.CASCADE, related_name="attempts")
    attempt_number = models.IntegerField(default=1)
    status = models.CharField(max_length=16, choices=VoiceCall.Status.choices, default=VoiceCall.Status.QUEUED)
    provider_response = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")
    # §10 — per-turn speech-to-text trace, so a bad transcript is diagnosable
    stt_text = models.TextField(blank=True, default="")
    stt_confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    detected_language = models.CharField(max_length=10, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "call_attempts"
        ordering = ["attempt_number"]

    def __str__(self):
        return f"Attempt {self.attempt_number} for {self.call_id}"

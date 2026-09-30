import uuid
from django.db import models
from apps.tenancy.models import TenantModel, TenantManager

class CommsManager(TenantManager):
    pass

class CommunicationPreference(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="comm_preferences")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="comm_preferences")
    channel = models.CharField(max_length=16, choices=[("whatsapp","WhatsApp"),("sms","SMS"),("email","Email"),("voice","Voice")])
    enabled = models.BooleanField(default=True)
    opted_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "communication_preferences"
        unique_together = ("org", "customer", "channel")

    def __str__(self):
        return f"{self.customer} - {self.channel}"

class CommunicationEvent(TenantModel):
    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"
        VOICE = "voice", "Voice"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="comm_events")
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="comm_events")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    template_id = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    provider_msg_id = models.CharField(max_length=128, blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    cost_minor = models.IntegerField(null=True, blank=True, help_text="Cost in kobo")
    error_code = models.CharField(max_length=64, blank=True, default="")

    # §21 — the language actually used for this message. Recorded so staff can
    # always prove which language a customer was contacted in, and so §24 can
    # attribute response rates per language.
    language = models.CharField(
        max_length=10, blank=True, default="",
        help_text="Language the message was rendered in (empty = resolved at send time)",
    )
    language_source = models.CharField(
        max_length=24, blank=True, default="",
        help_text="event_override | customer_preferred | org_default | fallback",
    )
    body_snapshot = models.TextField(
        blank=True, default="",
        help_text="Exact text sent - preserved so a dispute can be reconstructed",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CommsManager()

    class Meta:
        db_table = "communication_events"
        indexes = [
            models.Index(fields=["org", "channel"]),
            models.Index(fields=["org", "status"]),
            models.Index(fields=["org", "language"]),
        ]

    def __str__(self):
        return f"{self.channel} -> {self.customer} ({self.status})"


class ReminderRule(TenantModel):
    """S3 Auto-Reminder Engine: set once, runs daily at 8am WAT. — Love feature."""
    class Trigger(models.TextChoices):
        BEFORE_DUE = "before_due", "Before due"
        ON_DUE = "on_due", "On due date"
        AFTER_DUE = "after_due", "After due"

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"
        VOICE = "voice", "Voice"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, default="Reminder rule")
    trigger = models.CharField(max_length=16, choices=Trigger.choices, default=Trigger.ON_DUE)
    offset_days = models.IntegerField(default=0, help_text="Days before (negative) or after due date. 0=on due")
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.WHATSAPP)
    template = models.TextField(default="Hello {{customer_name}}, invoice {{invoice_number}} for {{amount_due}} is due on {{due_date}}. Pay: {{payment_link}}")
    language = models.CharField(max_length=16, default="auto", help_text="auto=customer preferred, or en/ha/yo/ig")
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CommsManager()

    class Meta:
        db_table = "reminder_rules"
        indexes = [models.Index(fields=["org", "enabled"])]

    def __str__(self):
        return f"{self.name} ({self.trigger} {self.offset_days}d via {self.channel})"

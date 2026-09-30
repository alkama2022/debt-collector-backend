import uuid
from django.db import models
from apps.tenancy.models import TenantModel, TenantManager

class AIManager(TenantManager):
    pass

class AIConversation(TenantModel):
    class State(models.TextChoices):
        INVOICE_CREATED = "INVOICE_CREATED", "Invoice Created"
        REMINDER_SENT = "REMINDER_SENT", "Reminder Sent"
        CUSTOMER_REPLIED = "CUSTOMER_REPLIED", "Customer Replied"
        NEGOTIATING = "NEGOTIATING", "Negotiating"
        PROMISE_MADE = "PROMISE_MADE", "Promise Made"
        PROMISE_DUE = "PROMISE_DUE", "Promise Due"
        PAYMENT_RECEIVED = "PAYMENT_RECEIVED", "Payment Received"
        PAYMENT_FAILED = "PAYMENT_FAILED", "Payment Failed"
        ESCALATED = "ESCALATED", "Escalated"
        HUMAN_HANDOFF = "HUMAN_HANDOFF", "Human Handoff"
        RESOLVED = "RESOLVED", "Resolved"
        CANCELLED = "CANCELLED", "Cancelled"
        FOLLOW_UP = "FOLLOW_UP", "Follow Up"
        OVERDUE_NOTICE = "OVERDUE_NOTICE", "Overdue Notice"
        COLLECTION_CLOSED = "COLLECTION_CLOSED", "Collection Closed"

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"
        VOICE = "voice", "Voice"

    class LanguageSource(models.TextChoices):
        """Why the conversation is being conducted in a given language (§20)."""
        CUSTOMER_PREFERRED = "customer_preferred", "Customer Preferred"
        DETECTED = "detected", "Detected"
        CONVERSATION_MEMORY = "conversation_memory", "Conversation Memory"
        BUSINESS_FALLBACK = "business_fallback", "Business Fallback"
        SYSTEM_FALLBACK = "system_fallback", "System Fallback"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_conversations")
    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_conversations")
    state = models.CharField(max_length=32, choices=State.choices, default=State.INVOICE_CREATED)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.WHATSAPP)

    # ── Language memory (§20) ──────────────────────────────────────────
    # The AI must not re-detect the customer's language on every message when
    # a trusted preference already exists. We snapshot the preference at
    # conversation start and carry the current language forward.
    preferred_language = models.ForeignKey(
        "languages.Language",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_conversation_preferred",
        help_text="Snapshot of customer preferred_language at conversation start",
    )
    conversation_language = models.ForeignKey(
        "languages.Language",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_conversation_current",
        help_text="Language currently being used in this conversation",
    )
    language_source = models.CharField(
        max_length=24, choices=LanguageSource.choices, blank=True, default="",
        help_text="How conversation_language was chosen (audit + §20 continuity)",
    )
    language_switch_count = models.PositiveIntegerField(
        default=0, help_text="Number of detected language switches in this conversation (§8)",
    )
    code_switch_count = models.PositiveIntegerField(
        default=0, help_text="Number of mixed-language messages seen (§27)",
    )
    language_updated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AIManager()

    class Meta:
        db_table = "ai_conversations"
        indexes = [
            models.Index(fields=["org", "state"]),
            models.Index(fields=["org", "conversation_language"]),
        ]

    def __str__(self):
        return f"{self.id} - {self.state}"

class AIMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=[("user","User"),("assistant","Assistant"),("system","System"),("tool","Tool")], default="user")
    content = models.TextField()
    tokens = models.IntegerField(null=True, blank=True)

    # ── Per-message language trace (§6/§7/§20/§27) ────────────────────
    # Stored per message so a staff member can always answer "why did the AI
    # reply in this language?" — see the audit requirements in §34.
    language = models.ForeignKey(
        "languages.Language",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_messages",
        help_text="Language this message was written in",
    )
    detected_language = models.ForeignKey(
        "languages.Language",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_messages_detected",
        help_text="Language detected from the inbound text (§6)",
    )
    language_confidence = models.DecimalField(
        max_digits=4, decimal_places=3, null=True, blank=True,
        help_text="Detection confidence 0-1 (§7)",
    )
    secondary_language = models.ForeignKey(
        "languages.Language",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_messages_secondary",
        help_text="Second language present in a mixed-language message (§27)",
    )
    is_code_switched = models.BooleanField(
        default=False, help_text="Message mixed two languages (§27)",
    )
    was_language_switch = models.BooleanField(
        default=False,
        help_text="Language differed from the conversation's established language (§8)",
    )
    # §33: staff-facing rendering. The original text in `content` is never
    # modified or overwritten by any AI translation.
    staff_translation = models.TextField(
        blank=True, default="",
        help_text="AI translation of `content` into the business owner's language (§33)",
    )
    staff_translation_language = models.CharField(
        max_length=10, blank=True, default="", help_text="Language of staff_translation",
    )
    staff_translation_confidence = models.DecimalField(
        max_digits=4, decimal_places=3, null=True, blank=True,
    )
    escalated = models.BooleanField(
        default=False, help_text="Low-confidence language handling triggered (§23)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_messages"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"

class AIAgentAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="actions")
    tool = models.CharField(max_length=128, help_text="Tool/function name")
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    tokens = models.IntegerField(null=True, blank=True)
    cost_minor = models.IntegerField(null=True, blank=True)
    prompt_version = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_agent_actions"

    def __str__(self):
        return f"{self.tool} @ {self.created_at}"

class PromiseToPay(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        KEPT = "kept", "Kept"
        BROKEN = "broken", "Broken"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.RESTRICT, related_name="promises")
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="promises", null=True, blank=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="promises", null=True, blank=True)
    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.CASCADE, related_name="promises", null=True, blank=True)
    promise_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "promise_to_pay"

    def __str__(self):
        return f"Promise {self.amount} on {self.promise_date} ({self.status})"

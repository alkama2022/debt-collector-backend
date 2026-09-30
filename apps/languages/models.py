import uuid
from django.db import models
from django.conf import settings


class Language(models.Model):
    """Registry of languages supported by CollectNaija. Add future languages as rows (active=False)."""

    class QualityStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW = "review", "Review"
        PRODUCTION = "production", "Production"

    code = models.CharField(
        max_length=10,
        primary_key=True,
        help_text="BCP-47 style e.g. en, ha, yo, ig, pcm, ff, kr, tiv",
    )
    name = models.CharField(max_length=64, help_text="English name, e.g. Hausa")
    native_name = models.CharField(max_length=64, help_text="Native name, e.g. Hausa, Yorùbá")
    locale = models.CharField(max_length=16, help_text="Locale e.g. ha-NG, en-NG, yo-NG")
    text_supported = models.BooleanField(default=True)
    speech_to_text_supported = models.BooleanField(default=False)
    text_to_speech_supported = models.BooleanField(default=False)
    active = models.BooleanField(default=True, db_index=True)
    quality_status = models.CharField(
        max_length=16, choices=QualityStatus.choices, default=QualityStatus.PRODUCTION
    )
    version = models.CharField(max_length=16, default="1.0.0")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "languages"
        ordering = ["code"]
        verbose_name = "Language"
        verbose_name_plural = "Languages"

    def __str__(self):
        return f"{self.name} ({self.code}) [{self.locale}]"


class OrganizationLanguageSettings(models.Model):
    """Three language settings per org: dashboard, default customer, fallback + mode + supported set."""

    class AICommunicationMode(models.TextChoices):
        CUSTOMER_PREFERRED = "customer_preferred", "Customer Preferred"
        BUSINESS_FALLBACK = "business_fallback", "Business Fallback"
        AUTO_DETECT = "auto_detect", "Auto Detect"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.OneToOneField(
        "tenancy.Organization",
        on_delete=models.CASCADE,
        related_name="language_settings",
    )
    dashboard_language = models.ForeignKey(
        Language,
        on_delete=models.RESTRICT,
        related_name="dashboard_orgs",
        default="en",
    )
    default_customer_language = models.ForeignKey(
        Language,
        on_delete=models.RESTRICT,
        related_name="default_customer_orgs",
        default="en",
    )
    ai_communication_mode = models.CharField(
        max_length=24,
        choices=AICommunicationMode.choices,
        default=AICommunicationMode.CUSTOMER_PREFERRED,
    )
    fallback_language = models.ForeignKey(
        Language,
        on_delete=models.RESTRICT,
        related_name="fallback_orgs",
        default="en",
    )
    supported_languages = models.ManyToManyField(
        Language, related_name="supported_by_orgs", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_language_settings"
        verbose_name = "Organization Language Settings"
        verbose_name_plural = "Organization Language Settings"

    def __str__(self):
        return f"LanguageSettings({self.org_id}) dashboard={self.dashboard_language_id}"


class CustomerLanguageHistory(models.Model):
    """Audit trail for customer language changes."""

    class Reason(models.TextChoices):
        CUSTOMER_REQUEST = "customer_request", "Customer Request"
        BUSINESS_CHANGE = "business_change", "Business Change"
        AUTO_DETECT = "auto_detect", "Auto Detect"
        DETECTED_SWITCH = "detected_switch", "Detected Switch"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "tenancy.Organization", on_delete=models.CASCADE, related_name="customer_language_histories"
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.CASCADE, related_name="language_histories"
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_language_changes",
        help_text="Null when system/auto_detect",
    )
    from_lang = models.ForeignKey(
        Language,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="history_from",
    )
    to_lang = models.ForeignKey(
        Language,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="history_to",
    )
    reason = models.CharField(max_length=24, choices=Reason.choices, default=Reason.CUSTOMER_REQUEST)
    detected_confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_language_history"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org", "customer", "created_at"]),
            models.Index(fields=["org", "created_at"]),
            models.Index(fields=["customer", "created_at"]),
        ]

    def __str__(self):
        return f"{self.customer_id}: {self.from_lang_id} -> {self.to_lang_id} ({self.reason})"

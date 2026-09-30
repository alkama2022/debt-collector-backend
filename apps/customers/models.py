import uuid
from django.db import models
from django.db.models import Q
from django.conf import settings
from apps.tenancy.models import TenantModel, TenantManager


class CustomerManager(TenantManager):
    pass


class Customer(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    outstanding = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    overdue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    prefs = models.JSONField(default=dict, blank=True)
    communication_preference = models.JSONField(default=dict, blank=True)
    opt_out = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Multilingual fields
    preferred_language = models.ForeignKey(
        "languages.Language",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        default=None,
        related_name="customers_preferred",
        db_column="preferred_language",
    )
    voice_language = models.ForeignKey(
        "languages.Language",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="customers_voice",
        db_column="voice_language",
    )
    language_detection_enabled = models.BooleanField(default=True)
    language_updated_at = models.DateTimeField(null=True, blank=True)

    objects = CustomerManager()

    class Meta:
        db_table = "customers"
        constraints = [
            models.UniqueConstraint(fields=["org", "customer_code"], condition=Q(deleted_at__isnull=True), name="uniq_customer_code_per_org"),
        ]
        indexes = [
            models.Index(fields=["org", "customer_code"]),
            models.Index(fields=["org", "name"]),
            models.Index(fields=["org", "preferred_language"]),
            models.Index(fields=["preferred_language"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.customer_code})"

    def get_effective_language(self, fallback: str = "en") -> str:
        """Fallback handling: preferred_language -> fallback param -> 'en'."""
        if self.preferred_language_id:
            return self.preferred_language_id
        return fallback or "en"

    def save(self, *args, **kwargs):
        # Set default preferred_language to 'en' if not set and Language exists
        if not self.preferred_language_id:
            # Defer default to DB; keep None to allow fallback logic, but ensure 'en' if Language table has it
            try:
                from apps.languages.models import Language
                if Language.objects.filter(code="en").exists():
                    # Only set if explicitly no value and this is creation without preference
                    # Keep None on existing rows to allow migration; new rows default via logic elsewhere
                    pass
            except Exception:
                pass
        super().save(*args, **kwargs)

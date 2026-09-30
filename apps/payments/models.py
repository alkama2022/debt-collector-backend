import uuid
from decimal import Decimal
from django.db import models
from apps.tenancy.models import TenantModel, TenantManager

class PaymentManager(TenantManager):
    pass

class Payment(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESSFUL = "successful", "Successful"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    class Provider(models.TextChoices):
        PAYSTACK = "paystack", "Paystack"
        FLUTTERWAVE = "flutterwave", "Flutterwave"
        MANUAL = "manual", "Manual"

    MANUAL_METHODS = [
        "cash", "bank_transfer", "card", "pos", "cheque", "mobile_money", "other"
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey("invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # provider = payment gateway / channel (paystack, flutterwave, manual)
    provider = models.CharField(max_length=16, choices=Provider.choices, default=Provider.MANUAL)
    # method = human-readable label for manual payments (Cash, Bank transfer, POS, etc.)
    method = models.CharField(max_length=64, blank=True, default="")
    provider_ref = models.CharField(max_length=128, null=True, blank=True, unique=True)
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PaymentManager()

    class Meta:
        db_table = "payments"
        indexes = [
            models.Index(fields=["org", "status"]),
            models.Index(fields=["org", "provider"]),
        ]

    def __str__(self):
        return f"{self.amount} {self.currency} ({self.status})"

class Receipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.RESTRICT, related_name="receipts")
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name="receipt")
    receipt_number = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="NGN")

    class Meta:
        db_table = "receipts"

    def __str__(self):
        return self.receipt_number

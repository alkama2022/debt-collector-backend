import uuid
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import Q
from apps.tenancy.models import TenantModel, TenantManager

class InvoiceManager(TenantManager):
    pass

class Invoice(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PARTIAL = "partial", "Partial"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.RESTRICT, related_name="invoices")
    invoice_number = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    due_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="NGN")
    sent_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = InvoiceManager()

    class Meta:
        db_table = "invoices"
        constraints = [
            models.UniqueConstraint(fields=["org", "invoice_number"], condition=Q(deleted_at__isnull=True), name="uniq_invoice_number_per_org"),
        ]
        indexes = [
            models.Index(fields=["org", "invoice_number"]),
            models.Index(fields=["org", "status"]),
        ]

    def clean(self):
        super().clean()
        expected = (self.subtotal or Decimal("0")) - (self.discount or Decimal("0")) + (self.tax or Decimal("0"))
        if self.total is not None and expected != self.total:
            raise ValidationError({"total": f"total must equal subtotal - discount + tax. Expected {expected}, got {self.total}."})
        if self.balance is not None and self.total is not None and self.balance > self.total:
            raise ValidationError({"balance": "balance cannot exceed total."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.invoice_number

class InvoiceItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    unit_price_minor = models.IntegerField(help_text="Unit price in kobo/minor units")
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        db_table = "invoice_items"

    def __str__(self):
        return f"{self.name} x {self.qty}"

from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal
from .models import Payment, Receipt
from apps.invoices.models import Invoice
from apps.comms.models import CommunicationEvent
import uuid

def _ensure_receipt(payment: Payment):
    if hasattr(payment, "receipt") and payment.receipt:
        return payment.receipt
    try:
        if Receipt.objects.filter(payment=payment).exists():
            return Receipt.objects.get(payment=payment)
    except Exception:
        pass
    # Generate receipt_number: RCT-<org>-<year>-<seq>
    num = f"RCT-{str(payment.id)[:8].upper()}"
    try:
        r = Receipt.objects.create(
            org=payment.org, payment=payment, receipt_number=num,
            amount=payment.amount, currency=payment.currency
        )
        return r
    except Exception:
        # Retry with uuid if collision
        try:
            return Receipt.objects.create(
                org=payment.org, payment=payment, receipt_number=f"RCT-{str(uuid.uuid4())[:8].upper()}",
                amount=payment.amount, currency=payment.currency
            )
        except Exception:
            return None

@receiver(post_save, sender=Payment)
def update_invoice_on_payment(sender, instance: Payment, created, **kwargs):
    # Handle both creation and status transition to successful (verify flow)
    if instance.status != "successful":
        return
    invoice = instance.invoice
    if not invoice:
        return
    # Backend is source of truth: recalc balance
    total_paid = Payment.objects.filter(invoice=invoice, status="successful").aggregate(
        s=__import__("django.db.models", fromlist=["Sum"] ).Sum("amount")
    )["s"] or Decimal("0.00")
    new_balance = max(Decimal("0.00"), invoice.total - total_paid)
    # Only update if changed to avoid recursion
    updates = {}
    if invoice.balance != new_balance:
        updates["balance"] = new_balance
        invoice.balance = new_balance
    target_status = Invoice.Status.PAID if new_balance == Decimal("0.00") else (Invoice.Status.PARTIAL if total_paid > Decimal("0.00") else invoice.status)
    if invoice.status != target_status:
        updates["status"] = target_status
        invoice.status = target_status
    if updates:
        invoice.save(update_fields=list(updates.keys()))
    # Cancel pending reminders — critical
    CommunicationEvent.objects.filter(
        invoice=invoice, status__in=["queued", "scheduled", "sending"]
    ).update(status="cancelled")
    # Auto-create receipt
    _ensure_receipt(instance)

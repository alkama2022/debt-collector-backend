from celery import shared_task
from decimal import Decimal
import logging
logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_webhook_event(self, event_id):
    try:
        from .models import WebhookEvent
        from apps.payments.models import Payment
        from apps.invoices.models import Invoice
        from apps.tenancy.models import Organization
        from django.utils import timezone
        event = WebhookEvent.objects.get(id=event_id)
        payload = event.payload or {}
        # Expected paystack: event="charge.success", data.reference, data.amount (kobo), data.metadata.invoice_id
        raw_event = payload.get("event") or payload.get("type") or ""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        # Only process successful charges
        if raw_event and raw_event not in ("charge.success", "charge.successful", "successful", "success"):
            # Still allow payloads without event name (manual test) but log
            if "charge" in raw_event and "failed" in raw_event:
                logger.info("Skipping failed charge event %s", raw_event)
                event.processed = True
                event.save(update_fields=["processed"])
                return True
        ref = str(data.get("reference") or data.get("provider_ref") or event.event_id)
        amount_minor = int(data.get("amount") or 0)
        amount = Decimal(amount_minor) / Decimal(100) if amount_minor else Decimal("0.00")
        # Resolve invoice: priority metadata.invoice_id > metadata.invoice_number > org+amount
        invoice = None
        org = None
        metadata = data.get("metadata") or payload.get("metadata") or {}
        # Paystack metadata can be dict with invoice_id
        invoice_id = metadata.get("invoice_id") or data.get("invoice_id") or metadata.get("invoice")
        org_id = metadata.get("org_id") or data.get("org_id") or payload.get("org_id")
        if invoice_id:
            try:
                invoice = Invoice.objects.filter(pk=invoice_id).first()
                if invoice:
                    org = invoice.org
            except Exception:
                pass
        if not invoice and metadata.get("invoice_number"):
            try:
                inv_no = metadata.get("invoice_number")
                if org_id:
                    org = Organization.objects.filter(id=org_id).first()
                    if org:
                        invoice = Invoice.objects.filter(org=org, invoice_number=inv_no).first()
                if not invoice:
                    invoice = Invoice.objects.filter(invoice_number=inv_no).first()
                    if invoice:
                        org = invoice.org
            except Exception:
                pass
        if not invoice and org_id:
            try:
                org = Organization.objects.get(id=org_id)
                # try pending payment with same reference to resolve org/invoice
                pending = Payment.objects.filter(provider_ref=ref).first()
                if pending and pending.invoice:
                    invoice = pending.invoice
                    org = pending.org
                else:
                    invoice = Invoice.objects.filter(org=org, status__in=["sent","partial","overdue"]).first()
            except Exception:
                pass
        # Fallback: pending payment with same ref
        if not invoice:
            pending = Payment.objects.filter(provider_ref=ref).first()
            if pending and pending.invoice:
                invoice = pending.invoice
                org = pending.org
        if not invoice and amount:
            invoice = Invoice.objects.filter(balance=amount).first()
            if invoice:
                org = invoice.org
        if not invoice:
            logger.warning("No invoice matched for webhook %s ref %s amount %s", event_id, ref, amount)
            event.processed = True
            event.save(update_fields=["processed"])
            return True
        if not org:
            org = invoice.org
        # Upsert successful payment
        existing = Payment.objects.filter(provider_ref=ref).first()
        if existing:
            if existing.status != "successful":
                existing.status = "successful"
                existing.verified_at = timezone.now()
                if amount and Decimal(amount) != Decimal("0.00"):
                    existing.amount = Decimal(amount)
                existing.save(update_fields=["status", "verified_at", "amount"])
                logger.info("Verified pending payment %s -> successful", ref)
            else:
                logger.info("Idempotent replay for %s", ref)
        else:
            pay_amount = amount if amount and Decimal(amount) != Decimal("0.00") else invoice.balance
            Payment.objects.create(
                org=org, invoice=invoice, amount=pay_amount,
                currency=invoice.currency, status="successful",
                provider=event.provider if event.provider in ("paystack","flutterwave") else "paystack",
                provider_ref=ref,
                idempotency_key=f"{event.provider}:{ref}",
                verified_at=timezone.now(),
            )
            logger.info("Created successful payment %s for invoice %s via %s amount %s", ref, invoice.invoice_number, event.provider, pay_amount)
        event.processed = True
        event.save(update_fields=["processed"])
        return True
    except Exception as exc:
        logger.exception("Failed to process webhook %s: %s", event_id, exc)
        try:
            from .models import WebhookEvent
            ev = WebhookEvent.objects.filter(id=event_id).first()
            if ev:
                ev.error_code = str(exc)[:256]
                ev.save(update_fields=["error_code"])
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def process_inbound_message(self, phone: str, message: str, channel: str = "sms"):
    """
    Process an inbound customer message (SMS/WhatsApp reply from AT).
    1. Find the customer by phone number
    2. Find their most recent open AI conversation (or create one)
    3. Run the AI response engine
    4. Queue the response via CommunicationEvent
    """
    try:
        from apps.customers.models import Customer
        from apps.ai.models import AIConversation, AIMessage
        from apps.comms.models import CommunicationEvent
        from apps.invoices.models import Invoice
        from django.utils import timezone

        # Normalize phone: try both with and without country code
        normalized = phone.strip()
        customers = Customer.objects.filter(phone__icontains=normalized[-9:])
        if not customers.exists():
            logger.warning("[InboundMsg] No customer found for phone %s", phone)
            return False

        customer = customers.first()
        org = customer.org

        # Find open conversation or create one
        open_conv = (
            AIConversation.objects
            .filter(
                org=org,
                customer=customer,
                state__in=[
                    "REMINDER_SENT", "CUSTOMER_REPLIED", "NEGOTIATING",
                    "PROMISE_MADE", "OVERDUE", "FOLLOW_UP",
                ],
            )
            .order_by("-updated_at")
            .first()
        )

        # Find the customer's most overdue open invoice
        invoice = (
            Invoice.objects
            .for_org(org)
            .filter(customer=customer, balance__gt=0, status__in=["sent", "partial", "overdue"])
            .order_by("-due_date")
            .first()
        )

        if not open_conv:
            open_conv = AIConversation.objects.create(
                org=org,
                customer=customer,
                invoice=invoice,
                state=AIConversation.State.CUSTOMER_REPLIED,
                channel=channel,
            )
        else:
            open_conv.state = AIConversation.State.CUSTOMER_REPLIED
            open_conv.save(update_fields=["state", "updated_at"])

        # Record inbound message
        AIMessage.objects.create(
            conversation=open_conv,
            role="user",
            content=message,
        )

        # Build context for AI response
        context_data = {
            "customer_name": customer.name,
            "invoice_number": invoice.invoice_number if invoice else "",
            "amount_due": str(invoice.balance) if invoice else "0",
            "due_date": str(invoice.due_date) if invoice and invoice.due_date else "",
            "payment_link": f"{_get_frontend_url()}/pay/{str(invoice.id)}" if invoice else "",
            "business_name": org.name,
        }

        # Call AI response engine
        import requests as req
        ai_response_text = _generate_ai_response(message, context_data, org)

        # Record AI response
        AIMessage.objects.create(
            conversation=open_conv,
            role="assistant",
            content=ai_response_text,
        )

        # Check for promise-to-pay intent in message
        _check_and_record_promise(message, open_conv, invoice, org)

        # Check for escalation need
        _check_escalation(message, open_conv)

        # Queue AI response via CommunicationEvent
        idem_key = f"ai-reply-{open_conv.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        CommunicationEvent.objects.create(
            org=org,
            invoice=invoice,
            customer=customer,
            channel=channel,
            template_id="ai_response",
            status="queued",
            scheduled_for=timezone.now(),
            idempotency_key=idem_key,
        )
        # Patch the template_id to hold the actual response text for the provider
        CommunicationEvent.objects.filter(idempotency_key=idem_key).update(
            template_id=ai_response_text[:128]
        )

        logger.info("[InboundMsg] Processed reply from %s | conv=%s", phone, open_conv.id)
        return True

    except Exception as exc:
        logger.exception("[InboundMsg] Failed to process message from %s: %s", phone, exc)
        raise self.retry(exc=exc, countdown=30)


def _generate_ai_response(message: str, context: dict, org) -> str:
    """Generate AI response using OpenAI/Anthropic or template fallback."""
    from django.conf import settings as _s

    provider = getattr(_s, "AI_PROVIDER", "mock")

    # Detect intent from customer message
    low = message.lower()
    if any(k in low for k in ["will pay", "pay on", "pay next", "pay tomorrow", "pay friday", "pay monday"]):
        intent = "promise"
    elif any(k in low for k in ["can't pay", "cannot pay", "no money", "later", "difficult"]):
        intent = "negotiation"
    elif any(k in low for k in ["already paid", "i paid", "sent money", "transferred"]):
        intent = "dispute"
    elif any(k in low for k in ["stop", "don't contact", "leave me", "opt out", "remove"]):
        intent = "opt_out"
    elif any(k in low for k in ["speak to", "talk to", "human", "person", "manager"]):
        intent = "escalation"
    else:
        intent = "reminder"

    if intent == "opt_out":
        # Honor opt-out immediately
        try:
            from apps.customers.models import Customer
            Customer.objects.filter(org=org, phone__icontains=context.get("customer_name", "")[:4]).update(opt_out=True)
        except Exception:
            pass
        return (
            f"Hello {context['customer_name']}, your request to stop receiving automated messages has been noted. "
            f"You will not receive further automated reminders. "
            f"If you have questions, please contact {context['business_name']} directly."
        )

    if intent == "escalation":
        return (
            f"Hello {context['customer_name']}, I understand you'd like to speak with someone directly. "
            f"I have flagged your account for a human representative from {context['business_name']} to contact you shortly. "
            f"Thank you for your patience."
        )

    if intent == "dispute":
        return (
            f"Hello {context['customer_name']}, thank you for letting us know. "
            f"We will verify your payment and update the record. "
            f"If you have a payment reference or receipt, kindly share it so we can confirm quickly. "
            f"We'll get back to you within one business day."
        )

    # Try LLM if configured
    if provider in ("openai", "anthropic") and (getattr(_s, "OPENAI_API_KEY", "") or getattr(_s, "ANTHROPIC_API_KEY", "")):
        try:
            from apps.ai.views import _call_llm_for_intent
            result = _call_llm_for_intent(intent, "en", message, context)
            if result:
                return result
        except Exception:
            pass

    # Natural template fallback
    try:
        from apps.languages.templates import render_template
        return render_template(intent, "en", context)
    except Exception:
        pass

    # Hard fallback
    templates = {
        "promise": (
            f"Thank you for letting us know, {context['customer_name']}. "
            f"We have noted your intention to pay. "
            f"Could you please confirm the exact date you will be making the payment? "
            f"You can pay via this link: {context['payment_link']}"
        ),
        "negotiation": (
            f"Hello {context['customer_name']}, we understand things can be difficult sometimes. "
            f"Please contact {context['business_name']} directly to discuss a payment arrangement. "
            f"We want to work with you to resolve your balance of {context['amount_due']}."
        ),
        "reminder": (
            f"Hello {context['customer_name']}, your outstanding balance for invoice "
            f"{context['invoice_number']} is {context['amount_due']}. "
            f"You can pay here: {context['payment_link']} — Thank you."
        ),
    }
    return templates.get(intent, templates["reminder"])


def _check_and_record_promise(message: str, conversation, invoice, org):
    """Detect and record promise-to-pay from customer message."""
    import re
    from django.utils import timezone
    from datetime import timedelta

    low = message.lower()
    if not any(k in low for k in ["will pay", "pay on", "tomorrow", "friday", "monday", "next week", "pay by"]):
        return

    # Try to extract a date — look for day names or date patterns
    promise_date = None
    today = timezone.now().date()

    day_map = {
        "tomorrow": today + timedelta(days=1),
        "monday": _next_weekday(today, 0),
        "tuesday": _next_weekday(today, 1),
        "wednesday": _next_weekday(today, 2),
        "thursday": _next_weekday(today, 3),
        "friday": _next_weekday(today, 4),
        "saturday": _next_weekday(today, 5),
        "sunday": _next_weekday(today, 6),
        "next week": today + timedelta(weeks=1),
    }
    for keyword, date_val in day_map.items():
        if keyword in low:
            promise_date = date_val
            break

    if not promise_date:
        promise_date = today + timedelta(days=3)  # Default: 3 days out

    if invoice:
        from apps.ai.models import PromiseToPay
        PromiseToPay.objects.get_or_create(
            org=org,
            conversation=conversation,
            customer=invoice.customer,
            invoice=invoice,
            defaults={
                "promise_date": promise_date,
                "amount": invoice.balance,
                "status": "pending",
            },
        )
        conversation.state = "PROMISE_MADE"
        conversation.save(update_fields=["state"])


def _check_escalation(message: str, conversation):
    """Check if the message requires human escalation."""
    low = message.lower()
    escalation_triggers = [
        "speak to", "talk to", "human", "manager", "supervisor",
        "already paid", "i paid", "fraud", "harassment", "wrong amount",
        "dispute", "complain", "not my debt",
    ]
    if any(k in low for k in escalation_triggers):
        conversation.state = "HUMAN_HANDOFF"
        conversation.save(update_fields=["state"])

        # Create escalation notification
        try:
            from apps.comms.models import CommunicationEvent
            from django.utils import timezone
            CommunicationEvent.objects.create(
                org=conversation.org,
                customer=conversation.customer,
                invoice=conversation.invoice,
                channel="email",
                template_id="escalation_alert",
                status="queued",
                scheduled_for=timezone.now(),
                idempotency_key=f"escalation-{conversation.id}",
            )
        except Exception:
            pass


def _next_weekday(d, weekday):
    """Return the next occurrence of weekday (0=Monday, 6=Sunday) after date d."""
    from datetime import timedelta
    days_ahead = weekday - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def _get_frontend_url():
    from django.conf import settings as _s
    return getattr(_s, "FRONTEND_URL", "http://localhost:5173")

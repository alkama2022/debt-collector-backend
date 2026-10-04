"""
tasks.py — Celery tasks for comms dispatch.

dispatch_queued_events: Picks up QUEUED CommunicationEvents and sends them
via the appropriate provider (Africa's Talking, Email, Mock).
Runs every 2 minutes via Celery Beat.
"""
import logging
from celery import shared_task
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

# Maximum events to process per task run (prevents runaway tasks)
BATCH_SIZE = 50


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def dispatch_queued_events(self):
    """
    Celery Beat task — runs every 2 minutes.
    Picks up CommunicationEvents with status=queued and scheduled_for <= now().
    Dispatches each event via the correct provider.
    Updates status to sending → sent | failed.
    """
    from apps.comms.models import CommunicationEvent
    from apps.comms.providers.factory import get_provider

    now = timezone.now()

    # Fetch queued events that are due
    events = (
        CommunicationEvent.objects
        .select_related("org", "invoice", "customer", "customer__preferred_language")
        .filter(
            status=CommunicationEvent.Status.QUEUED,
        )
        .filter(
            models.Q(scheduled_for__lte=now) | models.Q(scheduled_for__isnull=True)
        )
        .order_by("scheduled_for")[:BATCH_SIZE]
    )

    if not events:
        logger.debug("[dispatch_queued_events] No queued events to dispatch")
        return 0

    sent = 0
    failed = 0

    for event in events:
        # Safety: skip if invoice is paid (can happen between enqueue and dispatch)
        if event.invoice and event.invoice.balance == 0:
            event.status = CommunicationEvent.Status.CANCELLED
            event.save(update_fields=["status"])
            logger.info("[dispatch] Cancelled event %s — invoice already paid", event.id)
            continue

        # Safety: check customer opt-out
        if _is_opted_out(event):
            event.status = CommunicationEvent.Status.CANCELLED
            event.save(update_fields=["status"])
            logger.info("[dispatch] Cancelled event %s — customer opted out", event.id)
            continue

        # Mark as sending (optimistic lock pattern)
        updated = (
            CommunicationEvent.objects
            .filter(id=event.id, status=CommunicationEvent.Status.QUEUED)
            .update(status=CommunicationEvent.Status.SENDING)
        )
        if not updated:
            # Another worker grabbed it
            continue

        try:
            provider = get_provider(event.channel)

            # §21/§34 — resolve and persist the language actually used, plus
            # the exact body, *before* handing off to the provider. Recording
            # after the send would race with retries and lose the evidence.
            _record_language(event, provider)

            result = provider.send(event)

            if result.success:
                CommunicationEvent.objects.filter(id=event.id).update(
                    status=CommunicationEvent.Status.SENT,
                    provider_msg_id=result.provider_msg_id or "",
                    sent_at=timezone.now(),
                    cost_minor=result.cost_minor,
                    error_code="",
                )
                sent += 1
                logger.info(
                    "[dispatch] ✅ Sent %s event %s to customer %s | msg_id=%s",
                    event.channel, event.id, event.customer_id, result.provider_msg_id,
                )
            else:
                CommunicationEvent.objects.filter(id=event.id).update(
                    status=CommunicationEvent.Status.FAILED,
                    error_code=result.error_code[:64] if result.error_code else "PROVIDER_FAILED",
                )
                failed += 1
                logger.warning(
                    "[dispatch] ❌ Failed %s event %s | error=%s: %s",
                    event.channel, event.id, result.error_code, result.error_message,
                )

        except Exception as exc:
            CommunicationEvent.objects.filter(id=event.id).update(
                status=CommunicationEvent.Status.FAILED,
                error_code="EXCEPTION",
            )
            failed += 1
            logger.exception("[dispatch] Exception dispatching event %s: %s", event.id, exc)

    logger.info("[dispatch_queued_events] Batch done: sent=%d, failed=%d", sent, failed)
    return {"sent": sent, "failed": failed}


def _record_language(event, provider) -> None:
    """
    §21/§34 — persist which language a message went out in, and the exact text.

    Without this there is no way to answer "which language did we contact this
    customer in?", which the language dashboard and any dispute both require.
    """
    from apps.comms.models import CommunicationEvent

    try:
        lang = provider._resolve_language(event) if hasattr(provider, "_resolve_language") else "en"
    except Exception:
        lang = event.language or "en"

    source = "event_override" if event.language and event.language != "auto" else ""
    if not source:
        customer = getattr(event, "customer", None)
        pref = getattr(customer, "preferred_language", None) if customer else None
        source = "customer_preferred" if pref is not None else "org_default"

    body = ""
    try:
        body = provider._render_template(event) if hasattr(provider, "_render_template") else ""
    except Exception:
        body = ""

    CommunicationEvent.objects.filter(id=event.id).update(
        language=lang, language_source=source, body_snapshot=body[:4000]
    )
    # Keep the in-memory instance consistent for anything downstream.
    event.language = lang
    event.language_source = source


def _is_opted_out(event) -> bool:
    """Check if the customer has opted out of this communication channel."""
    from apps.comms.models import CommunicationPreference
    if not event.customer:
        return False
    try:
        pref = CommunicationPreference.objects.get(
            org=event.org,
            customer=event.customer,
            channel=event.channel,
        )
        return not pref.enabled or pref.opted_out_at is not None
    except CommunicationPreference.DoesNotExist:
        return False


@shared_task
def retry_failed_events():
    """
    Retries FAILED events that are less than 24 hours old.
    Resets them to QUEUED so dispatch_queued_events picks them up again.
    Runs every hour via Celery Beat.
    """
    from apps.comms.models import CommunicationEvent
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(hours=24)
    count = (
        CommunicationEvent.objects
        .filter(
            status=CommunicationEvent.Status.FAILED,
            created_at__gte=cutoff,
            error_code__in=["REQUEST_FAILED", "SMTP_ERROR", "EXCEPTION"],  # transient errors only
        )
        .update(status=CommunicationEvent.Status.QUEUED, error_code="")
    )
    if count:
        logger.info("[retry_failed_events] Reset %d failed events to queued", count)
    return count

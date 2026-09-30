from celery import shared_task
from django.utils import timezone
from datetime import datetime, time, timedelta, date
import logging
logger = logging.getLogger(__name__)


@shared_task
def enqueue_due_reminders():
    """
    Celery Beat task — runs every 5 minutes.
    For every org, evaluates enabled ReminderRules against open invoices.
    Creates CommunicationEvent records (status=queued) for matching invoices.
    The separate dispatch_queued_events task actually sends them.

    Logic per rule:
      - trigger=before_due + offset_days=3 → target invoices due in 3 days
      - trigger=on_due + offset_days=0    → target invoices due today
      - trigger=after_due + offset_days=7 → target invoices due 7 days ago (overdue)
    """
    from apps.invoices.models import Invoice
    from apps.tenancy.models import Organization
    from apps.comms.models import CommunicationEvent, ReminderRule, CommunicationPreference
    from apps.collections.models import CollectionPolicy

    now = timezone.now()
    today = now.date()
    total_created = 0

    for org in Organization.objects.filter(deleted_at__isnull=True):
        # Get or create collection policy for quiet hours / rate limits
        policy, _ = CollectionPolicy.objects.get_or_create(
            org=org,
            defaults={"reminder_intervals": [-7, -2, 0, 2, 7, 14]},
        )

        # Skip if currently in quiet hours
        if _is_quiet_hours(now, org.timezone):
            continue

        # Get all enabled reminder rules for this org
        rules = ReminderRule.objects.for_org(org).filter(enabled=True)
        if not rules.exists():
            continue

        for rule in rules:
            # Calculate the target invoice due date for this rule
            target_due_date = _calculate_target_date(today, rule)

            # Find open invoices with this target due date
            invoices_qs = (
                Invoice.objects
                .for_org(org)
                .filter(
                    deleted_at__isnull=True,
                    balance__gt=0,
                    status__in=["sent", "partial", "overdue"],
                )
                .select_related("customer", "customer__preferred_language")
            )

            if rule.trigger == ReminderRule.Trigger.AFTER_DUE:
                # Overdue invoices: due_date < today (past due)
                invoices_qs = invoices_qs.filter(
                    due_date=target_due_date,
                    status__in=["sent", "partial", "overdue"],
                )
                # If no exact match, fallback for after_due=0 to all overdue
                if not invoices_qs.exists() and rule.offset_days == 0:
                    invoices_qs = Invoice.objects.for_org(org).filter(
                        deleted_at__isnull=True,
                        balance__gt=0,
                        due_date__lt=today,
                        status="overdue",
                    ).select_related("customer", "customer__preferred_language")
            elif rule.trigger == ReminderRule.Trigger.BEFORE_DUE:
                invoices_qs = invoices_qs.filter(due_date=target_due_date)
            else:  # ON_DUE
                invoices_qs = invoices_qs.filter(due_date=today)

            for inv in invoices_qs[:50]:  # safety cap
                customer = inv.customer

                # Respect daily contact limit
                today_sends = CommunicationEvent.objects.filter(
                    org=org, customer=customer, created_at__date=today
                ).count()
                if today_sends >= policy.max_contacts_per_day:
                    continue

                # Respect opt-out
                try:
                    pref = CommunicationPreference.objects.get(
                        org=org, customer=customer, channel=rule.channel
                    )
                    if not pref.enabled or pref.opted_out_at:
                        continue
                except CommunicationPreference.DoesNotExist:
                    pass

                # Idempotency: one event per rule+invoice+date
                idem_key = f"{org.id}-{inv.id}-{rule.id}-{today}"
                exists = CommunicationEvent.objects.filter(
                    idempotency_key=idem_key
                ).exists()
                if exists:
                    continue

                # Determine language for the message
                lang = "en"
                if rule.language != "auto":
                    lang = rule.language
                elif customer and getattr(customer, "preferred_language", None):
                    pl = customer.preferred_language
                    lang = pl.code if hasattr(pl, "code") else str(pl)

                # Use rule template if it's a custom one, otherwise use template_id key
                template_id = rule.template if "{{" in rule.template else rule.template[:128]

                CommunicationEvent.objects.create(
                    org=org,
                    invoice=inv,
                    customer=customer,
                    channel=rule.channel,
                    template_id=template_id,
                    status="queued",
                    scheduled_for=now,
                    idempotency_key=idem_key,
                )
                total_created += 1

    logger.info("[enqueue_due_reminders] Created %d queued events", total_created)
    return total_created


def _calculate_target_date(today: date, rule) -> date:
    """Calculate the invoice due_date we're targeting for a given rule."""
    from apps.comms.models import ReminderRule
    if rule.trigger == ReminderRule.Trigger.BEFORE_DUE:
        # Rule fires N days before due — so target is today + offset_days
        return today + timedelta(days=abs(rule.offset_days))
    elif rule.trigger == ReminderRule.Trigger.AFTER_DUE:
        # Rule fires N days after due — so target was today - offset_days ago
        return today - timedelta(days=abs(rule.offset_days))
    else:  # ON_DUE
        return today


def _is_quiet_hours(dt: datetime, tz_name: str) -> bool:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        local = dt.astimezone(tz)
    except Exception:
        local = dt
    # 20:00-08:00 WAT default
    start = time(20, 0)
    end = time(8, 0)
    t = local.time()
    if start < end:
        return start <= t < end
    return t >= start or t < end


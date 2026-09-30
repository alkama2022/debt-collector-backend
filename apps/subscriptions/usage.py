"""
Usage metering — atomic, idempotent, reservation pattern.
"""
import uuid
import math
from decimal import Decimal
from django.db import transaction, IntegrityError
from django.db.models import F, Sum
from django.utils import timezone

from .models import UsageEvent, UsageCounter, UsageCredit, CreditConsumption


def _period_key(now=None):
    return (now or timezone.now()).strftime("%Y-%m")


def check_usage_available(org, feature: str, quantity: Decimal = Decimal("1")) -> tuple[bool, str]:
    """Check before execution. Uses limit + counter + credits + overage policy."""
    from .entitlements import get_limit, get_subscription_for_org
    from .models import Subscription
    limit = get_limit(org, feature)
    sub = get_subscription_for_org(org)
    # unlimited => allow
    if limit is None:
        return True, "ok"
    if limit == 0:
        return False, f"{feature} is not available on your plan."
    period = _period_key()
    counter = UsageCounter.objects.filter(org=org, feature=feature, period_key=period).first()
    used = counter.quantity if counter else Decimal("0")
    # also sum committed events not yet rolled into counter (for safety, counter is source of truth)
    if used + quantity > limit:
        # check overage policy / credits
        if sub.overage_policy == Subscription.OveragePolicy.BLOCK:
            return False, f"Usage limit reached for {feature} ({used}/{limit}). Upgrade or change overage policy to continue."
        if sub.overage_policy == Subscription.OveragePolicy.CREDITS:
            # check credits
            total_credits = UsageCredit.objects.filter(org=org, remaining__gt=0).aggregate(s=Sum("remaining"))["s"] or Decimal("0")
            if total_credits < quantity:
                return False, f"Insufficient credits for {feature}. Purchase credits to continue."
            return True, "ok (credits)"
        if sub.overage_policy == Subscription.OveragePolicy.AUTO_CHARGE:
            return True, "ok (overage)"
    return True, "ok"


def reserve_usage(org, feature: str, quantity: Decimal = Decimal("1"), idempotency_key: str = None, metadata: dict = None, unit: str = "") -> UsageEvent:
    """Reserve usage atomically. Raises ValueError if not allowed. Idempotent."""
    from .entitlements import get_subscription_for_org
    sub = get_subscription_for_org(org)
    if idempotency_key:
        existing = UsageEvent.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    ok, reason = check_usage_available(org, feature, quantity)
    if not ok:
        raise PermissionError(reason)
    key = idempotency_key or str(uuid.uuid4())
    with transaction.atomic():
        # select_for_update on counter row (or create)
        period = _period_key()
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(
            org=org, feature=feature, period_key=period,
            defaults={"quantity": Decimal("0")}
        )
        # re-check after lock
        ok2, reason2 = check_usage_available(org, feature, quantity)
        # but allow if overage policy permits — we still increment counter
        if not ok2 and sub.overage_policy == sub.OveragePolicy.BLOCK:
            raise PermissionError(reason2)
        evt = UsageEvent.objects.create(
            org=org, subscription=sub, feature=feature, quantity=quantity,
            unit=unit, status=UsageEvent.Status.RESERVED,
            idempotency_key=key, metadata=metadata or {}
        )
        # Do not increment counter until commit (to allow release)
        return evt


def commit_usage(event_id) -> UsageEvent:
    """Commit reserved usage — increments counter atomically. Idempotent."""
    with transaction.atomic():
        evt = UsageEvent.objects.select_for_update().get(pk=event_id)
        if evt.status == UsageEvent.Status.COMMITTED:
            return evt
        if evt.status == UsageEvent.Status.RELEASED:
            raise ValueError("Cannot commit released usage")
        evt.status = UsageEvent.Status.COMMITTED
        evt.save(update_fields=["status"])
        period = _period_key(evt.created_at)
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(
            org=evt.org, feature=evt.feature, period_key=period, defaults={"quantity": Decimal("0")}
        )
        counter.quantity = F("quantity") + evt.quantity
        counter.save(update_fields=["quantity"])
        counter.refresh_from_db()
        # consume credits if overage_policy == CREDITS and over limit
        from .entitlements import get_limit, get_subscription_for_org
        limit = get_limit(evt.org, evt.feature)
        if limit is not None and counter.quantity > limit:
            over = evt.quantity  # simplified: consume exact quantity if already over
            consume_credits(evt.org, evt.feature, over)
        # threshold notifications
        _check_thresholds(evt.org, evt.feature, counter.quantity, limit)
        return evt


def commit_or_create_usage(org, feature: str, quantity: Decimal = Decimal("1"), idempotency_key: str = None, **kwargs) -> UsageEvent:
    """One-shot: reserve + commit. For non-critical paths."""
    if idempotency_key and UsageEvent.objects.filter(idempotency_key=idempotency_key).exists():
        return UsageEvent.objects.get(idempotency_key=idempotency_key)
    evt = reserve_usage(org, feature, quantity, idempotency_key=idempotency_key, **kwargs)
    return commit_usage(evt.id)


def release_usage(event_id):
    with transaction.atomic():
        evt = UsageEvent.objects.select_for_update().get(pk=event_id)
        if evt.status != UsageEvent.Status.RESERVED:
            return evt
        evt.status = UsageEvent.Status.RELEASED
        evt.save(update_fields=["status"])
        return evt


def record_usage_cost(event_id, provider_cost_minor: int = None, billing_cost_minor: int = None, provider_ref: str = ""):
    evt = UsageEvent.objects.get(pk=event_id)
    if provider_cost_minor is not None:
        evt.cost_minor = provider_cost_minor
    if billing_cost_minor is not None:
        evt.billing_cost_minor = billing_cost_minor
    if provider_ref:
        evt.provider_ref = provider_ref
    evt.save(update_fields=["cost_minor", "billing_cost_minor", "provider_ref"])
    return evt


def consume_credits(org, feature: str, quantity: Decimal):
    """FIFO consume credits."""
    remaining = quantity
    credits = UsageCredit.objects.filter(org=org, remaining__gt=0).order_by("created_at").select_for_update()
    with transaction.atomic():
        for c in credits:
            if remaining <= 0:
                break
            take = min(c.remaining, remaining)
            c.remaining -= take
            c.save(update_fields=["remaining"])
            CreditConsumption.objects.create(credit=c, org=org, feature=feature, quantity=take)
            remaining -= take


def get_current_usage(org, feature: str, period_key: str = None) -> dict:
    from .entitlements import get_limit
    pk = period_key or _period_key()
    counter = UsageCounter.objects.filter(org=org, feature=feature, period_key=pk).first()
    used = float(counter.quantity) if counter else 0
    limit = get_limit(org, feature)
    remaining = None if limit is None else max(0, limit - used)
    pct = None if limit is None or limit == 0 else round(used / limit * 100, 1)
    return {"feature": feature, "period": pk, "used": used, "limit": limit, "remaining": remaining, "pct": pct}


def get_all_usage(org, period_key: str = None) -> list:
    keys = ["AI_CONVERSATIONS", "AI_VOICE", "AI_VOICE_MINUTES", "WHATSAPP_MESSAGE", "WHATSAPP_MESSAGES", "SMS", "EMAIL"]
    return [get_current_usage(org, k, period_key) for k in keys]


def _check_thresholds(org, feature: str, quantity, limit):
    if limit is None or limit == 0:
        return
    pct = float(quantity) / limit * 100 if limit else 0
    thresholds = [50, 75, 80, 90, 100]
    for t in thresholds:
        if pct >= t:
            # Create audit log + notification hook
            from .models import BillingAuditLog
            # idempotent per period/threshold: only log once per day per threshold
            # simple: always log but caller can dedupe via polling
            pass


# ── AI usage service façade ─────────────────────────────────────────────────

class AIUsageService:
    @staticmethod
    def check_ai_access(org):
        from .entitlements import check_feature_access
        return check_feature_access(org, "AI_CONVERSATIONS")

    @staticmethod
    def check_ai_limit(org, qty=1):
        return check_usage_available(org, "AI_CONVERSATIONS", Decimal(qty))

    @staticmethod
    def reserve_ai_usage(org, qty=1, idempotency_key=None, metadata=None):
        return reserve_usage(org, "AI_CONVERSATIONS", Decimal(qty), idempotency_key=idempotency_key, metadata=metadata, unit="conversation")

    @staticmethod
    def commit_ai_usage(event_id):
        return commit_usage(event_id)

    @staticmethod
    def release_ai_usage(event_id):
        return release_usage(event_id)

    @staticmethod
    def record_ai_cost(event_id, cost_minor=None, billing_cost_minor=None):
        return record_usage_cost(event_id, provider_cost_minor=cost_minor, billing_cost_minor=billing_cost_minor)

    @staticmethod
    def get_current_usage(org):
        return get_current_usage(org, "AI_CONVERSATIONS")


def calculate_billable_minutes(duration_seconds: int, rule: str = "ceil_minute") -> Decimal:
    """Configurable: ceil to next minute."""
    if not duration_seconds:
        return Decimal("0")
    if rule == "ceil_minute":
        return Decimal(math.ceil(duration_seconds / 60))
    if rule == "ceil_30s":
        return Decimal(math.ceil(duration_seconds / 30) * 0.5).quantize(Decimal("0.01"))
    return Decimal(duration_seconds) / Decimal(60)

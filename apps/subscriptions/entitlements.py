"""
Entitlement & Billing Engine — centralized authority.
Frontend only displays result. Backend is final authority.
"""
from decimal import Decimal
from django.utils import timezone
from django.db.models import Count

from .models import Plan, PlanFeature, PlanLimit, Feature, Subscription

# Canonical feature/limit keys used throughout app (must match PlanLimit.key)
LIMIT_KEYS = {
    "CUSTOMER_LIMIT": "CUSTOMER_LIMIT",
    "INVOICE_LIMIT": "INVOICE_LIMIT",
    "STAFF_LIMIT": "STAFF_LIMIT",
    "BRANCH_LIMIT": "BRANCH_LIMIT",
    "AI_CONVERSATIONS": "AI_CONVERSATIONS",
    "AI_VOICE_MINUTES": "AI_VOICE_MINUTES",
    "WHATSAPP_MESSAGES": "WHATSAPP_MESSAGES",
    "SMS_MESSAGES": "SMS_MESSAGES",
    "EMAIL_MESSAGES": "EMAIL_MESSAGES",
}

FEATURE_SLUGS = {
    "BASIC_REMINDERS": "BASIC_REMINDERS",
    "AUTOMATED_REMINDERS": "AUTOMATED_REMINDERS",
    "WHATSAPP_REMINDERS": "WHATSAPP_REMINDERS",
    "SMS_REMINDERS": "SMS_REMINDERS",
    "EMAIL_REMINDERS": "EMAIL_REMINDERS",
    "AI_CONVERSATIONS": "AI_CONVERSATIONS",
    "AI_MULTILINGUAL": "AI_MULTILINGUAL",
    "AI_VOICE": "AI_VOICE",
    "AI_PAYMENT_NEGOTIATION": "AI_PAYMENT_NEGOTIATION",
    "PAYMENT_PLANS": "PAYMENT_PLANS",
    "COLLECTION_CAMPAIGNS": "COLLECTION_CAMPAIGNS",
    "ADVANCED_REPORTS": "ADVANCED_REPORTS",
    "ADVANCED_ANALYTICS": "ADVANCED_ANALYTICS",
    "API_ACCESS": "API_ACCESS",
    "WEBHOOK_ACCESS": "WEBHOOK_ACCESS",
    "CUSTOM_INTEGRATIONS": "CUSTOM_INTEGRATIONS",
    "PRIORITY_SUPPORT": "PRIORITY_SUPPORT",
    "BRANCHES": "BRANCHES",
    "CUSTOM_POLICIES": "CUSTOM_POLICIES",
    "SSO": "SSO",
    "HUMAN_ESCALATION": "HUMAN_ESCALATION",
}


def get_subscription_for_org(org):
    """Get or create subscription for org. Uses plan_obj if available."""
    from .models import Subscription
    sub, _ = Subscription.objects.get_or_create(org=org, defaults={"plan": Subscription.PlanSlug.FREE, "status": Subscription.Status.ACTIVE})
    return sub


def get_plan_for_subscription(sub: Subscription) -> Plan | None:
    if sub.plan_obj_id:
        return sub.plan_obj
    try:
        return Plan.objects.get(slug=sub.effective_plan_slug, active=True)
    except Plan.DoesNotExist:
        return None


def get_plan_limits(plan: Plan) -> dict:
    """Return dict key -> PlanLimit for a plan."""
    if not plan:
        return {}
    return {pl.key: pl for pl in plan.limits.all()}


def is_feature_enabled(org, feature_slug: str) -> bool:
    """Check boolean entitlement via PlanFeature. If no Plan row, fallback to legacy map."""
    sub = get_subscription_for_org(org)
    plan = get_plan_for_subscription(sub)
    if plan:
        pf = PlanFeature.objects.filter(plan=plan, feature__slug=feature_slug).first()
        if pf is not None:
            return pf.enabled
        # fallback: check Feature active but no PlanFeature row => enabled by default if core?
        # treat missing row as disabled for non-free features
        return False
    # Legacy fallback map (seed values)
    legacy = _legacy_feature_map(sub.effective_plan_slug)
    return legacy.get(feature_slug, False)


def check_feature_access(org, feature_slug: str) -> tuple[bool, str]:
    """Return (allowed, reason). Checks entitlement + subscription status."""
    sub = get_subscription_for_org(org)
    if sub.status in (Subscription.Status.CANCELLED, Subscription.Status.SUSPENDED):
        return False, f"Subscription is {sub.status}. Please reactivate."
    if sub.status == Subscription.Status.PAST_DUE:
        # allow read but block write? For entitlements we block premium
        if feature_slug in ("AI_CONVERSATIONS", "AI_VOICE", "AI_MULTILINGUAL"):
            return False, "Subscription past due. Please update payment method."
    enabled = is_feature_enabled(org, feature_slug)
    if not enabled:
        return False, f"{feature_slug} is not available on your current plan ({sub.effective_plan_slug}). Upgrade to access."
    return True, "ok"


def get_limit(org, key: str) -> int | None:
    """Return limit value for org/plan. None = unlimited, 0 = blocked."""
    sub = get_subscription_for_org(org)
    plan = get_plan_for_subscription(sub)
    if plan:
        pl = PlanLimit.objects.filter(plan=plan, key=key).first()
        if pl is not None:
            return pl.limit_value
    # legacy fallback
    return _legacy_limit_map(sub.effective_plan_slug).get(key)


def get_usage_count(org, feature_key: str) -> int:
    """Live count for limit checks (customers, invoices, staff)."""
    from apps.customers.models import Customer
    from apps.invoices.models import Invoice
    from apps.tenancy.models import Membership
    key = feature_key
    if key == LIMIT_KEYS["CUSTOMER_LIMIT"]:
        return Customer.objects.for_org(org).filter(deleted_at__isnull=True).count()
    if key == LIMIT_KEYS["INVOICE_LIMIT"]:
        return Invoice.objects.for_org(org).filter(deleted_at__isnull=True).count()
    if key == LIMIT_KEYS["STAFF_LIMIT"]:
        return Membership.objects.filter(org=org).count()
    # metered counters: use UsageCounter + UsageEvent for current period
    from .models import UsageCounter
    from django.utils import timezone
    period = timezone.now().strftime("%Y-%m")
    counter = UsageCounter.objects.filter(org=org, feature=feature_key, period_key=period).first()
    if counter:
        return int(counter.quantity)
    return 0


def check_limit(org, key: str, requested: int = 1) -> tuple[bool, str, dict]:
    """Check if adding requested would exceed limit. Never deletes data on downgrade."""
    limit = get_limit(org, key)
    if limit is None:
        return True, "unlimited", {"limit": None, "used": get_usage_count(org, key), "remaining": None}
    if limit == 0:
        return False, f"{key} is not available on your current plan.", {"limit": 0, "used": 0, "remaining": 0}
    used = get_usage_count(org, key)
    if used + requested > limit:
        return False, f"Your current account contains {used} {key.lower().replace('_',' ')}, while your plan supports {limit}. Existing data remains safe, but you cannot add more until within limit. Please upgrade or reduce usage.", {"limit": limit, "used": used, "remaining": max(0, limit - used)}
    return True, "ok", {"limit": limit, "used": used, "remaining": limit - used}


def get_entitlements(org) -> dict:
    """Aggregate entitlements + usage for dashboard."""
    sub = get_subscription_for_org(org)
    plan = get_plan_for_subscription(sub)
    features = {}
    for slug in FEATURE_SLUGS.values():
        allowed, reason = check_feature_access(org, slug)
        features[slug] = {"enabled": allowed, "reason": reason}
    limits = {}
    for key in LIMIT_KEYS.values():
        limit = get_limit(org, key)
        used = get_usage_count(org, key)
        remaining = None if limit is None else max(0, limit - used)
        pct = None if limit is None or limit == 0 else min(100, round(used / limit * 100))
        limits[key] = {"limit": limit, "used": used, "remaining": remaining, "pct": pct}
    # usage counters for metered features current month
    usage = get_monthly_usage_summary(org)
    return {
        "subscription": {
            "id": str(sub.id),
            "plan": sub.effective_plan_slug,
            "plan_name": plan.name if plan else sub.plan,
            "status": sub.status,
            "currency": sub.currency,
            "price": str(plan.price) if plan else "0.00",
            "billing_interval": sub.billing_interval,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "trial_end": sub.trial_end,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "overage_policy": sub.overage_policy,
        },
        "features": features,
        "limits": limits,
        "usage": usage,
    }


def get_monthly_usage_summary(org) -> dict:
    from .models import UsageEvent
    from django.utils import timezone
    from django.db.models import Sum
    period = timezone.now().strftime("%Y-%m")
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    qs = UsageEvent.objects.filter(org=org, created_at__gte=start, status="committed")
    summary = {}
    for feat in ["AI_CONVERSATIONS", "AI_VOICE", "WHATSAPP_MESSAGE", "SMS", "EMAIL", "WHATSAPP_MESSAGES", "AI_VOICE_MINUTES"]:
        qty = qs.filter(feature=feat).aggregate(s=Sum("quantity"))["s"] or 0
        cost = qs.filter(feature=feat).aggregate(s=Sum("cost_minor"))["s"] or 0
        summary[feat] = {"quantity": float(qty), "cost_minor": int(cost)}
    # aliases
    summary["AI_CONVERSATIONS_TOTAL"] = summary.get("AI_CONVERSATIONS", {})
    return summary


# ── legacy fallbacks (seed hypotheses) ───────────────────────────────────────

def _legacy_feature_map(plan_slug: str) -> dict:
    # Mirrors spec suggested plan capabilities
    free = {
        "BASIC_REMINDERS": True, "AUTOMATED_REMINDERS": False, "WHATSAPP_REMINDERS": False,
        "SMS_REMINDERS": False, "EMAIL_REMINDERS": False,
        "AI_CONVERSATIONS": False, "AI_MULTILINGUAL": False, "AI_VOICE": False, "AI_PAYMENT_NEGOTIATION": False,
        "PAYMENT_PLANS": False, "COLLECTION_CAMPAIGNS": False, "ADVANCED_REPORTS": False, "ADVANCED_ANALYTICS": False,
        "API_ACCESS": False, "WEBHOOK_ACCESS": False, "CUSTOM_INTEGRATIONS": False, "PRIORITY_SUPPORT": False,
        "BRANCHES": False, "CUSTOM_POLICIES": False, "SSO": False, "HUMAN_ESCALATION": False,
    }
    starter = {**free, "BASIC_REMINDERS": True, "WHATSAPP_REMINDERS": True, "SMS_REMINDERS": True, "EMAIL_REMINDERS": True, "AI_CONVERSATIONS": True, "AI_MULTILINGUAL": False, "ADVANCED_REPORTS": False}
    business = {**starter, "AUTOMATED_REMINDERS": True, "WHATSAPP_REMINDERS": True, "AI_CONVERSATIONS": True, "AI_MULTILINGUAL": True, "AI_PAYMENT_NEGOTIATION": True, "PAYMENT_PLANS": True, "COLLECTION_CAMPAIGNS": True, "ADVANCED_REPORTS": True, "ADVANCED_ANALYTICS": True, "HUMAN_ESCALATION": True}
    professional = {**business, "AI_VOICE": True, "API_ACCESS": True, "WEBHOOK_ACCESS": True, "PRIORITY_SUPPORT": True, "BRANCHES": True, "CUSTOM_POLICIES": True}
    enterprise = {**professional, "CUSTOM_INTEGRATIONS": True, "SSO": True}
    m = {"free": free, "starter": starter, "business": business, "professional": professional, "enterprise": enterprise}
    return m.get(plan_slug, free)

def _legacy_limit_map(plan_slug: str) -> dict:
    limits = {
        "free": {"CUSTOMER_LIMIT": 50, "INVOICE_LIMIT": 50, "STAFF_LIMIT": 1, "BRANCH_LIMIT": 1, "AI_CONVERSATIONS": 10, "AI_VOICE_MINUTES": 0, "WHATSAPP_MESSAGES": 20},
        "starter": {"CUSTOMER_LIMIT": 500, "INVOICE_LIMIT": None, "STAFF_LIMIT": 3, "BRANCH_LIMIT": 1, "AI_CONVERSATIONS": 100, "AI_VOICE_MINUTES": 0, "WHATSAPP_MESSAGES": 500},
        "business": {"CUSTOMER_LIMIT": 2500, "INVOICE_LIMIT": None, "STAFF_LIMIT": 10, "BRANCH_LIMIT": 1, "AI_CONVERSATIONS": 1000, "AI_VOICE_MINUTES": 0, "WHATSAPP_MESSAGES": 5000},
        "professional": {"CUSTOMER_LIMIT": 10000, "INVOICE_LIMIT": None, "STAFF_LIMIT": 25, "BRANCH_LIMIT": 5, "AI_CONVERSATIONS": 5000, "AI_VOICE_MINUTES": 100, "WHATSAPP_MESSAGES": 20000},
        "enterprise": {"CUSTOMER_LIMIT": None, "INVOICE_LIMIT": None, "STAFF_LIMIT": None, "BRANCH_LIMIT": None, "AI_CONVERSATIONS": None, "AI_VOICE_MINUTES": None, "WHATSAPP_MESSAGES": None},
    }
    return limits.get(plan_slug, limits["free"])

import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings

# ──────────────────────────────────────────────────────────────────────────────
# Feature Registry — centralized, DB-backed but seeded with canonical slugs
# ──────────────────────────────────────────────────────────────────────────────

class Feature(models.Model):
    """Canonical feature registry. Slugs are stable identifiers used by code."""
    class Category(models.TextChoices):
        CORE = "core", "Core"
        REMINDERS = "reminders", "Reminders"
        AI = "ai", "AI"
        VOICE = "voice", "Voice"
        COLLECTIONS = "collections", "Collections"
        ANALYTICS = "analytics", "Analytics"
        INTEGRATIONS = "integrations", "Integrations"
        SUPPORT = "support", "Support"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True, max_length=64)  # e.g. AI_CONVERSATIONS
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.CORE)
    metered = models.BooleanField(default=False, help_text="If true, usage is metered")
    unit = models.CharField(max_length=32, blank=True, default="", help_text="e.g. conversation, minute, message")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_features"
        ordering = ["category", "slug"]

    def __str__(self):
        return self.slug

# ──────────────────────────────────────────────────────────────────────────────
# Plan — configuration-driven, not hard-coded. Prices are hypotheses.
# ──────────────────────────────────────────────────────────────────────────────

class Plan(models.Model):
    class Interval(models.TextChoices):
        MONTH = "month", "Monthly"
        YEAR = "year", "Yearly"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=64)  # e.g. Starter
    slug = models.SlugField(unique=True, max_length=32)  # free/starter/business/...
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="NGN")
    billing_interval = models.CharField(max_length=16, choices=Interval.choices, default=Interval.MONTH)
    active = models.BooleanField(default=True)
    public = models.BooleanField(default=True, help_text="Visible on pricing page")
    trial_days = models.IntegerField(default=0)
    sort_order = models.IntegerField(default=0)
    is_enterprise = models.BooleanField(default=False, help_text="Custom negotiated plan")
    stripe_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_plans"
        ordering = ["sort_order", "price"]

    def __str__(self):
        return f"{self.name} ({self.currency} {self.price}/{self.billing_interval})"

class PlanFeature(models.Model):
    """Which features a plan grants (boolean entitlements)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="plan_features")
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="plan_features")
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_plan_features"
        unique_together = ("plan", "feature")

class PlanLimit(models.Model):
    """Configurable limits per plan per metered dimension."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="limits")
    # feature slug or dimension key e.g. CUSTOMER_LIMIT, AI_CONVERSATIONS, AI_VOICE_MINUTES, STAFF_LIMIT, WHATSAPP_MESSAGES
    key = models.CharField(max_length=64, help_text="Limit key e.g. CUSTOMER_LIMIT, AI_CONVERSATIONS, STAFF_LIMIT")
    limit_value = models.IntegerField(null=True, blank=True, help_text="Null = unlimited, 0 = not allowed")
    period = models.CharField(max_length=16, default="month", help_text="month / billing_period / lifetime")
    overage_allowed = models.BooleanField(default=False)
    overage_price_minor = models.IntegerField(null=True, blank=True, help_text="Price per unit overage in minor units")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_plan_limits"
        unique_together = ("plan", "key")

# ──────────────────────────────────────────────────────────────────────────────
# Subscription — extended lifecycle
# ──────────────────────────────────────────────────────────────────────────────

class Subscription(models.Model):
    class PlanSlug(models.TextChoices):
        FREE = "free", "Free"
        STARTER = "starter", "Starter"
        BUSINESS = "business", "Business"
        PROFESSIONAL = "professional", "Professional"
        ENTERPRISE = "enterprise", "Enterprise"

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past Due"
        GRACE_PERIOD = "grace_period", "Grace Period"
        PAUSED = "paused", "Paused"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"
        INCOMPLETE = "incomplete", "Incomplete"
        UPGRADED = "upgraded", "Upgraded"
        DOWNGRADED = "downgraded", "Downgraded"

    class OveragePolicy(models.TextChoices):
        BLOCK = "block", "Block additional usage"
        CREDITS = "credits", "Consume credits"
        AUTO_CHARGE = "auto_charge", "Automatic overage billing"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.OneToOneField("tenancy.Organization", on_delete=models.CASCADE, related_name="subscription")
    # legacy slug for quick check; canonical source is plan FK
    plan = models.CharField(max_length=16, choices=PlanSlug.choices, default=PlanSlug.FREE)
    plan_obj = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="subscriptions")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    currency = models.CharField(max_length=3, default="NGN")
    billing_interval = models.CharField(max_length=16, default="month")
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    grace_until = models.DateTimeField(null=True, blank=True)
    overage_policy = models.CharField(max_length=16, choices=OveragePolicy.choices, default=OveragePolicy.BLOCK)
    provider = models.CharField(max_length=32, blank=True, default="", help_text="paystack/flutterwave/manual")
    provider_customer_id = models.CharField(max_length=128, blank=True, default="")
    provider_subscription_id = models.CharField(max_length=128, blank=True, default="")
    mrr_minor = models.IntegerField(default=0, help_text="MRR in minor units for admin dashboard")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions"

    def __str__(self):
        return f"{self.org} - {self.plan} ({self.status})"

    @property
    def effective_plan_slug(self):
        if self.plan_obj:
            return self.plan_obj.slug
        return self.plan

    def is_active(self):
        return self.status in (self.Status.ACTIVE, self.Status.TRIALING, self.Status.GRACE_PERIOD)

class SubscriptionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="events")
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="billing_events")
    event_type = models.CharField(max_length=32, help_text="SubscriptionCreated, Upgraded, Downgraded, Cancelled, Renewed, etc")
    from_plan = models.CharField(max_length=32, blank=True, default="")
    to_plan = models.CharField(max_length=32, blank=True, default="")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_subscription_events"
        ordering = ["-created_at"]

# ──────────────────────────────────────────────────────────────────────────────
# Usage metering — atomic, idempotent
# ──────────────────────────────────────────────────────────────────────────────

class UsageEvent(models.Model):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        COMMITTED = "committed", "Committed"
        RELEASED = "released", "Released"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="usage_events")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_events")
    feature = models.CharField(max_length=64, help_text="Feature slug e.g. AI_CONVERSATIONS, AI_VOICE, WHATSAPP_MESSAGE")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("1"))
    unit = models.CharField(max_length=32, blank=True, default="")
    provider = models.CharField(max_length=32, blank=True, default="")
    cost_minor = models.IntegerField(null=True, blank=True, help_text="Provider cost in minor units")
    billing_cost_minor = models.IntegerField(null=True, blank=True, help_text="Billed to customer in minor units")
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMMITTED)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # extended fields for voice
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)
    billable_minutes = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    channel = models.CharField(max_length=16, blank=True, default="")
    message_type = models.CharField(max_length=32, blank=True, default="")
    provider_ref = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "billing_usage_events"
        indexes = [
            models.Index(fields=["org", "feature"]),
            models.Index(fields=["org", "created_at"]),
            models.Index(fields=["idempotency_key"]),
        ]

class UsageCounter(models.Model):
    """Aggregated counter per org/feature/period for fast limit checks."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="usage_counters")
    feature = models.CharField(max_length=64)
    period_key = models.CharField(max_length=16, help_text="YYYY-MM")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    limit_value = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_usage_counters"
        unique_together = ("org", "feature", "period_key")

# ──────────────────────────────────────────────────────────────────────────────
# Voice billing detail
# ──────────────────────────────────────────────────────────────────────────────

class VoiceBillingRecord(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="voice_billing_records")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True)
    call_id = models.CharField(max_length=128, blank=True, default="")
    duration_seconds = models.IntegerField(null=True, blank=True)
    billable_minutes = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    provider = models.CharField(max_length=32, blank=True, default="")
    provider_cost_minor = models.IntegerField(null=True, blank=True)
    billing_cost_minor = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_voice_records"

# ──────────────────────────────────────────────────────────────────────────────
# Credits
# ──────────────────────────────────────────────────────────────────────────────

class UsageCredit(models.Model):
    class CreditType(models.TextChoices):
        AI = "ai", "AI Credits"
        VOICE = "voice", "Voice Credits"
        MESSAGING = "messaging", "Messaging Credits"
        GENERAL = "general", "General"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="usage_credits")
    type = models.CharField(max_length=16, choices=CreditType.choices, default=CreditType.GENERAL)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    remaining = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_transaction = models.ForeignKey("BillingTransaction", on_delete=models.SET_NULL, null=True, blank=True, related_name="credits")
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_usage_credits"

class CreditConsumption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit = models.ForeignKey(UsageCredit, on_delete=models.CASCADE, related_name="consumptions")
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="credit_consumptions")
    feature = models.CharField(max_length=64, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_credit_consumptions"

# ──────────────────────────────────────────────────────────────────────────────
# Billing invoices (subscription billing, not customer invoices)
# ──────────────────────────────────────────────────────────────────────────────

class BillingInvoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        VOID = "void", "Void"
        UNCOLLECTIBLE = "uncollectible", "Uncollectible"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="billing_invoices")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="billing_invoices")
    invoice_number = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    amount_minor = models.IntegerField(help_text="Amount in minor units")
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=32, blank=True, default="")
    provider_invoice_id = models.CharField(max_length=128, blank=True, default="")
    provider_ref = models.CharField(max_length=128, blank=True, default="")
    pdf_url = models.URLField(blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_invoices"
        ordering = ["-created_at"]

class BillingTransaction(models.Model):
    class Type(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        USAGE = "usage", "Usage"
        CREDIT = "credit", "Credit Purchase"
        OVERAGE = "overage", "Overage"
        REFUND = "refund", "Refund"
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="billing_transactions")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.SUBSCRIPTION)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_minor = models.IntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    provider = models.CharField(max_length=32, blank=True, default="")
    provider_ref = models.CharField(max_length=128, blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_transactions"
        ordering = ["-created_at"]

class PaymentMethod(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="payment_methods")
    provider = models.CharField(max_length=32, blank=True, default="")
    brand = models.CharField(max_length=32, blank=True, default="")
    last4 = models.CharField(max_length=4, blank=True, default="")
    exp_month = models.IntegerField(null=True, blank=True)
    exp_year = models.IntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    provider_ref = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_payment_methods"

# ──────────────────────────────────────────────────────────────────────────────
# Coupons
# ──────────────────────────────────────────────────────────────────────────────

class Coupon(models.Model):
    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage"
        FIXED = "fixed", "Fixed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    discount_type = models.CharField(max_length=16, choices=DiscountType.choices, default=DiscountType.PERCENTAGE)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, help_text="Percent 0-100 or fixed amount")
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    max_redemptions = models.IntegerField(null=True, blank=True)
    times_redeemed = models.IntegerField(default=0)
    eligible_plans = models.JSONField(default=list, blank=True, help_text="List of plan slugs or empty for all")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_coupons"

class CouponRedemption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="redemptions")
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="coupon_redemptions")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True, blank=True)
    discount_amount_minor = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_coupon_redemptions"
        unique_together = ("coupon", "org")

# ──────────────────────────────────────────────────────────────────────────────
# Referral / Affiliate scaffolding
# ──────────────────────────────────────────────────────────────────────────────

class Referral(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONVERTED = "converted", "Converted"
        REWARDED = "rewarded", "Rewarded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    referrer_org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="referrals_made")
    referred_org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="referrals_received", null=True, blank=True)
    code = models.CharField(max_length=32, unique=True)
    email = models.EmailField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reward_granted = models.BooleanField(default=False)
    reward_days = models.IntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_referrals"

class AffiliateLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, related_name="affiliate_links", null=True, blank=True)
    code = models.CharField(max_length=32, unique=True)
    affiliate_email = models.EmailField(blank=True, default="")
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"))
    total_earned_minor = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_affiliate_links"

# ──────────────────────────────────────────────────────────────────────────────
# Webhook / Audit
# ──────────────────────────────────────────────────────────────────────────────

class WebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32)
    event_id = models.CharField(max_length=128, unique=True, help_text="Provider event id for idempotency")
    event_type = models.CharField(max_length=64, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_webhook_events"
        ordering = ["-created_at"]

class BillingAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="billing_audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=64)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_audit_logs"
        ordering = ["-created_at"]

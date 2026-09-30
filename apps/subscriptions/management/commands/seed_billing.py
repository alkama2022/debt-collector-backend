from django.core.management.base import BaseCommand
from decimal import Decimal

FEATURES = [
    ("CUSTOMER_LIMIT", "Customer limit", "core", False, "customers"),
    ("INVOICE_LIMIT", "Invoice limit", "core", False, ""),
    ("STAFF_LIMIT", "Staff limit", "core", False, "seats"),
    ("BRANCH_LIMIT", "Branch limit", "core", False, "branches"),
    ("BASIC_REMINDERS", "Basic reminders", "reminders", False, ""),
    ("AUTOMATED_REMINDERS", "Automated reminders", "reminders", False, ""),
    ("WHATSAPP_REMINDERS", "WhatsApp reminders", "reminders", False, ""),
    ("SMS_REMINDERS", "SMS reminders", "reminders", False, ""),
    ("EMAIL_REMINDERS", "Email reminders", "reminders", False, ""),
    ("AI_CONVERSATIONS", "AI conversations", "ai", True, "conversations"),
    ("AI_MULTILINGUAL", "Multilingual AI", "ai", False, ""),
    ("AI_VOICE", "AI voice calls", "voice", True, "minutes"),
    ("AI_PAYMENT_NEGOTIATION", "AI payment negotiation", "ai", False, ""),
    ("PAYMENT_PLANS", "Payment plans", "collections", False, ""),
    ("COLLECTION_CAMPAIGNS", "Collection campaigns", "collections", False, ""),
    ("ADVANCED_REPORTS", "Advanced reports", "analytics", False, ""),
    ("ADVANCED_ANALYTICS", "Advanced analytics", "analytics", False, ""),
    ("API_ACCESS", "API access", "integrations", False, ""),
    ("WEBHOOK_ACCESS", "Webhook access", "integrations", False, ""),
    ("CUSTOM_INTEGRATIONS", "Custom integrations", "integrations", False, ""),
    ("PRIORITY_SUPPORT", "Priority support", "support", False, ""),
    ("BRANCHES", "Multiple branches", "core", False, ""),
    ("CUSTOM_POLICIES", "Custom collection policies", "collections", False, ""),
    ("SSO", "SSO", "other", False, ""),
    ("HUMAN_ESCALATION", "Human escalation", "ai", False, ""),
    ("WHATSAPP_MESSAGES", "WhatsApp messages", "reminders", True, "messages"),
    ("SMS_MESSAGES", "SMS messages", "reminders", True, "messages"),
]

PLAN_DEFS = [
    {"slug": "free", "name": "Free", "price": "0", "currency": "NGN", "sort_order": 1, "trial_days": 0, "public": True},
    {"slug": "starter", "name": "Starter", "price": "5000", "currency": "NGN", "sort_order": 2, "trial_days": 14, "public": True},
    {"slug": "business", "name": "Business", "price": "12000", "currency": "NGN", "sort_order": 3, "trial_days": 14, "public": True},
    {"slug": "professional", "name": "Professional", "price": "25000", "currency": "NGN", "sort_order": 4, "trial_days": 14, "public": True},
    {"slug": "enterprise", "name": "Enterprise", "price": "0", "currency": "NGN", "sort_order": 5, "trial_days": 0, "public": True, "is_enterprise": True},
]

PLAN_LIMITS = {
    "free": {"CUSTOMER_LIMIT": 50, "INVOICE_LIMIT": 50, "STAFF_LIMIT": 1, "BRANCH_LIMIT": 1, "AI_CONVERSATIONS": 10, "AI_VOICE_MINUTES": 0, "WHATSAPP_MESSAGES": 20},
    "starter": {"CUSTOMER_LIMIT": 500, "INVOICE_LIMIT": None, "STAFF_LIMIT": 3, "BRANCH_LIMIT": 1, "AI_CONVERSATIONS": 100, "AI_VOICE_MINUTES": 0, "WHATSAPP_MESSAGES": 500},
    "business": {"CUSTOMER_LIMIT": 2500, "INVOICE_LIMIT": None, "STAFF_LIMIT": 10, "BRANCH_LIMIT": 1, "AI_CONVERSATIONS": 1000, "AI_VOICE_MINUTES": 0, "WHATSAPP_MESSAGES": 5000},
    "professional": {"CUSTOMER_LIMIT": 10000, "INVOICE_LIMIT": None, "STAFF_LIMIT": 25, "BRANCH_LIMIT": 5, "AI_CONVERSATIONS": 5000, "AI_VOICE_MINUTES": 100, "WHATSAPP_MESSAGES": 20000},
    "enterprise": {"CUSTOMER_LIMIT": None, "INVOICE_LIMIT": None, "STAFF_LIMIT": None, "BRANCH_LIMIT": None, "AI_CONVERSATIONS": None, "AI_VOICE_MINUTES": None, "WHATSAPP_MESSAGES": None},
}

PLAN_FEATURES = {
    "free": {"BASIC_REMINDERS": True},
    "starter": {"BASIC_REMINDERS": True, "WHATSAPP_REMINDERS": True, "SMS_REMINDERS": True, "EMAIL_REMINDERS": True, "AI_CONVERSATIONS": True},
    "business": {"BASIC_REMINDERS": True, "AUTOMATED_REMINDERS": True, "WHATSAPP_REMINDERS": True, "SMS_REMINDERS": True, "EMAIL_REMINDERS": True, "AI_CONVERSATIONS": True, "AI_MULTILINGUAL": True, "AI_PAYMENT_NEGOTIATION": True, "PAYMENT_PLANS": True, "COLLECTION_CAMPAIGNS": True, "ADVANCED_REPORTS": True, "ADVANCED_ANALYTICS": True, "HUMAN_ESCALATION": True},
    "professional": {"BASIC_REMINDERS": True, "AUTOMATED_REMINDERS": True, "WHATSAPP_REMINDERS": True, "SMS_REMINDERS": True, "EMAIL_REMINDERS": True, "AI_CONVERSATIONS": True, "AI_MULTILINGUAL": True, "AI_VOICE": True, "AI_PAYMENT_NEGOTIATION": True, "PAYMENT_PLANS": True, "COLLECTION_CAMPAIGNS": True, "ADVANCED_REPORTS": True, "ADVANCED_ANALYTICS": True, "API_ACCESS": True, "WEBHOOK_ACCESS": True, "PRIORITY_SUPPORT": True, "BRANCHES": True, "CUSTOM_POLICIES": True, "HUMAN_ESCALATION": True},
    "enterprise": {"BASIC_REMINDERS": True, "AUTOMATED_REMINDERS": True, "WHATSAPP_REMINDERS": True, "SMS_REMINDERS": True, "EMAIL_REMINDERS": True, "AI_CONVERSATIONS": True, "AI_MULTILINGUAL": True, "AI_VOICE": True, "AI_PAYMENT_NEGOTIATION": True, "PAYMENT_PLANS": True, "COLLECTION_CAMPAIGNS": True, "ADVANCED_REPORTS": True, "ADVANCED_ANALYTICS": True, "API_ACCESS": True, "WEBHOOK_ACCESS": True, "CUSTOM_INTEGRATIONS": True, "PRIORITY_SUPPORT": True, "BRANCHES": True, "CUSTOM_POLICIES": True, "SSO": True, "HUMAN_ESCALATION": True},
}

class Command(BaseCommand):
    help = "Seed billing: features, plans, limits, WELCOME50 coupon"
    def handle(self, *args, **options):
        from apps.subscriptions.models import Feature, Plan, PlanFeature, PlanLimit, Coupon
        for slug, name, cat, metered, unit in FEATURES:
            Feature.objects.get_or_create(slug=slug, defaults={"name": name, "category": cat, "metered": metered, "unit": unit})
        self.stdout.write(self.style.SUCCESS(f"Seeded {Feature.objects.count()} features"))
        for pd in PLAN_DEFS:
            plan, created = Plan.objects.get_or_create(slug=pd["slug"], defaults={
                "name": pd["name"], "price": Decimal(pd["price"]), "currency": pd["currency"],
                "sort_order": pd["sort_order"], "trial_days": pd["trial_days"], "public": pd["public"], "is_enterprise": pd.get("is_enterprise", False),
                "description": f"{pd['name']} plan — NGN {pd['price']}/month"
            })
            if not created:
                plan.price = Decimal(pd["price"])
                plan.save(update_fields=["price"])
            # limits
            limits = PLAN_LIMITS.get(pd["slug"], {})
            for k, v in limits.items():
                PlanLimit.objects.update_or_create(plan=plan, key=k, defaults={"limit_value": v, "period": "month"})
            # features
            feats = PLAN_FEATURES.get(pd["slug"], {})
            for slug, enabled in feats.items():
                try:
                    feat = Feature.objects.get(slug=slug)
                    PlanFeature.objects.update_or_create(plan=plan, feature=feat, defaults={"enabled": enabled})
                except Feature.DoesNotExist:
                    pass
            self.stdout.write(f"Plan {plan.slug}: {plan.price} — limits {len(limits)} features {len(feats)}")
        Coupon.objects.get_or_create(code="WELCOME50", defaults={"discount_type": "percentage", "discount_value": Decimal("50.00"), "max_redemptions": 1000, "eligible_plans": ["starter","business"], "active": True})
        Coupon.objects.get_or_create(code="BUSINESS30", defaults={"discount_type": "percentage", "discount_value": Decimal("30"), "active": True})
        self.stdout.write(self.style.SUCCESS("Seeded coupons WELCOME50 (50% off) + BUSINESS30"))
        self.stdout.write(self.style.SUCCESS("Billing seed complete."))

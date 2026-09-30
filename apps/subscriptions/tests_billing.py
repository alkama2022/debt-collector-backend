"""
Tests for monetization system per spec §43.
Run: python manage.py test apps.subscriptions.tests_billing -v 2
"""
from decimal import Decimal
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from apps.tenancy.models import Organization, Membership
from apps.subscriptions.models import Plan, Subscription, UsageEvent
from apps.subscriptions.entitlements import check_feature_access, check_limit, get_entitlements
from apps.subscriptions.usage import commit_or_create_usage, reserve_usage, commit_usage, release_usage, get_current_usage
from apps.customers.models import Customer

User = get_user_model()

class BillingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@test.com", password="pass12345")
        self.org = Organization.objects.create(slug="test-org", name="Test Org")
        Membership.objects.create(org=self.org, user=self.user, role="owner")
        # ensure seed plans
        from django.core.management import call_command
        call_command("seed_billing", verbosity=0)
        # set subscription to business
        from apps.subscriptions.entitlements import get_subscription_for_org
        self.sub = get_subscription_for_org(self.org)
        plan = Plan.objects.get(slug="business")
        self.sub.plan = "business"
        self.sub.plan_obj = plan
        self.sub.status = Subscription.Status.ACTIVE
        self.sub.save()

    def test_entitlement_business_has_ai(self):
        allowed, _ = check_feature_access(self.org, "AI_CONVERSATIONS")
        self.assertTrue(allowed)
        allowed2, _ = check_feature_access(self.org, "AI_VOICE")
        self.assertFalse(allowed2)  # business no voice

    def test_entitlement_professional_has_voice(self):
        plan = Plan.objects.get(slug="professional")
        self.sub.plan = "professional"
        self.sub.plan_obj = plan
        self.sub.save()
        allowed, _ = check_feature_access(self.org, "AI_VOICE")
        self.assertTrue(allowed)

    def test_customer_limit_enforced(self):
        # business limit 2500
        allowed, _, info = check_limit(self.org, "CUSTOMER_LIMIT", 1)
        self.assertTrue(allowed)
        # set to free (50)
        plan = Plan.objects.get(slug="free")
        self.sub.plan = "free"
        self.sub.plan_obj = plan
        self.sub.save()
        # create 50 customers
        for i in range(50):
            Customer.objects.create(org=self.org, customer_code=f"CUS-{i}", name=f"C{i}")
        allowed, reason, info = check_limit(self.org, "CUSTOMER_LIMIT", 1)
        self.assertFalse(allowed)
        self.assertIn(" Existing data", reason)  # downgrade messaging

    def test_usage_metering_idempotent(self):
        evt = commit_or_create_usage(self.org, "AI_CONVERSATIONS", Decimal(1), idempotency_key="idem-123")
        evt2 = commit_or_create_usage(self.org, "AI_CONVERSATIONS", Decimal(1), idempotency_key="idem-123")
        self.assertEqual(str(evt.id), str(evt2.id))
        counter = get_current_usage(self.org, "AI_CONVERSATIONS")
        self.assertEqual(counter["used"], 1.0)

    def test_usage_reservation_rollback(self):
        evt = reserve_usage(self.org, "AI_CONVERSATIONS", Decimal(1), idempotency_key="res-1")
        self.assertEqual(evt.status, "reserved")
        # counter not incremented yet
        self.assertEqual(get_current_usage(self.org, "AI_CONVERSATIONS")["used"], 0)
        commit_usage(evt.id)
        self.assertEqual(get_current_usage(self.org, "AI_CONVERSATIONS")["used"], 1.0)
        # duplicate commit idempotent
        commit_usage(evt.id)
        self.assertEqual(get_current_usage(self.org, "AI_CONVERSATIONS")["used"], 1.0)

    def test_voice_metered_separately(self):
        from apps.subscriptions.usage import calculate_billable_minutes
        self.assertEqual(calculate_billable_minutes(61), Decimal(2))
        self.assertEqual(calculate_billable_minutes(60), Decimal(1))

    def test_tenant_isolation(self):
        org2 = Organization.objects.create(slug="org2", name="Org2")
        user2 = User.objects.create_user(email="other@test.com", password="pass12345")
        Membership.objects.create(org=org2, user=user2, role="owner")
        from apps.subscriptions.entitlements import get_subscription_for_org
        sub2 = get_subscription_for_org(org2)
        plan = Plan.objects.get(slug="free")
        sub2.plan = "free"
        sub2.plan_obj = plan
        sub2.save()
        # org1 business has AI, org2 free does not
        self.assertTrue(check_feature_access(self.org, "AI_CONVERSATIONS")[0])
        self.assertFalse(check_feature_access(org2, "AI_CONVERSATIONS")[0])

    def test_overage_block(self):
        plan = Plan.objects.get(slug="free")  # 10 AI conversations
        self.sub.plan = "free"
        self.sub.plan_obj = plan
        self.sub.overage_policy = Subscription.OveragePolicy.BLOCK
        self.sub.save()
        for i in range(10):
            commit_or_create_usage(self.org, "AI_CONVERSATIONS", Decimal(1), idempotency_key=f"free-{i}")
        # 11th should be blocked
        with self.assertRaises(PermissionError):
            commit_or_create_usage(self.org, "AI_CONVERSATIONS", Decimal(1), idempotency_key="free-10")

    def test_webhook_idempotency(self):
        from apps.subscriptions.models import WebhookEvent
        from apps.subscriptions.views import _process_webhook_event
        payload = {"data": {"reference": "ref123", "status": "success"}}
        we = WebhookEvent.objects.create(provider="paystack", event_id="evt-1", event_type="charge.success", payload=payload)
        # second with same event_id should be rejected as already_processed via view logic (we test model uniqueness)
        with self.assertRaises(Exception):
            WebhookEvent.objects.create(provider="paystack", event_id="evt-1", event_type="charge.success", payload=payload)

    def test_downgrade_preserves_data(self):
        # create 100 customers on business (limit 2500)
        for i in range(100):
            Customer.objects.create(org=self.org, customer_code=f"DOWN-{i}", name=f"D{i}")
        # downgrade to starter (500 limit) — still within, should succeed
        plan = Plan.objects.get(slug="starter")
        self.sub.plan = "starter"
        self.sub.plan_obj = plan
        self.sub.save()
        self.assertEqual(Customer.objects.filter(org=self.org).count(), 100)
        # downgrade to free (50) — over limit, but data not deleted
        plan2 = Plan.objects.get(slug="free")
        self.sub.plan = "free"
        self.sub.plan_obj = plan2
        self.sub.save()
        self.assertEqual(Customer.objects.filter(org=self.org).count(), 100)
        allowed, reason, _ = check_limit(self.org, "CUSTOMER_LIMIT", 1)
        self.assertFalse(allowed)
        self.assertIn(" Existing data", reason)

    def test_coupon_validation(self):
        from apps.subscriptions.models import Coupon
        c = Coupon.objects.get(code="WELCOME50")
        self.assertTrue(c.active)
        self.assertEqual(c.discount_type, "percentage")

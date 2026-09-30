from rest_framework import serializers
from .models import Subscription, Plan, PlanFeature, PlanLimit, Feature, BillingInvoice, BillingTransaction, UsageEvent, UsageCredit, Coupon, PaymentMethod, Referral

class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ["id", "slug", "name", "description", "category", "metered", "unit", "active"]

class PlanLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanLimit
        fields = ["id", "key", "limit_value", "period", "overage_allowed", "overage_price_minor"]

class PlanFeatureSerializer(serializers.ModelSerializer):
    feature = FeatureSerializer(read_only=True)
    class Meta:
        model = PlanFeature
        fields = ["id", "feature", "enabled"]

class PlanSerializer(serializers.ModelSerializer):
    limits = PlanLimitSerializer(many=True, read_only=True)
    plan_features = PlanFeatureSerializer(many=True, read_only=True)
    class Meta:
        model = Plan
        fields = ["id","name","slug","description","price","currency","billing_interval","active","public","trial_days","sort_order","is_enterprise","limits","plan_features"]

class SubscriptionSerializer(serializers.ModelSerializer):
    plan_obj = PlanSerializer(read_only=True)
    effective_plan = serializers.CharField(source="effective_plan_slug", read_only=True)
    class Meta:
        model = Subscription
        fields = ["id","org","plan","plan_obj","effective_plan","status","currency","billing_interval","current_period_start","current_period_end","trial_start","trial_end","cancel_at_period_end","cancelled_at","grace_until","overage_policy","provider","provider_subscription_id","created_at","updated_at"]
        read_only_fields = ["id","org","created_at","updated_at","provider_subscription_id","provider"]

class BillingInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingInvoice
        fields = ["id","org","subscription","invoice_number","status","amount","currency","amount_minor","period_start","period_end","provider","provider_invoice_id","paid_at","created_at"]

class BillingTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingTransaction
        fields = ["id","org","subscription","type","amount","amount_minor","currency","provider","provider_ref","idempotency_key","status","metadata","created_at"]
        read_only_fields = ["id","created_at"]

class UsageEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageEvent
        fields = ["id","org","feature","quantity","unit","provider","cost_minor","billing_cost_minor","idempotency_key","status","metadata","customer","duration_seconds","billable_minutes","channel","created_at"]

class UsageCreditSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageCredit
        fields = ["id","org","type","quantity","remaining","expires_at","created_at"]

class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id","org","provider","brand","last4","exp_month","exp_year","is_default","provider_ref","created_at"]

class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = ["id","code","discount_type","discount_value","start_date","end_date","max_redemptions","times_redeemed","eligible_plans","active"]

class ReferralSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referral
        fields = ["id","referrer_org","referred_org","code","email","status","reward_granted","reward_days","created_at"]

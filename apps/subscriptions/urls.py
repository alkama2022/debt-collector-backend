from django.urls import path
from .views import (
    SubscriptionDetail, PlanListView, PlanDetailView, EntitlementsView, CheckFeatureView, CheckLimitView,
    SubscribeView, UpgradeView, DowngradeView, CancelView, ReactivateView, UpdateOveragePolicyView,
    UsageSummaryView, UsageHistoryView, RecordUsageView, VoiceUsageView,
    CreditsView, VerifyCreditPaymentView,
    BillingInvoicesView, BillingTransactionsView, PaymentMethodsView,
    WebhookView, AdminBillingDashboardView, CouponValidateView, ReferralView, UnitEconomicsView, BillingHistoryExportView
)

urlpatterns = [
    # Plans (public pricing)
    path("billing/plans", PlanListView.as_view(), name="billing-plans"),
    path("billing/plans/<slug:slug>", PlanDetailView.as_view(), name="billing-plan-detail"),

    # Subscription & entitlements (authoritative)
    path("subscriptions/me", SubscriptionDetail.as_view(), name="subscription-detail"),
    path("billing/subscription", SubscriptionDetail.as_view(), name="billing-subscription"),
    path("billing/entitlements", EntitlementsView.as_view(), name="billing-entitlements"),
    path("billing/check-feature", CheckFeatureView.as_view(), name="billing-check-feature"),
    path("billing/check-limit", CheckLimitView.as_view(), name="billing-check-limit"),

    # Lifecycle
    path("billing/subscribe", SubscribeView.as_view(), name="billing-subscribe"),
    path("billing/upgrade", UpgradeView.as_view(), name="billing-upgrade"),
    path("billing/downgrade", DowngradeView.as_view(), name="billing-downgrade"),
    path("billing/cancel", CancelView.as_view(), name="billing-cancel"),
    path("billing/reactivate", ReactivateView.as_view(), name="billing-reactivate"),
    path("billing/overage-policy", UpdateOveragePolicyView.as_view(), name="billing-overage-policy"),

    # Usage
    path("billing/usage", UsageSummaryView.as_view(), name="billing-usage"),
    path("billing/usage/history", UsageHistoryView.as_view(), name="billing-usage-history"),
    path("billing/usage/record", RecordUsageView.as_view(), name="billing-usage-record"),
    path("billing/usage/voice", VoiceUsageView.as_view(), name="billing-voice-usage"),
    path("billing/unit-economics", UnitEconomicsView.as_view(), name="billing-unit-economics"),

    # Credits / Overage
    path("billing/credits", CreditsView.as_view(), name="billing-credits"),
    path("billing/credits/verify", VerifyCreditPaymentView.as_view(), name="billing-credits-verify"),
    path("billing/credits/purchase", CreditsView.as_view(), name="billing-credits-purchase"),

    # Invoices / Transactions / Payment Methods
    path("billing/invoices", BillingInvoicesView.as_view(), name="billing-invoices"),
    path("billing/transactions", BillingTransactionsView.as_view(), name="billing-transactions"),
    path("billing/payment-methods", PaymentMethodsView.as_view(), name="billing-payment-methods"),
    path("billing/history", BillingHistoryExportView.as_view(), name="billing-history"),

    # Coupons / Referrals
    path("billing/coupons/validate", CouponValidateView.as_view(), name="billing-coupon-validate"),
    path("billing/referrals", ReferralView.as_view(), name="billing-referrals"),

    # Webhooks (no auth)
    path("billing/webhooks/<str:provider>", WebhookView.as_view(), name="billing-webhook"),

    # Admin
    path("admin/billing", AdminBillingDashboardView.as_view(), name="admin-billing"),
    path("admin/billing/dashboard", AdminBillingDashboardView.as_view(), name="admin-billing-dashboard"),
]

import uuid
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Subscription, Plan, BillingInvoice, BillingTransaction, UsageEvent, UsageCredit, PaymentMethod, Coupon, CouponRedemption, WebhookEvent, BillingAuditLog, SubscriptionEvent, Referral, AffiliateLink
from .serializers import SubscriptionSerializer, PlanSerializer, BillingInvoiceSerializer, BillingTransactionSerializer, UsageEventSerializer, UsageCreditSerializer, PaymentMethodSerializer, CouponSerializer, ReferralSerializer
from .entitlements import get_subscription_for_org, get_plan_for_subscription, get_entitlements, check_feature_access, check_limit
from .providers import get_provider
from .usage import get_current_usage, get_all_usage, commit_or_create_usage, calculate_billable_minutes
from apps.tenancy.org import get_org


def _require_org(request):
    org = get_org(request)
    if org is None:
        raise NotFound("Organization context required. Send X-Org-Id header or create an organization.")
    return org

def _require_owner_or_admin(request):
    org = _require_org(request)
    from apps.tenancy.models import Membership
    m = Membership.objects.filter(org=org, user=request.user).first()
    if not m or m.role not in ("owner","admin"):
        # allow billing_manager role extension
        raise PermissionDenied("Only Owner/Admin can manage billing. Your role: %s" % (m.role if m else "none"))
    return org

def _is_billing_manager(request):
    org = get_org(request)
    if org is None:
        return False
    from apps.tenancy.models import Membership
    m = Membership.objects.filter(org=org, user=request.user).first()
    return m and m.role in ("owner","admin")

# ── Plans ────────────────────────────────────────────────────────────────

def assert_plans_seeded():
    """Fail loudly when the billing catalog is empty.

    An unseeded plans table previously surfaced as a 404 ("Plan starter not
    found") on every subscribe call, which looks like a user error and hides a
    missing `manage.py seed_billing` step. 503 + an explicit message points at
    the real cause instead.
    """
    if not Plan.objects.filter(active=True).exists():
        from rest_framework.response import Response as _R
        from rest_framework import status as _s
        return _R(
            {
                "detail": "Billing plans are not configured. "
                          "Run `python manage.py seed_billing` to create them.",
                "code": "BILLING_NOT_SEEDED",
            },
            status=_s.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return None


class PlanListView(generics.ListAPIView):
    serializer_class = PlanSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        qs = Plan.objects.filter(active=True).order_by("sort_order")
        if self.request.query_params.get("public") == "true":
            qs = qs.filter(public=True)
        return qs

    def list(self, request, *args, **kwargs):
        unseeded = assert_plans_seeded()
        if unseeded is not None:
            return unseeded
        return super().list(request, *args, **kwargs)


class PlanDetailView(generics.RetrieveAPIView):
    serializer_class = PlanSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "slug"
    queryset = Plan.objects.filter(active=True)

# ── Entitlements / Subscription ──────────────────────────────────────────

class SubscriptionDetail(generics.RetrieveAPIView):
    serializer_class = SubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_object(self):
        org = _require_org(self.request)
        return get_subscription_for_org(org)

class EntitlementsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        data = get_entitlements(org)
        return Response(data)

class CheckFeatureView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        feature = request.query_params.get("feature") or request.query_params.get("slug")
        if not feature:
            return Response({"detail": "feature query param required"}, status=400)
        allowed, reason = check_feature_access(org, feature)
        return Response({"feature": feature, "allowed": allowed, "reason": reason})

class CheckLimitView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        key = request.query_params.get("key") or request.query_params.get("limit")
        if not key:
            return Response({"detail": "key query param required"}, status=400)
        allowed, reason, info = check_limit(org, key, int(request.query_params.get("qty", 1)))
        return Response({"key": key, "allowed": allowed, "reason": reason, **info})

# ── Subscription lifecycle ───────────────────────────────────────────────

class SubscribeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_owner_or_admin(request)
        plan_slug = request.data.get("plan") or request.data.get("plan_slug")
        if not plan_slug:
            return Response({"detail": "plan required"}, status=400)
        try:
            plan = Plan.objects.get(slug=plan_slug, active=True)
        except Plan.DoesNotExist:
            unseeded = assert_plans_seeded()
            if unseeded is not None:
                return unseeded
            return Response({"detail": f"Plan {plan_slug} not found"}, status=404)
        sub = get_subscription_for_org(org)
        # coupon
        coupon_code = request.data.get("coupon") or request.data.get("coupon_code")
        discount_minor = 0
        coupon = None
        if coupon_code:
            try:
                coupon = Coupon.objects.get(code__iexact=coupon_code.strip(), active=True)
                # validate eligible plans, dates, max redemptions
                from django.utils import timezone as tz
                now = tz.now()
                if coupon.start_date and now < coupon.start_date:
                    return Response({"detail": "Coupon not yet active"}, status=400)
                if coupon.end_date and now > coupon.end_date:
                    return Response({"detail": "Coupon expired"}, status=400)
                if coupon.max_redemptions and coupon.times_redeemed >= coupon.max_redemptions:
                    return Response({"detail": "Coupon max redemptions reached"}, status=400)
                if coupon.eligible_plans and plan.slug not in coupon.eligible_plans:
                    return Response({"detail": "Coupon not eligible for this plan"}, status=400)
                # compute discount
                price_minor = int(plan.price * 100)
                if coupon.discount_type == "percentage":
                    discount_minor = int(price_minor * float(coupon.discount_value) / 100)
                else:
                    discount_minor = int(float(coupon.discount_value) * 100)
            except Coupon.DoesNotExist:
                return Response({"detail": "Invalid coupon code"}, status=400)

        # Handle downgrade guard: if new limit smaller than current usage, warn but allow (data stays)
        from .entitlements import get_limit as _get_limit, get_usage_count
        new_limits = {pl.key: pl.limit_value for pl in plan.limits.all()}
        warnings = []
        for k, new_lim in new_limits.items():
            if new_lim is None:
                continue
            used = get_usage_count(org, k)
            if used > new_lim:
                warnings.append(f"Your account has {used} {k.lower()}, new plan allows {new_lim}. Existing data kept, but you cannot add more until within limit.")

        with transaction.atomic():
            old_plan = sub.effective_plan_slug
            sub.plan = plan.slug
            sub.plan_obj = plan
            sub.currency = plan.currency
            sub.billing_interval = plan.billing_interval
            now = timezone.now()
            # trial
            if plan.trial_days and not sub.trial_start:
                sub.status = Subscription.Status.TRIALING
                sub.trial_start = now
                sub.trial_end = now + timezone.timedelta(days=plan.trial_days)
                sub.current_period_end = sub.trial_end
            else:
                sub.status = Subscription.Status.ACTIVE
                sub.current_period_start = now
                # monthly
                sub.current_period_end = now + timezone.timedelta(days=30)
                # Clear stale trial dates when leaving a trial (e.g. downgrade
                # to free). Leaving them set made a non-trialing subscription
                # report a trial_end it was no longer in.
                if plan.trial_days == 0:
                    sub.trial_start = None
                    sub.trial_end = None
            sub.mrr_minor = int(plan.price * 100) - discount_minor
            sub.cancel_at_period_end = False
            sub.save()

            BillingAuditLog.objects.create(org=org, actor=request.user, action="subscription.subscribe", before={"plan": old_plan}, after={"plan": plan.slug, "coupon": coupon_code})
            SubscriptionEvent.objects.create(subscription=sub, org=org, event_type="SubscriptionCreated" if old_plan=="free" else "SubscriptionUpgraded" if warnings else "SubscriptionRenewed", from_plan=old_plan, to_plan=plan.slug, actor=request.user, metadata={"coupon": coupon_code, "warnings": warnings})

            if coupon:
                CouponRedemption.objects.get_or_create(coupon=coupon, org=org, defaults={"subscription": sub, "discount_amount_minor": discount_minor})
                coupon.times_redeemed = (coupon.times_redeemed or 0) + 1
                coupon.save(update_fields=["times_redeemed"])

            # Create billing invoice (open, then mock paid via verify)
            invoice_number = f"SUB-{timezone.now().strftime('%Y%m')}-{str(uuid.uuid4())[:8].upper()}"
            amount_minor = int(plan.price * 100) - discount_minor
            amount = Decimal(amount_minor) / Decimal(100)
            inv = BillingInvoice.objects.create(
                org=org, subscription=sub, invoice_number=invoice_number,
                status=BillingInvoice.Status.OPEN, amount=amount, amount_minor=amount_minor, currency=plan.currency,
                period_start=sub.current_period_start, period_end=sub.current_period_end, provider="paystack"
            )
            # Provider payment link
            provider = get_provider("paystack")
            ref = f"sub_{org.id}_{invoice_number}"
            pay_data = provider.create_payment_link(org, amount_minor, plan.currency, ref, {"email": request.user.email, "plan": plan.slug, "invoice_number": invoice_number})
            txn = BillingTransaction.objects.create(
                org=org, subscription=sub, type=BillingTransaction.Type.SUBSCRIPTION,
                amount=amount, amount_minor=amount_minor, currency=plan.currency,
                provider="paystack", provider_ref=ref, idempotency_key=ref, status=BillingTransaction.Status.PENDING,
                metadata={"invoice_id": str(inv.id), "authorization_url": pay_data.get("authorization_url")}
            )
            # If free plan (0), auto-mark paid
            if amount_minor == 0:
                inv.status = BillingInvoice.Status.PAID
                inv.paid_at = timezone.now()
                inv.save(update_fields=["status","paid_at"])
                txn.status = BillingTransaction.Status.SUCCEEDED
                txn.save(update_fields=["status"])

        return Response({"subscription": SubscriptionSerializer(sub).data, "invoice": BillingInvoiceSerializer(inv).data, "transaction": BillingTransactionSerializer(txn).data, "payment": pay_data, "warnings": warnings, "coupon_applied": bool(coupon), "discount_minor": discount_minor})


class UpgradeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        # alias to subscribe with proration note
        return SubscribeView().post(request)


class DowngradeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_owner_or_admin(request)
        plan_slug = request.data.get("plan") or request.data.get("plan_slug")
        if not plan_slug:
            return Response({"detail": "plan required"}, status=400)
        try:
            plan = Plan.objects.get(slug=plan_slug, active=True)
        except Plan.DoesNotExist:
            return Response({"detail": "Plan not found"}, status=404)
        sub = get_subscription_for_org(org)
        old = sub.effective_plan_slug
        # never delete data; just check and warn
        from .entitlements import get_usage_count
        warnings = []
        for pl in plan.limits.all():
            used = get_usage_count(org, pl.key)
            if pl.limit_value is not None and used > pl.limit_value:
                warnings.append(f"Downgrade warning: {pl.key} used {used} exceeds new limit {pl.limit_value}. Data kept; cannot add more until within limit.")
        with transaction.atomic():
            sub.plan = plan.slug
            sub.plan_obj = plan
            sub.status = Subscription.Status.DOWNGRADED
            sub.save(update_fields=["plan","plan_obj","status","updated_at"])
            SubscriptionEvent.objects.create(subscription=sub, org=org, event_type="SubscriptionDowngraded", from_plan=old, to_plan=plan.slug, actor=request.user, metadata={"warnings": warnings})
            BillingAuditLog.objects.create(org=org, actor=request.user, action="subscription.downgrade", before={"plan": old}, after={"plan": plan.slug})
        return Response({"subscription": SubscriptionSerializer(sub).data, "warnings": warnings, "message": warnings[0] if warnings else "Downgraded. Existing data kept."})

class CancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_owner_or_admin(request)
        mode = request.data.get("mode") or ("immediate" if request.data.get("immediate") else "period_end")
        sub = get_subscription_for_org(org)
        if sub.status == Subscription.Status.CANCELLED:
            return Response({"detail": "Already cancelled"}, status=400)
        old_status = sub.status
        with transaction.atomic():
            if mode == "immediate":
                sub.status = Subscription.Status.CANCELLED
                sub.cancelled_at = timezone.now()
                sub.cancel_at_period_end = False
                sub.save(update_fields=["status","cancelled_at","cancel_at_period_end"])
                SubscriptionEvent.objects.create(subscription=sub, org=org, event_type="SubscriptionCancelled", from_plan=sub.effective_plan_slug, to_plan=sub.effective_plan_slug, actor=request.user, metadata={"mode": "immediate"})
            else:
                sub.cancel_at_period_end = True
                sub.save(update_fields=["cancel_at_period_end"])
                SubscriptionEvent.objects.create(subscription=sub, org=org, event_type="SubscriptionCancellationScheduled", from_plan=sub.effective_plan_slug, to_plan=sub.effective_plan_slug, actor=request.user, metadata={"mode": "period_end", "period_end": str(sub.current_period_end)})
            BillingAuditLog.objects.create(org=org, actor=request.user, action="subscription.cancel", before={"status": old_status}, after={"status": sub.status, "cancel_at_period_end": sub.cancel_at_period_end})
        return Response({"subscription": SubscriptionSerializer(sub).data, "message": "Cancelled immediately" if mode=="immediate" else f"Will cancel at period end ({sub.current_period_end})"})

class ReactivateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_owner_or_admin(request)
        sub = get_subscription_for_org(org)
        if sub.status != Subscription.Status.CANCELLED and not sub.cancel_at_period_end:
            return Response({"detail": "Subscription not cancelled"}, status=400)
        sub.cancel_at_period_end = False
        if sub.status == Subscription.Status.CANCELLED:
            sub.status = Subscription.Status.ACTIVE
            sub.cancelled_at = None
        sub.save(update_fields=["cancel_at_period_end","status","cancelled_at"])
        SubscriptionEvent.objects.create(subscription=sub, org=org, event_type="SubscriptionReactivated", from_plan=sub.effective_plan_slug, to_plan=sub.effective_plan_slug, actor=request.user)
        return Response({"subscription": SubscriptionSerializer(sub).data})


class UpdateOveragePolicyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_owner_or_admin(request)
        policy = request.data.get("overage_policy") or request.data.get("policy")
        if policy not in [c[0] for c in Subscription.OveragePolicy.choices]:
            return Response({"detail": f"Invalid policy. Choices: {[c[0] for c in Subscription.OveragePolicy.choices]}"}, status=400)
        sub = get_subscription_for_org(org)
        sub.overage_policy = policy
        sub.save(update_fields=["overage_policy"])
        BillingAuditLog.objects.create(org=org, actor=request.user, action="subscription.overage_policy", after={"policy": policy})
        return Response({"overage_policy": policy, "message": "Overage policy updated. You will not be silently charged."})

# ── Usage ────────────────────────────────────────────────────────────────

class UsageSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        period = request.query_params.get("period")
        data = get_all_usage(org, period)
        # also include limits + counters for dashboard
        from .entitlements import get_entitlements as _ent
        ent = _ent(org)
        return Response({"period": period or timezone.now().strftime("%Y-%m"), "usage": data, "limits": ent["limits"], "subscription": ent["subscription"]})

class UsageHistoryView(generics.ListAPIView):
    serializer_class = UsageEventSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        org = _require_org(self.request)
        qs = UsageEvent.objects.filter(org=org).order_by("-created_at")
        feat = self.request.query_params.get("feature")
        if feat:
            qs = qs.filter(feature=feat)
        return qs

class RecordUsageView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_org(request)
        feature = request.data.get("feature") or request.data.get("type")
        qty = request.data.get("quantity") or 1
        idem = request.data.get("idempotency_key")
        if not feature:
            return Response({"detail": "feature required"}, status=400)
        # entitlement check — backend authoritative
        allowed, reason = check_feature_access(org, feature) if feature in ("AI_VOICE","AI_CONVERSATIONS","AI_MULTILINGUAL") else (True, "ok")
        if not allowed:
            return Response({"detail": reason, "code": "FEATURE_NOT_ENTITLED"}, status=403)
        try:
            evt = commit_or_create_usage(org, feature, Decimal(str(qty)), idempotency_key=idem, metadata=request.data.get("metadata", {}), unit=request.data.get("unit",""))
        except PermissionError as e:
            return Response({"detail": str(e), "code": "USAGE_LIMIT_REACHED"}, status=429)
        return Response(UsageEventSerializer(evt).data, status=201)

class VoiceUsageView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_org(request)
        allowed, reason = check_feature_access(org, "AI_VOICE")
        if not allowed:
            return Response({"detail": reason, "code": "FEATURE_NOT_ENTITLED"}, status=403)
        duration = int(request.data.get("duration_seconds") or 0)
        billable = calculate_billable_minutes(duration)
        customer_id = request.data.get("customer_id")
        idem = request.data.get("idempotency_key") or request.data.get("call_id")
        try:
            evt = commit_or_create_usage(org, "AI_VOICE_MINUTES", billable, idempotency_key=idem, unit="minutes", metadata={"duration_seconds": duration, "customer_id": customer_id})
            # also record voice billing detail
            from .models import VoiceBillingRecord
            VoiceBillingRecord.objects.create(org=org, subscription=get_subscription_for_org(org), customer_id=customer_id if customer_id else None, call_id=idem or str(evt.id), duration_seconds=duration, billable_minutes=billable, provider=request.data.get("provider","mock"), status="completed")
        except PermissionError as e:
            return Response({"detail": str(e), "code": "USAGE_LIMIT_REACHED"}, status=429)
        return Response({"event": UsageEventSerializer(evt).data, "billable_minutes": str(billable), "duration_seconds": duration})

# ── Credits ──────────────────────────────────────────────────────────────

class CreditsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        credits = UsageCredit.objects.filter(org=org).order_by("-created_at")
        return Response({"credits": UsageCreditSerializer(credits, many=True).data, "total_remaining": float(sum((c.remaining for c in credits), Decimal("0")))})

    def post(self, request):
        org = _require_owner_or_admin(request)
        ctype = request.data.get("type") or "general"
        qty = Decimal(str(request.data.get("quantity") or 0))
        if qty <= 0:
            return Response({"detail": "quantity must be > 0"}, status=400)
        # pricing config: e.g. 5000 NGN -> 500 credits (10 NGN per credit) — configurable via request price
        price_minor = int(request.data.get("price_minor") or int(qty * 1000))  # default 10 NGN per credit
        # create transaction
        txn = BillingTransaction.objects.create(
            org=org, subscription=get_subscription_for_org(org), type=BillingTransaction.Type.CREDIT,
            amount=Decimal(price_minor)/Decimal(100), amount_minor=price_minor, currency="NGN",
            provider="paystack", provider_ref=f"credit_{uuid.uuid4().hex[:8]}", idempotency_key=str(uuid.uuid4()), status=BillingTransaction.Status.PENDING,
            metadata={"credit_type": ctype, "quantity": str(qty)}
        )
        # mock auto succeed for now; real would need paystack link
        provider = get_provider("paystack")
        ref = txn.provider_ref
        pay_data = provider.create_payment_link(org, price_minor, "NGN", ref, {"email": request.user.email, "type": "credit_purchase"})
        txn.metadata["authorization_url"] = pay_data.get("authorization_url")
        txn.save(update_fields=["metadata"])
        # In mock mode, immediately grant credits on verify step; for now create pending credit
        # For MVP, if mock, auto-succeed
        if pay_data.get("mock"):
            txn.status = BillingTransaction.Status.SUCCEEDED
            txn.save(update_fields=["status"])
            credit = UsageCredit.objects.create(org=org, type=ctype, quantity=qty, remaining=qty, purchase_transaction=txn)
            return Response({"credit": UsageCreditSerializer(credit).data, "transaction": BillingTransactionSerializer(txn).data, "payment": pay_data})
        return Response({"transaction": BillingTransactionSerializer(txn).data, "payment": pay_data})

class VerifyCreditPaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        org = _require_owner_or_admin(request)
        ref = request.data.get("reference") or request.data.get("provider_ref")
        if not ref:
            return Response({"detail": "reference required"}, status=400)
        txn = BillingTransaction.objects.filter(org=org, provider_ref=ref).first()
        if not txn:
            return Response({"detail": "Transaction not found"}, status=404)
        # verify via provider
        provider = get_provider("paystack")
        result = provider.verify_payment(ref)
        # mock always succeeds
        if result.get("status") in ("success","successful","mock") or txn.status == BillingTransaction.Status.PENDING:
            txn.status = BillingTransaction.Status.SUCCEEDED
            txn.save(update_fields=["status"])
            # grant credits if not already
            if not UsageCredit.objects.filter(purchase_transaction=txn).exists():
                qty = Decimal(str(txn.metadata.get("quantity") or 0))
                credit = UsageCredit.objects.create(org=org, type=txn.metadata.get("credit_type","general"), quantity=qty, remaining=qty, purchase_transaction=txn)
                return Response({"credit": UsageCreditSerializer(credit).data, "transaction": BillingTransactionSerializer(txn).data})
        return Response({"transaction": BillingTransactionSerializer(txn).data})

# ── Invoices / Transactions / Payment Methods ────────────────────────────

class BillingInvoicesView(generics.ListAPIView):
    serializer_class = BillingInvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        org = _require_org(self.request)
        return BillingInvoice.objects.filter(org=org).order_by("-created_at")

class BillingTransactionsView(generics.ListAPIView):
    serializer_class = BillingTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        org = _require_org(self.request)
        return BillingTransaction.objects.filter(org=org).order_by("-created_at")

class PaymentMethodsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        ms = PaymentMethod.objects.filter(org=org).order_by("-is_default","-created_at")
        return Response({"payment_methods": PaymentMethodSerializer(ms, many=True).data})
    def post(self, request):
        org = _require_owner_or_admin(request)
        pm = PaymentMethod.objects.create(
            org=org, provider=request.data.get("provider","paystack"),
            brand=request.data.get("brand","card"), last4=request.data.get("last4","4242"),
            exp_month=request.data.get("exp_month"), exp_year=request.data.get("exp_year"),
            is_default=request.data.get("is_default", True), provider_ref=request.data.get("provider_ref","")
        )
        if pm.is_default:
            PaymentMethod.objects.filter(org=org).exclude(id=pm.id).update(is_default=False)
        return Response(PaymentMethodSerializer(pm).data, status=201)

# ── Webhooks ─────────────────────────────────────────────────────────────

class WebhookView(APIView):
    permission_classes = []
    authentication_classes = []
    def post(self, request, provider):
        import json
        raw = request.body
        sig = request.headers.get("X-Paystack-Signature") or request.headers.get("verif-hash") or request.headers.get("X-Webhook-Signature") or ""
        prov = get_provider(provider)
        # verify
        if hasattr(prov, "verify_signature"):
            if not prov.verify_signature(raw, sig):
                return Response({"detail": "Invalid signature"}, status=400)
        try:
            payload = json.loads(raw.decode() or "{}")
        except Exception:
            payload = request.data
        event_id = payload.get("id") or payload.get("event_id") or payload.get("reference") or str(uuid.uuid4())
        event_type = payload.get("event") or payload.get("type") or "unknown"
        # idempotency
        if WebhookEvent.objects.filter(event_id=str(event_id)).exists():
            return Response({"status": "already_processed"})
        we = WebhookEvent.objects.create(provider=provider, event_id=str(event_id), event_type=event_type, payload=payload)
        # process
        try:
            _process_webhook_event(we)
            we.processed = True
            we.processed_at = timezone.now()
            we.save(update_fields=["processed","processed_at"])
        except Exception as e:
            we.error = str(e)[:1000]
            we.save(update_fields=["error"])
            return Response({"detail": str(e)}, status=500)
        return Response({"status": "processed"})

def _process_webhook_event(we):
    payload = we.payload
    # Paystack: event charge.success
    data = payload.get("data") or payload
    reference = data.get("reference") or data.get("provider_ref") or ""
    status_str = data.get("status") or data.get("gateway_response") or ""
    if we.event_type in ("charge.success","charge.successful") or status_str in ("success","successful"):
        # mark transaction succeeded + invoice paid
        if reference:
            txn = BillingTransaction.objects.filter(provider_ref=reference).first()
            if txn:
                txn.status = BillingTransaction.Status.SUCCEEDED
                txn.save(update_fields=["status"])
                # mark invoice paid
                inv_id = txn.metadata.get("invoice_id")
                if inv_id:
                    try:
                        inv = BillingInvoice.objects.get(id=inv_id)
                        inv.status = BillingInvoice.Status.PAID
                        inv.paid_at = timezone.now()
                        inv.save(update_fields=["status","paid_at"])
                        # activate subscription
                        sub = inv.subscription
                        if sub and sub.status in (Subscription.Status.INCOMPLETE, Subscription.Status.PAST_DUE, Subscription.Status.TRIALING):
                            sub.status = Subscription.Status.ACTIVE
                            sub.current_period_start = timezone.now()
                            sub.current_period_end = timezone.now() + timezone.timedelta(days=30)
                            sub.save(update_fields=["status","current_period_start","current_period_end"])
                    except BillingInvoice.DoesNotExist:
                        pass

# ── Billing history / Admin ──────────────────────────────────────────────

class AdminBillingDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        if not request.user.is_staff and not request.user.is_superuser:
            raise PermissionDenied("Admin only")
        from .models import Subscription as Sub
        total_orgs = Sub.objects.count()
        by_plan = Sub.objects.values("plan").annotate(c=Count("id"))
        by_status = Sub.objects.values("status").annotate(c=Count("id"))
        mrr = Sub.objects.aggregate(s=Sum("mrr_minor"))["s"] or 0
        arr = mrr * 12
        new_subs = SubscriptionEvent.objects.filter(event_type="SubscriptionCreated", created_at__gte=timezone.now()-timezone.timedelta(days=30)).count()
        cancels = SubscriptionEvent.objects.filter(event_type__in=["SubscriptionCancelled","SubscriptionCancellationScheduled"], created_at__gte=timezone.now()-timezone.timedelta(days=30)).count()
        # usage aggregates
        ai_total = UsageEvent.objects.filter(feature="AI_CONVERSATIONS", status="committed").aggregate(s=Sum("quantity"))["s"] or 0
        voice_total = UsageEvent.objects.filter(feature__in=["AI_VOICE","AI_VOICE_MINUTES"], status="committed").aggregate(s=Sum("quantity"))["s"] or 0
        # provider costs
        total_cost = UsageEvent.objects.filter(status="committed").aggregate(s=Sum("cost_minor"))["s"] or 0
        gross = BillingTransaction.objects.filter(status="succeeded").aggregate(s=Sum("amount_minor"))["s"] or 0
        margin = gross - (total_cost or 0)
        return Response({
            "total_organizations": total_orgs,
            "by_plan": list(by_plan),
            "by_status": list(by_status),
            "mrr_minor": mrr, "mrr": float(mrr)/100, "arr_minor": arr, "arr": float(arr)/100,
            "new_subscriptions_30d": new_subs, "cancellations_30d": cancels,
            "churn_rate": round(cancels / total_orgs * 100, 2) if total_orgs else 0,
            "ai_usage_total": float(ai_total), "voice_usage_total": float(voice_total),
            "provider_cost_minor": total_cost, "gross_minor": gross, "gross": float(gross)/100,
            "estimated_margin_minor": margin, "estimated_margin": float(margin)/100,
        })

class BillingHistoryExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        invoices = BillingInvoice.objects.filter(org=org).order_by("-created_at")
        txns = BillingTransaction.objects.filter(org=org).order_by("-created_at")
        return Response({"invoices": BillingInvoiceSerializer(invoices, many=True).data, "transactions": BillingTransactionSerializer(txns, many=True).data})

# ── Coupons ──────────────────────────────────────────────────────────────

class CouponValidateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        code = (request.data.get("code") or request.data.get("coupon") or "").strip()
        plan_slug = request.data.get("plan") or request.data.get("plan_slug")
        if not code:
            return Response({"detail": "code required"}, status=400)
        try:
            c = Coupon.objects.get(code__iexact=code, active=True)
        except Coupon.DoesNotExist:
            return Response({"valid": False, "reason": "Invalid code"}, status=404)
        # date checks
        now = timezone.now()
        if c.start_date and now < c.start_date:
            return Response({"valid": False, "reason": "Not yet active"})
        if c.end_date and now > c.end_date:
            return Response({"valid": False, "reason": "Expired"})
        if c.max_redemptions and c.times_redeemed >= c.max_redemptions:
            return Response({"valid": False, "reason": "Max redemptions reached"})
        if plan_slug and c.eligible_plans and plan_slug not in c.eligible_plans:
            return Response({"valid": False, "reason": f"Not eligible for {plan_slug}"})
        # compute discount preview
        discount = c.discount_value
        dtype = c.discount_type
        return Response({"valid": True, "coupon": CouponSerializer(c).data, "discount_type": dtype, "discount_value": str(discount)})

# ── Referrals ────────────────────────────────────────────────────────────

class ReferralView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        refs = Referral.objects.filter(referrer_org=org).order_by("-created_at")
        my_code = refs.first().code if refs.exists() else f"REF-{str(org.id)[:6].upper()}"
        # ensure one baseline referral code exists
        if not refs.exists():
            r = Referral.objects.create(referrer_org=org, code=my_code, status=Referral.Status.PENDING)
            refs = [r]
        return Response({"referrals": ReferralSerializer(refs, many=True).data, "my_code": my_code, "reward_days": 30})

    def post(self, request):
        org = _require_org(request)
        email = request.data.get("email")
        if not email:
            return Response({"detail": "email required"}, status=400)
        code = f"REF-{uuid.uuid4().hex[:6].upper()}"
        r = Referral.objects.create(referrer_org=org, code=code, email=email)
        return Response(ReferralSerializer(r).data, status=201)

class UnitEconomicsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        org = _require_org(request)
        sub = get_subscription_for_org(org)
        price_minor = sub.mrr_minor
        usage_cost = UsageEvent.objects.filter(org=org, status="committed", created_at__gte=timezone.now().replace(day=1)).aggregate(s=Sum("cost_minor"))["s"] or 0
        # comms cost
        from apps.comms.models import CommunicationEvent
        comm_cost = CommunicationEvent.objects.filter(org=org).aggregate(s=Sum("cost_minor"))["s"] or 0
        gross = price_minor
        # voice cost already in usage_cost if recorded
        profit = gross - (usage_cost or 0) - (comm_cost or 0)
        flagged = (usage_cost or 0) > gross * 2  # >2x subscription
        return Response({
            "subscription_revenue_minor": gross,
            "usage_cost_minor": usage_cost,
            "comm_cost_minor": comm_cost,
            "estimated_gross_profit_minor": profit,
            "flagged_high_usage": flagged,
            "note": "High usage flagged for admin review, not auto-punished." if flagged else "Healthy margin"
        })

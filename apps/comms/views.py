from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import CommunicationEvent, CommunicationPreference, ReminderRule
from .serializers import CommunicationEventSerializer, CommunicationPreferenceSerializer, ReminderRuleSerializer


def _org(request):
    """Resolve the active org for both session and JWT requests.

    CurrentOrgMiddleware sets request.org = None for JWT requests (DRF has not
    authenticated yet at middleware time), so bare getattr(request, "org")
    returns None and writes fail the org_id NOT NULL constraint.
    """
    from apps.tenancy.middleware import resolve_org
    return resolve_org(request)


class CommunicationEventList(generics.ListCreateAPIView):
    serializer_class = CommunicationEventSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["channel", "status", "customer", "invoice"]
    ordering = ["-created_at"]

    def get_queryset(self):
        org = _org(self.request)
        if org is None:
            return CommunicationEvent.objects.none()
        return CommunicationEvent.objects.for_org(org)

    def perform_create(self, serializer):
        org = _org(self.request)
        if org is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Organization context required.")
        # Feature gate: check WHATSAPP/SMS/EMAIL entitlement + metered limit
        channel = (serializer.validated_data.get("channel") or "").upper()
        if org and channel in ("WHATSAPP", "SMS", "EMAIL"):
            from apps.subscriptions.entitlements import check_feature_access, check_limit
            feature_map = {"WHATSAPP": "WHATSAPP_REMINDERS", "SMS": "SMS_REMINDERS", "EMAIL": "EMAIL_REMINDERS"}
            feat = feature_map.get(channel)
            if feat:
                allowed, reason = check_feature_access(org, feat)
                if not allowed:
                    from rest_framework.exceptions import PermissionDenied
                    raise PermissionDenied({"detail": reason, "code": "FEATURE_NOT_ENTITLED"})
            allowed2, reason2, info = check_limit(org, "WHATSAPP_MESSAGES" if channel=="WHATSAPP" else "SMS_MESSAGES" if channel=="SMS" else "EMAIL_MESSAGES", 1)
            if not allowed2:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied({"detail": reason2, "code": "USAGE_LIMIT_REACHED"})
        idem = self.request.headers.get("X-Idempotency-Key") or self.request.headers.get("Idempotency-Key")
        obj = serializer.save(org=org, idempotency_key=idem or serializer.validated_data.get("idempotency_key"))
        # Meter usage
        if org and channel:
            try:
                from apps.subscriptions.usage import commit_or_create_usage
                key = f"WHATSAPP_MESSAGE" if channel=="WHATSAPP" else channel
                commit_or_create_usage(org, key, 1, idempotency_key=idem or str(obj.id), unit="message", metadata={"channel": channel})
            except Exception:
                pass

class CommunicationEventDetail(generics.RetrieveAPIView):
    serializer_class = CommunicationEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = _org(self.request)
        if org is None:
            return CommunicationEvent.objects.none()
        return CommunicationEvent.objects.for_org(org)

class CommunicationPreferenceList(generics.ListCreateAPIView):
    serializer_class = CommunicationPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = _org(self.request)
        if org is None:
            return CommunicationPreference.objects.none()
        return CommunicationPreference.objects.filter(org=org)

    def perform_create(self, serializer):
        org = _org(self.request)
        if org is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Organization context required.")
        serializer.save(org=org)


class ReminderRuleListCreate(generics.ListCreateAPIView):
    serializer_class = ReminderRuleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = _org(self.request)
        if org is None:
            return ReminderRule.objects.none()
        return ReminderRule.objects.for_org(org).order_by("-created_at")

    def perform_create(self, serializer):
        org = _org(self.request)
        if org is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Organization context required.")
        serializer.save(org=org)


class ReminderRuleDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ReminderRuleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = _org(self.request)
        if org is None:
            return ReminderRule.objects.none()
        return ReminderRule.objects.for_org(org)


class ReminderRuleRunView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        org = _org(request)
        if org is None:
            return Response({"success": False, "message": "Organization required"}, status=401)
        # If pk provided, run single rule; else run all enabled
        rules = ReminderRule.objects.for_org(org).filter(enabled=True)
        if pk:
            try:
                rules = rules.filter(pk=pk)
                if not rules.exists():
                    return Response({"success": False, "message": "Rule not found"}, status=404)
            except Exception:
                return Response({"success": False, "message": "Invalid rule id"}, status=400)
        # Create CommunicationEvents for open invoices matching rule date logic (mock schedule)
        from apps.invoices.models import Invoice
        from datetime import timedelta, date
        today = date.today()
        created = 0
        events = []
        for rule in rules:
            target_date = today - timedelta(days=rule.offset_days) if rule.trigger == "after_due" else today + timedelta(days=abs(rule.offset_days)) if rule.trigger == "before_due" else today
            # For demo: match invoices where due_date == target_date and balance>0, or if no due_date, take all open
            invoices = Invoice.objects.for_org(org).filter(deleted_at__isnull=True, balance__gt=0)
            # Filter by due date when rule is date-specific; if rule is very generic, limit to 20 to avoid spam
            if rule.trigger != "after_due" or rule.offset_days != 0:
                invoices = invoices.filter(due_date=target_date)
                if not invoices.exists() and rule.trigger == "after_due":
                    # fallback: overdue invoices
                    invoices = Invoice.objects.for_org(org).filter(deleted_at__isnull=True, balance__gt=0, status="overdue")[:20]
                    # need to re-evaluate as queryset slice not allowed for count; convert
                    invoices = list(invoices)
                else:
                    invoices = list(invoices[:20])
            else:
                invoices = list(invoices[:20])
            for inv in invoices:
                # Idempotency: skip if event already exists for this invoice+rule today
                existing = CommunicationEvent.objects.filter(org=org, invoice=inv, channel=rule.channel, created_at__date=today).exists()
                if existing:
                    continue
                ev = CommunicationEvent.objects.create(
                    org=org,
                    invoice=inv,
                    customer=inv.customer,
                    channel=rule.channel,
                    template_id=rule.template[:128],
                    status="queued",
                    scheduled_for=timezone.now(),
                )
                events.append(str(ev.id))
                created += 1
        return Response({"success": True, "data": {"created": created, "event_ids": events, "message": f"Scheduled {created} reminders via {rules.count()} rule(s) for {today}"}})

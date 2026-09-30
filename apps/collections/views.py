from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from .models import CollectionPolicy, Campaign
from .serializers import CollectionPolicySerializer, CampaignSerializer
from apps.tenancy.org import get_org

class CollectionPolicyView(generics.RetrieveUpdateAPIView):
    serializer_class = CollectionPolicySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        org = get_org(self.request)
        if org is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Organization context required")
        obj, _ = CollectionPolicy.objects.get_or_create(org=org, defaults={"reminder_intervals": [0, 3, 7]})
        return obj

class CampaignListCreate(generics.ListCreateAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return Campaign.objects.none()
        return Campaign.objects.filter(org=org).order_by("-created_at")

    def perform_create(self, serializer):
        org = get_org(self.request)
        if org:
            from apps.subscriptions.entitlements import check_feature_access
            from rest_framework.exceptions import PermissionDenied
            allowed, reason = check_feature_access(org, "COLLECTION_CAMPAIGNS")
            if not allowed:
                raise PermissionDenied({"detail": reason, "code": "FEATURE_NOT_ENTITLED"})
        serializer.save(org=org)

class CampaignDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return Campaign.objects.none()
        return Campaign.objects.filter(org=org)


class CampaignLaunchView(APIView):
    """POST /api/v1/collections/campaigns/<pk>/launch — Activate a draft campaign."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        org = get_org(request)
        try:
            campaign = Campaign.objects.get(pk=pk, org=org)
        except Campaign.DoesNotExist:
            return Response({"success": False, "message": "Campaign not found"}, status=404)

        if campaign.status not in (Campaign.Status.DRAFT, Campaign.Status.PAUSED):
            return Response(
                {"success": False, "message": f"Cannot launch a campaign with status '{campaign.status}'"},
                status=400,
            )

        campaign.status = Campaign.Status.ACTIVE
        campaign.started_at = timezone.now()
        campaign.save(update_fields=["status", "started_at"])

        # Enqueue communication events for all open invoices matching config
        created = self._enqueue_campaign_events(campaign, org)

        return Response({
            "success": True,
            "data": {
                "campaign_id": str(campaign.id),
                "status": campaign.status,
                "events_created": created,
            }
        })

    def _enqueue_campaign_events(self, campaign, org) -> int:
        """Create CommunicationEvents for all open invoices in this org."""
        from apps.invoices.models import Invoice
        from apps.comms.models import CommunicationEvent

        config = campaign.config or {}
        channel = config.get("channel", "whatsapp")
        template = config.get("template", "Hello {{customer_name}}, this is a reminder from {{business_name}} about invoice {{invoice_number}} for {{amount_due}}. Pay: {{pay_link}}")

        invoices = (
            Invoice.objects.for_org(org)
            .filter(deleted_at__isnull=True, balance__gt=0, status__in=["sent", "partial", "overdue"])
            .select_related("customer")[:200]
        )

        now = timezone.now()
        created = 0
        for inv in invoices:
            idem_key = f"campaign-{campaign.id}-{inv.id}"
            if CommunicationEvent.objects.filter(idempotency_key=idem_key).exists():
                continue
            CommunicationEvent.objects.create(
                org=org,
                invoice=inv,
                customer=inv.customer,
                channel=channel,
                template_id=template,
                status="queued",
                scheduled_for=now,
                idempotency_key=idem_key,
            )
            created += 1
        return created


class CampaignStatsView(APIView):
    """GET /api/v1/collections/campaigns/<pk>/stats — Campaign delivery stats."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        org = get_org(request)
        try:
            campaign = Campaign.objects.get(pk=pk, org=org)
        except Campaign.DoesNotExist:
            return Response({"success": False, "message": "Not found"}, status=404)

        from apps.comms.models import CommunicationEvent
        from django.db.models import Count

        prefix = f"campaign-{campaign.id}-"
        events = CommunicationEvent.objects.filter(
            org=org, idempotency_key__startswith=prefix
        )
        stats = events.values("status").annotate(count=Count("id"))
        breakdown = {s["status"]: s["count"] for s in stats}

        return Response({
            "success": True,
            "data": {
                "campaign_id": str(campaign.id),
                "name": campaign.name,
                "status": campaign.status,
                "total_events": events.count(),
                "breakdown": breakdown,
                "started_at": campaign.started_at,
            }
        })


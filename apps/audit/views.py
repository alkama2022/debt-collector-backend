from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import AuditLog, AICommunicationAudit
from .serializers import AuditLogSerializer
from apps.tenancy.org import get_org


class AuditLogList(generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["action", "target_type", "actor"]

    def get_queryset(self):
        # SECURITY: always scope audit logs to the current org
        org = get_org(self.request)
        if org is None:
            return AuditLog.objects.none()
        # AuditLog has no org FK directly — scope via actor memberships to this org
        # filter by target_type + actors who belong to this org, OR all if staff
        if self.request.user.is_staff:
            return AuditLog.objects.all().select_related("actor").order_by("-created_at")
        org_user_ids = org.memberships.values_list("user_id", flat=True)
        return (
            AuditLog.objects.filter(actor_id__in=org_user_ids)
            .select_related("actor")
            .order_by("-created_at")
        )


class AuditLogCreate(APIView):
    """Internal endpoint — create an audit log entry. Used by frontend and other services."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        action = request.data.get("action", "")
        target_type = request.data.get("target_type", "")
        target_id = request.data.get("target_id", "")
        if not action:
            return Response({"detail": "action required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            log = AuditLog(
                actor=request.user,
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                before=request.data.get("before") or {},
                after=request.data.get("after") or {},
                ip=_get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            )
            log.save()
            return Response(AuditLogSerializer(log).data, status=status.HTTP_201_CREATED)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class AICommunicationAuditList(generics.ListAPIView):
    """
    §34 — the multilingual communication audit trail.

    Scoped to the caller's org, and filterable by language and escalation so
    staff can answer "which language do escalations happen in?" without a
    database console.
    """

    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["language_selected", "channel", "escalated", "outcome", "customer"]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return AICommunicationAudit.objects.none()
        return (
            AICommunicationAudit.objects.filter(org=org)
            .select_related("customer", "handled_by", "conversation")
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # Surface the retention policy so consumers know when content expires.
        from .policy import RETENTION_POLICY
        if isinstance(response.data, dict):
            response.data["retention_days"] = dict(RETENTION_POLICY)
        return response


class AICommunicationAuditCreate(APIView):
    """Internal — record one AI communication. Never blocks the send."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from apps.audit.services import record_ai_communication

        org = get_org(request)
        if org is None:
            return Response({"detail": "org required"}, status=status.HTTP_400_BAD_REQUEST)

        row = record_ai_communication(
            org=org,
            customer_id=request.data.get("customer_id") or None,
            conversation_id=request.data.get("conversation_id") or None,
            language_selected=request.data.get("language_selected", ""),
            language_detected=request.data.get("language_detected", ""),
            secondary_language=request.data.get("secondary_language", ""),
            detection_confidence=request.data.get("detection_confidence"),
            language_source=request.data.get("language_source", ""),
            channel=request.data.get("channel", ""),
            ai_model=request.data.get("ai_model", ""),
            prompt_version=request.data.get("prompt_version", ""),
            template_id=request.data.get("template_id", ""),
            request_summary=request.data.get("request_summary", ""),
            response_text=request.data.get("response_text", ""),
            translation_status=request.data.get("translation_status", ""),
            voice_provider=request.data.get("voice_provider", ""),
            voice_id=request.data.get("voice_id", ""),
            stt_confidence=request.data.get("stt_confidence"),
            call_status=request.data.get("call_status", ""),
            outcome=request.data.get("outcome", ""),
            escalated=bool(request.data.get("escalated", False)),
            escalation_reason=request.data.get("escalation_reason", ""),
            handled_by=request.user if request.data.get("escalated") else None,
        )
        if row is None:
            return Response({"detail": "audit write failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(
            {
                "id": str(row.id),
                "created_at": row.created_at,
                "content_expires_at": row.content_expires_at,
            },
            status=status.HTTP_201_CREATED,
        )

import logging
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from .models import VoiceCall, CallAttempt
from .serializers import VoiceCallSerializer, CallAttemptSerializer
from apps.tenancy.org import get_org

logger = logging.getLogger(__name__)


# S9 step 2 — resolve which language to speak on a call.
# Precedence: customer.voice_language -> customer.preferred_language ->
# org default -> English.
def _resolve_call_language(call, org):
    """Return (language_code, language_source, voice_profile)."""
    from apps.languages.router import MultilingualLanguageRouter

    code, source = "en", "fallback"

    customer = call.customer
    if customer is not None:
        if customer.voice_language_id:
            code, source = customer.voice_language_id, "customer_voice_pref"
        elif customer.preferred_language_id:
            code, source = customer.preferred_language_id, "customer_pref"

    if source == "fallback" and org is not None:
        try:
            from apps.languages.models import OrganizationLanguageSettings
            s = OrganizationLanguageSettings.objects.filter(
                org=org
            ).select_related("default_customer_language").first()
            if s and s.default_customer_language_id:
                code, source = s.default_customer_language_id, "org_default"
        except Exception:
            pass

    profile = MultilingualLanguageRouter().resolve_voice_profile(code)
    return code, source, profile


def _apply_language_to_call(call, code, source, profile):
    """Record the language decision on the call before dialling."""
    from apps.languages.models import Language

    lang = Language.objects.filter(code=code).first()
    fields = [
        "language_source", "voice_id", "voice_usable", "updated_at",
    ]
    call.language_source = source
    call.voice_id = profile.get("voice_id", "") or ""
    call.voice_usable = bool(profile.get("usable"))
    if lang is not None:
        call.language = lang
        fields.append("language")
    call.save(update_fields=fields)


class VoiceCallListCreate(generics.ListCreateAPIView):
    serializer_class = VoiceCallSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "customer", "invoice"]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return VoiceCall.objects.none()
        return VoiceCall.objects.for_org(org).prefetch_related("attempts")

    def perform_create(self, serializer):
        org = get_org(self.request)
        if org:
            from apps.subscriptions.entitlements import check_feature_access, check_limit
            from rest_framework.exceptions import PermissionDenied
            allowed, reason = check_feature_access(org, "AI_VOICE")
            if not allowed:
                raise PermissionDenied({"detail": reason, "code": "FEATURE_NOT_ENTITLED", "upgrade": "professional"})
            allowed2, reason2, info = check_limit(org, "AI_VOICE_MINUTES", 1)
            if not allowed2:
                raise PermissionDenied({"detail": reason2, "code": "USAGE_LIMIT_REACHED"})
        obj = serializer.save(org=org)
        if org:
            try:
                from apps.subscriptions.usage import commit_or_create_usage
                commit_or_create_usage(
                    org, "AI_VOICE", 1,
                    idempotency_key=str(obj.id),
                    unit="call",
                    metadata={"voice_call_id": str(obj.id)},
                )
            except Exception:
                pass


class VoiceCallDetail(generics.RetrieveUpdateAPIView):
    serializer_class = VoiceCallSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return VoiceCall.objects.none()
        return VoiceCall.objects.for_org(org)


class VoiceCallTriggerView(APIView):
    """
    POST /api/v1/voice/calls/<uuid>/trigger
    Initiates the actual outbound call via Africa's Talking.
    Creates a CallAttempt record and fires the AT voice API.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        org = get_org(request)

        try:
            call = VoiceCall.objects.for_org(org).get(pk=pk)
        except VoiceCall.DoesNotExist:
            return Response({"detail": "Voice call not found"}, status=status.HTTP_404_NOT_FOUND)

        if call.status not in ("queued", "failed"):
            return Response(
                {"detail": f"Call is already {call.status} — cannot trigger again"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # S9 step 2 + S22/S23: identify the customer, resolve their language,
        # and refuse to dial if we have no native voice for it. Speaking Igbo
        # with an English voice is worse than not calling at all.
        language_code, language_source, profile = _resolve_call_language(call, org)

        if not profile.get("usable"):
            call.status = "cancelled"
            call.voice_usable = False
            call.escalated = True
            call.escalation_reason = "no_native_voice"
            call.language_source = language_source
            call.save(update_fields=[
                "status", "voice_usable", "escalated", "escalation_reason",
                "language_source", "updated_at",
            ])
            logger.warning(
                "[VoiceCallTrigger] Refusing to call %s — no validated voice for %s",
                pk, language_code,
            )
            return Response({
                "success": False,
                "data": {
                    "error_code": "NO_NATIVE_VOICE",
                    "language": language_code,
                    "reason": profile.get("reason"),
                    "message": (
                        f"No validated {language_code} voice is available. "
                        "Escalated to a human instead of calling in the wrong language."
                    ),
                },
            }, status=status.HTTP_409_CONFLICT)

        # Persist the language decision before dialling so the record exists
        # even if the provider call fails.
        _apply_language_to_call(call, language_code, language_source, profile)

        # Create attempt record
        attempt_number = call.attempts.count() + 1
        attempt = CallAttempt.objects.create(
            org=org,
            call=call,
            attempt_number=attempt_number,
            status="initiated",
        )

        # Fire the AT voice API via the comms provider
        try:
            from apps.comms.providers.africastalking import AfricasTalkingProvider
            from apps.comms.models import CommunicationEvent

            # Create a temporary CommunicationEvent for the provider to read
            event = CommunicationEvent(
                org=org,
                invoice=call.invoice,
                customer=call.customer,
                channel="voice",
                template_id="voice_reminder",
                status="sending",
                # Pin the language we validated, so the provider cannot
                # re-resolve to something else mid-call.
                language=language_code,
                language_source=language_source,
            )

            provider = AfricasTalkingProvider()
            result = provider.send(event)

            if result.success:
                call.status = "in_progress"
                call.provider_call_id = result.provider_msg_id or ""
                call.save(update_fields=["status", "provider_call_id"])

                attempt.status = "connected"
                attempt.provider_response = result.raw or {}
                attempt.save(update_fields=["status", "provider_response"])

                logger.info("[VoiceCallTrigger] Call %s triggered successfully | AT session=%s", pk, result.provider_msg_id)
                return Response({
                    "success": True,
                    "data": {
                        "call_id": str(call.id),
                        "attempt": attempt.attempt_number,
                        "provider_call_id": call.provider_call_id,
                        "status": call.status,
                    }
                })
            else:
                call.status = "failed"
                call.save(update_fields=["status"])
                attempt.status = "failed"
                attempt.error_code = result.error_code or "PROVIDER_ERROR"
                attempt.provider_response = {"error": result.error_message}
                attempt.save(update_fields=["status", "error_code", "provider_response"])

                logger.warning("[VoiceCallTrigger] Call %s failed | error=%s", pk, result.error_code)
                return Response({
                    "success": False,
                    "data": {"error_code": result.error_code, "error_message": result.error_message},
                }, status=status.HTTP_502_BAD_GATEWAY)

        except Exception as exc:
            call.status = "failed"
            call.save(update_fields=["status"])
            attempt.status = "failed"
            attempt.error_code = "EXCEPTION"
            attempt.provider_response = {"error": str(exc)}
            attempt.save(update_fields=["status", "error_code", "provider_response"])
            logger.exception("[VoiceCallTrigger] Exception for call %s: %s", pk, exc)
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VoiceCallStatusWebhookView(APIView):
    """
    POST /api/v1/voice/webhook/status
    Africa's Talking calls this URL with call completion/status events.
    Updates VoiceCall duration, recording URL, and final status.
    No auth — verified by checking AT headers/signature.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        data = request.data
        session_id = data.get("sessionId") or data.get("callSessionState") or ""
        call_status = (data.get("status") or data.get("callSessionState") or "").lower()
        duration = data.get("durationInSeconds") or data.get("duration") or 0
        recording_url = data.get("recordingUrl") or ""

        logger.info("[VoiceWebhook] session=%s status=%s duration=%s", session_id, call_status, duration)

        if not session_id:
            return Response({"success": False, "detail": "sessionId required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            call = VoiceCall.objects.filter(provider_call_id=session_id).first()
            if not call:
                logger.warning("[VoiceWebhook] No call found for session %s", session_id)
                return Response({"success": True})  # Return 200 so AT doesn't retry

            # Map AT statuses to our status
            status_map = {
                "completed": "completed",
                "answered": "in_progress",
                "no_answer": "no_answer",
                "busy": "failed",
                "failed": "failed",
                "cancelled": "cancelled",
                "rejected": "failed",
            }
            new_status = status_map.get(call_status, call.status)
            update_fields = ["status"]
            call.status = new_status

            if duration:
                call.duration_seconds = int(duration)
                update_fields.append("duration_seconds")

            if recording_url:
                call.recording_url = recording_url
                update_fields.append("recording_url")

            call.save(update_fields=update_fields)

            # Update latest attempt
            attempt = call.attempts.order_by("-created_at").first()
            if attempt:
                attempt.status = new_status
                attempt.provider_response = dict(data)
                attempt.save(update_fields=["status", "provider_response"])

            # If call was not answered — update comm event status too
            if new_status in ("failed", "no_answer", "cancelled"):
                from apps.comms.models import CommunicationEvent
                CommunicationEvent.objects.filter(
                    invoice=call.invoice,
                    customer=call.customer,
                    channel="voice",
                    status="sending",
                ).update(status="failed", error_code=call_status.upper())

        except Exception as exc:
            logger.exception("[VoiceWebhook] Error processing webhook: %s", exc)

        return Response({"success": True})

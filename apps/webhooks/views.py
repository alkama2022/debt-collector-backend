import hmac
import hashlib
import uuid
import logging
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from .models import WebhookEvent

logger = logging.getLogger(__name__)


def verify_signature(provider, payload_raw, signature):
    """
    HMAC verification. If secret not set, accept all (dev mode).

    Paystack: HMAC-SHA512 of raw body, compared against X-Paystack-Signature header.
    Flutterwave: plain-string comparison of verif-hash header against FLUTTERWAVE_SECRET_KEY
                 (FLW does NOT use HMAC — the header IS the secret).
    """
    if provider == "paystack":
        secret = getattr(settings, "PAYSTACK_WEBHOOK_SECRET", "")
        if not secret:
            return True
        if not signature:
            return False
        expected = hmac.new(secret.encode(), payload_raw, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)

    elif provider == "flutterwave":
        secret = getattr(settings, "FLUTTERWAVE_SECRET_KEY", "")
        if not secret:
            return True
        if not signature:
            return False
        # Flutterwave sends the raw secret as the verif-hash header value
        return hmac.compare_digest(secret, signature)

    # manual / unknown — no signature required
    return True


class PaymentWebhookView(APIView):
    """
    POST /api/v1/webhooks/payments/<provider>
    Handles Paystack and Flutterwave payment confirmation webhooks.
    Returns 200 immediately — actual processing is async via Celery.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, provider):
        provider = provider.lower()
        if provider not in ("paystack", "flutterwave", "manual"):
            return Response({"success": False, "message": "Unknown provider"}, status=status.HTTP_400_BAD_REQUEST)

        raw = request.body or b"{}"
        sig = (
            request.headers.get("x-paystack-signature")
            or request.headers.get("X-Paystack-Signature")
            or request.headers.get("verif-hash")
            or request.headers.get("X-Signature")
            or ""
        )
        if not verify_signature(provider, raw, sig):
            logger.warning("[Webhook/%s] Invalid signature", provider)
            return Response({"success": False, "message": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

        data = request.data if isinstance(request.data, dict) else {}
        event_id = str(
            data.get("event_id") or data.get("id") or data.get("event") or uuid.uuid4()
        )

        # Idempotent store — get or create
        event, created = WebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={"provider": provider, "payload": data, "signature": sig},
        )
        if not created and event.provider != provider:
            event.provider = provider
            event.save(update_fields=["provider"])

        # Async processing — return immediately
        try:
            from .tasks import process_webhook_event
            process_webhook_event.delay(str(event.id))
        except Exception as exc:
            logger.error("[Webhook/%s] Failed to queue task: %s", provider, exc)

        logger.info("[Webhook/%s] Received event %s (new=%s)", provider, event_id, created)
        return Response(
            {"success": True, "data": {"event_id": event.event_id, "processed": event.processed}},
            status=status.HTTP_200_OK,
        )


class ATDeliveryReceiptView(APIView):
    """
    POST /api/v1/webhooks/at/delivery
    Africa's Talking calls this URL with SMS/WhatsApp delivery receipts.
    Updates CommunicationEvent.status to DELIVERED or FAILED.
    No auth — AT doesn't send auth headers. We accept all and ignore unknown IDs.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        data = request.data
        # AT delivery receipt format:
        # {"id": "ATXid_xxx", "status": "Success", "phoneNumber": "+234...", "networkCode": "62120", ...}
        msg_id = data.get("id") or data.get("messageId") or ""
        at_status = (data.get("status") or "").lower()
        failure_reason = data.get("failureReason") or ""

        logger.info("[AT-Delivery] msg_id=%s status=%s", msg_id, at_status)

        if not msg_id:
            return Response({"success": False}, status=status.HTTP_400_BAD_REQUEST)

        # Map AT status to our status
        status_map = {
            "success": "delivered",
            "sent": "sent",
            "submitted": "sent",
            "buffered": "sent",
            "rejected": "failed",
            "failed": "failed",
        }
        new_status = status_map.get(at_status, None)
        if not new_status:
            logger.debug("[AT-Delivery] Unknown status %s for msg %s — ignoring", at_status, msg_id)
            return Response({"success": True})

        try:
            from apps.comms.models import CommunicationEvent
            updated = CommunicationEvent.objects.filter(
                provider_msg_id=msg_id,
                status__in=["sending", "sent"],
            ).update(
                status=new_status,
                error_code=failure_reason[:64] if failure_reason and new_status == "failed" else "",
            )
            if updated:
                logger.info("[AT-Delivery] Updated %d event(s) for msg %s → %s", updated, msg_id, new_status)
            else:
                logger.debug("[AT-Delivery] No event found for msg_id=%s", msg_id)
        except Exception as exc:
            logger.exception("[AT-Delivery] Error updating delivery status: %s", exc)

        return Response({"success": True})


class ATInboundMessageView(APIView):
    """
    POST /api/v1/webhooks/at/inbound
    Africa's Talking calls this when a customer replies to an SMS or WhatsApp message.
    Triggers the AI conversation engine to process the reply.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        data = request.data
        from_number = data.get("from") or data.get("phoneNumber") or ""
        message_text = data.get("text") or data.get("body") or ""
        to_number = data.get("to") or ""
        channel = "sms"  # AT doesn't distinguish in this webhook but we can infer

        logger.info("[AT-Inbound] from=%s text=%s", from_number, message_text[:100])

        if not from_number or not message_text:
            return Response({"success": False, "detail": "from and text required"}, status=status.HTTP_400_BAD_REQUEST)

        # Queue AI processing as async Celery task
        try:
            from .tasks import process_inbound_message
            process_inbound_message.delay(
                phone=from_number,
                message=message_text,
                channel=channel,
            )
        except Exception as exc:
            logger.error("[AT-Inbound] Failed to queue message processing: %s", exc)

        # Always return 200 so AT doesn't retry
        return Response({"success": True})

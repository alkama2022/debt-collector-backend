"""
africastalking.py — Africa's Talking provider for WhatsApp, SMS, and Voice.
Docs: https://developers.africastalking.com/

Required settings (from env):
    AFRICASTALKING_USERNAME  — your AT username (use 'sandbox' for testing)
    AFRICASTALKING_API_KEY   — your AT API key
    AFRICASTALKING_SENDER_ID — optional SMS sender ID (alphanumeric, e.g. CollectNaija)
    AFRICASTALKING_SHORTCODE — optional shortcode for SMS

Voice uses AT's voice call API + text-to-speech.
WhatsApp uses AT's WhatsApp Business API (requires AT WhatsApp approval).
SMS uses AT's SMS API (works immediately with sandbox).
"""
import logging
import requests
from django.conf import settings
from .base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)

AT_SMS_URL = "https://api.africastalking.com/version1/messaging"
AT_VOICE_URL = "https://voice.africastalking.com/call"
AT_WHATSAPP_URL = "https://chat.africastalking.com/whatsapp/message"
AT_SANDBOX_SMS_URL = "https://api.sandbox.africastalking.com/version1/messaging"
AT_SANDBOX_VOICE_URL = "https://voice.sandbox.africastalking.com/call"


def _is_sandbox() -> bool:
    username = getattr(settings, "AFRICASTALKING_USERNAME", "sandbox")
    return username == "sandbox"


def _headers() -> dict:
    return {
        "apiKey": getattr(settings, "AFRICASTALKING_API_KEY", ""),
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }


class AfricasTalkingProvider(BaseProvider):
    """Africa's Talking SMS/WhatsApp/Voice provider."""

    channel = "sms"  # Default; factory overrides for voice

    def send(self, event) -> ProviderResult:
        channel = event.channel.lower()
        if channel == "sms":
            return self._send_sms(event)
        elif channel == "whatsapp":
            return self._send_whatsapp(event)
        elif channel == "voice":
            return self._send_voice(event)
        elif channel == "email":
            # Fallback to email provider
            from .email_provider import EmailProvider
            return EmailProvider().send(event)
        else:
            return ProviderResult(
                success=False,
                error_code="UNKNOWN_CHANNEL",
                error_message=f"Unknown channel: {channel}",
            )

    def _send_sms(self, event) -> ProviderResult:
        phone = self._get_phone(event)
        if not phone:
            return ProviderResult(
                success=False,
                error_code="NO_PHONE",
                error_message="Customer has no phone number",
            )

        body = self._render_template(event)
        username = getattr(settings, "AFRICASTALKING_USERNAME", "sandbox")
        sender_id = getattr(settings, "AFRICASTALKING_SENDER_ID", None)
        url = AT_SANDBOX_SMS_URL if _is_sandbox() else AT_SMS_URL

        payload = {
            "username": username,
            "to": phone,
            "message": body[:160],  # SMS limit
        }
        if sender_id:
            payload["from"] = sender_id

        try:
            resp = requests.post(url, data=payload, headers=_headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            logger.info("[AT-SMS] sent to %s | resp=%s", phone, data)

            # Parse AT response
            sms_data = data.get("SMSMessageData", {})
            recipients = sms_data.get("Recipients", [])
            if recipients:
                r = recipients[0]
                status = r.get("status", "")
                if status == "Success":
                    cost_str = r.get("cost", "NGN 0").replace("NGN ", "").strip()
                    try:
                        cost_minor = int(float(cost_str) * 100)
                    except ValueError:
                        cost_minor = 0
                    return ProviderResult(
                        success=True,
                        provider_msg_id=r.get("messageId", ""),
                        cost_minor=cost_minor,
                        raw=data,
                    )
                else:
                    return ProviderResult(
                        success=False,
                        error_code=status,
                        error_message=r.get("statusCode", "Unknown AT error"),
                        raw=data,
                    )
            return ProviderResult(success=False, error_code="NO_RECIPIENTS", raw=data)

        except requests.RequestException as e:
            logger.error("[AT-SMS] Request failed: %s", e)
            return ProviderResult(
                success=False,
                error_code="REQUEST_FAILED",
                error_message=str(e),
            )

    def _send_whatsapp(self, event) -> ProviderResult:
        """
        Africa's Talking WhatsApp API.
        Note: Requires AT WhatsApp Business account approval.
        Falls back to SMS if not configured.
        """
        phone = self._get_phone(event)
        if not phone:
            return ProviderResult(
                success=False,
                error_code="NO_PHONE",
                error_message="Customer has no phone number",
            )

        username = getattr(settings, "AFRICASTALKING_USERNAME", "sandbox")
        whatsapp_sender = getattr(settings, "AFRICASTALKING_WHATSAPP_SENDER", None)

        # If no WhatsApp sender configured, fall back to SMS
        if not whatsapp_sender:
            logger.info("[AT-WhatsApp] No sender configured — falling back to SMS")
            # Temporarily change channel for SMS send
            event.channel = "sms"
            result = self._send_sms(event)
            event.channel = "whatsapp"
            return result

        body = self._render_template(event)

        payload = {
            "username": username,
            "productName": whatsapp_sender,
            "recipients": [{"phoneNumber": phone, "message": {"body": {"type": "TEXT", "text": body}}}],
        }

        try:
            resp = requests.post(
                AT_WHATSAPP_URL,
                json=payload,
                headers={
                    "apiKey": getattr(settings, "AFRICASTALKING_API_KEY", ""),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("[AT-WhatsApp] sent to %s | resp=%s", phone, data)

            entries = data.get("entries", [])
            if entries and entries[0].get("status") == "success":
                return ProviderResult(
                    success=True,
                    provider_msg_id=entries[0].get("messageId", ""),
                    raw=data,
                )
            return ProviderResult(
                success=False,
                error_code=entries[0].get("status", "UNKNOWN") if entries else "NO_ENTRIES",
                error_message=str(entries),
                raw=data,
            )

        except requests.RequestException as e:
            logger.error("[AT-WhatsApp] Request failed: %s", e)
            return ProviderResult(
                success=False,
                error_code="REQUEST_FAILED",
                error_message=str(e),
            )

    def _send_voice(self, event) -> ProviderResult:
        """
        Africa's Talking Voice API — initiates an outbound call.
        The call plays a TTS debt reminder when answered.
        """
        phone = self._get_phone(event)
        if not phone:
            return ProviderResult(
                success=False,
                error_code="NO_PHONE",
                error_message="Customer has no phone number",
            )

        username = getattr(settings, "AFRICASTALKING_USERNAME", "sandbox")
        caller_id = getattr(settings, "AFRICASTALKING_CALLER_ID", None)
        url = AT_SANDBOX_VOICE_URL if _is_sandbox() else AT_VOICE_URL

        payload = {
            "username": username,
            "to": phone,
        }
        if caller_id:
            payload["from"] = caller_id

        try:
            resp = requests.post(url, data=payload, headers=_headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            logger.info("[AT-Voice] call initiated to %s | resp=%s", phone, data)

            entries = data.get("entries", [])
            if entries and entries[0].get("status") == "Success":
                return ProviderResult(
                    success=True,
                    provider_msg_id=entries[0].get("sessionId", ""),
                    raw=data,
                )
            return ProviderResult(
                success=False,
                error_code="CALL_FAILED",
                error_message=str(data),
                raw=data,
            )

        except requests.RequestException as e:
            logger.error("[AT-Voice] Request failed: %s", e)
            return ProviderResult(
                success=False,
                error_code="REQUEST_FAILED",
                error_message=str(e),
            )

    def test_connection(self) -> bool:
        """Test AT API connectivity by fetching account balance."""
        username = getattr(settings, "AFRICASTALKING_USERNAME", "sandbox")
        url = "https://api.sandbox.africastalking.com/version1/user" if _is_sandbox() \
              else "https://api.africastalking.com/version1/user"
        try:
            resp = requests.get(
                url,
                params={"username": username},
                headers={"apiKey": getattr(settings, "AFRICASTALKING_API_KEY", ""), "Accept": "application/json"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("[AT] Connection test failed: %s", e)
            return False

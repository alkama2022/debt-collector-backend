"""
mock.py — Mock provider for development and testing.
Logs what would be sent but does NOT make real API calls.
Marks all events as 'sent' immediately.
"""
import logging
from .base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)


class MockProvider(BaseProvider):
    """
    Simulates sending without any real network calls.
    All messages are logged and marked as sent.
    Used when no real provider keys are configured.
    """
    channel = "all"

    def send(self, event) -> ProviderResult:
        body = self._render_template(event)
        phone = self._get_phone(event)
        email = self._get_email(event)

        target = phone if event.channel in ("whatsapp", "sms", "voice") else email
        logger.info(
            "[MOCK] Would send %s to %s | org=%s | invoice=%s | body=%r",
            event.channel.upper(),
            target,
            event.org_id,
            event.invoice_id,
            body[:80],
        )

        return ProviderResult(
            success=True,
            provider_msg_id=f"mock-{event.id}",
            cost_minor=0,
            raw={"mock": True, "target": target, "body": body},
        )

    def test_connection(self) -> bool:
        logger.info("[MOCK] Connection test — always passes")
        return True

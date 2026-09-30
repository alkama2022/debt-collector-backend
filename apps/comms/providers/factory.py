"""
factory.py — Provider factory that selects the right provider based on settings.

Priority:
  1. If WHATSAPP_PROVIDER == 'mock' → MockProvider (always)
  2. If AFRICASTALKING_API_KEY is set → AfricasTalkingProvider
  3. Otherwise → MockProvider (safe fallback with logging)

Per-channel override is also supported:
  SMS_PROVIDER = 'africastalking' | 'mock'
  EMAIL_PROVIDER = 'smtp' | 'mock'
  VOICE_PROVIDER = 'africastalking' | 'mock'
"""
import logging
from django.conf import settings
from .base import BaseProvider

logger = logging.getLogger(__name__)


def get_provider(channel: str) -> BaseProvider:
    """
    Return the appropriate provider instance for the given channel.

    Args:
        channel: 'whatsapp', 'sms', 'email', 'voice'

    Returns:
        BaseProvider instance
    """
    channel = channel.lower()

    if channel == "email":
        return _get_email_provider()
    elif channel == "voice":
        return _get_voice_provider()
    else:
        return _get_messaging_provider(channel)


def _get_messaging_provider(channel: str) -> BaseProvider:
    """Get provider for WhatsApp or SMS."""
    from .mock import MockProvider
    from .africastalking import AfricasTalkingProvider

    configured_provider = getattr(settings, "WHATSAPP_PROVIDER", "mock").lower()
    at_key = getattr(settings, "AFRICASTALKING_API_KEY", "")

    if configured_provider == "mock" or not at_key:
        if configured_provider != "mock" and not at_key:
            logger.warning(
                "[CommsFactory] No AFRICASTALKING_API_KEY set — using MockProvider for %s", channel
            )
        return MockProvider()

    if configured_provider == "africastalking":
        return AfricasTalkingProvider()

    # Unknown provider — safe fallback
    logger.error("[CommsFactory] Unknown WHATSAPP_PROVIDER=%r — using MockProvider", configured_provider)
    return MockProvider()


def _get_email_provider() -> BaseProvider:
    """Get email provider."""
    from .email_provider import EmailProvider
    from .mock import MockProvider

    email_backend = getattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
    email_host = getattr(settings, "EMAIL_HOST", "")
    email_provider_setting = getattr(settings, "EMAIL_PROVIDER", "auto").lower()

    if email_provider_setting == "mock":
        return MockProvider()

    # If using console backend (dev), still use EmailProvider (Django handles it)
    # If using SMTP backend, use EmailProvider
    return EmailProvider()


def _get_voice_provider() -> BaseProvider:
    """Get voice provider."""
    from .mock import MockProvider
    from .africastalking import AfricasTalkingProvider

    voice_provider = getattr(settings, "VOICE_PROVIDER", getattr(settings, "WHATSAPP_PROVIDER", "mock")).lower()
    at_key = getattr(settings, "AFRICASTALKING_API_KEY", "")

    if voice_provider == "africastalking" and at_key:
        return AfricasTalkingProvider()

    if voice_provider != "mock":
        logger.warning("[CommsFactory] Voice provider %r not configured — using MockProvider", voice_provider)
    return MockProvider()

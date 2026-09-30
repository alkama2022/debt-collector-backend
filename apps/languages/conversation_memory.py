"""
Conversation language memory (§20).

The spec is explicit: "Do not make the AI rediscover the customer's language on
every message when a trusted preference already exists."

This service is the single place that decides a conversation's language and
keeps the counters honest, so views and tasks cannot drift apart.

Responsibilities:
  * seed a conversation from the customer's trusted preference
  * carry the current language forward across messages
  * count genuine language switches (§8) separately from code switches (§27)
  * stamp `language_updated_at` so staleness is observable
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class LanguageMemory:
    language: str
    source: str
    is_switch: bool = False
    is_code_switch: bool = False
    confidence: Optional[Decimal] = None
    secondary_language: Optional[str] = None


# Mirrors AIConversation.LanguageSource. Kept as plain strings so this module
# stays importable without Django.
SOURCE_CUSTOMER_PREFERRED = "customer_preferred"
SOURCE_DETECTED = "detected"
SOURCE_CONVERSATION_MEMORY = "conversation_memory"
SOURCE_BUSINESS_FALLBACK = "business_fallback"
SOURCE_SYSTEM_FALLBACK = "system_fallback"


def resolve_for_conversation(
    router,
    conversation=None,
    customer=None,
    org=None,
    inbound_text: str = "",
    customer_id: Optional[str] = None,
) -> LanguageMemory:
    """
    Decide the language for this turn and describe how it was chosen.

    Priority (§5): customer explicit preference -> business configuration ->
    AI detection -> safe fallback, with §20 conversation memory inserted so a
    trusted preference is not re-derived every message.
    """
    # What the conversation is currently using, if anything.
    current = None
    if conversation is not None:
        current = getattr(conversation, "conversation_language_id", None) or (
            conversation.conversation_language.code
            if getattr(conversation, "conversation_language", None) else None
        )
    preferred = None
    if customer_id and inbound_text:
        preferred = None
    # Trusted preference from the customer record.
    customer_pref = router.get_customer_language(customer) if customer is not None else None

    business_settings = None
    if org is not None:
        try:
            from apps.languages.models import OrganizationLanguageSettings
            business_settings = OrganizationLanguageSettings.objects.filter(
                org=org
            ).select_related(
                "dashboard_language", "default_customer_language", "fallback_language"
            ).first()
        except Exception:
            business_settings = None

    resolved = router.resolve_response_language(
        customer=customer,
        detected=None,
        business_settings=business_settings,
        confidence=None,
        conversation_language=current,
    )

    # Detection is a safety check, not the primary signal when we already have
    # a trusted preference.
    detected = None
    confidence = None
    secondary = None
    is_code_switch = False
    if inbound_text:
        detection = router.resolve_code_switched_language(
            inbound_text, customer=customer,
            business_settings=business_settings,
            conversation_language=current,
        )
        detected = detection.get("primary")
        confidence = detection.get("detection_confidence")
        secondary = detection.get("secondary")
        is_code_switch = bool(detection.get("is_code_switched"))

        # A confident, deliberate switch (§8) is honoured and becomes the new
        # conversation language. §8 forbids making it permanent on the customer
        # record from a single message — we only move the conversation.
        if (
            detection.get("is_code_switched") is False
            and current
            and detected
            and detected != current
            and confidence is not None
            and confidence >= Decimal("0.80")
            and detected == customer_pref
        ):
            resolved = detected

    is_switch = bool(current and resolved and current != resolved)
    if is_switch:
        source = SOURCE_DETECTED
    elif current:
        source = SOURCE_CONVERSATION_MEMORY
    elif customer_pref:
        source = SOURCE_CUSTOMER_PREFERRED
    elif business_settings is not None:
        source = SOURCE_BUSINESS_FALLBACK
    else:
        source = SOURCE_SYSTEM_FALLBACK

    return LanguageMemory(
        language=resolved or "en",
        source=source,
        is_switch=is_switch,
        is_code_switch=is_code_switch,
        confidence=confidence,
        secondary_language=secondary,
    )


def apply_to_conversation(conversation, memory: LanguageMemory) -> None:
    """Persist a resolved LanguageMemory onto a conversation instance."""
    from apps.languages.models import Language

    if conversation is None:
        return

    if memory.is_switch:
        conversation.language_switch_count = (conversation.language_switch_count or 0) + 1
    if memory.is_code_switch:
        conversation.code_switch_count = (conversation.code_switch_count or 0) + 1

    lang = Language.objects.filter(code=memory.language).first()
    if lang is not None:
        conversation.conversation_language = lang
    conversation.language_source = memory.source
    conversation.language_updated_at = _now()
    conversation.save(update_fields=[
        "conversation_language", "language_source", "language_updated_at",
        "language_switch_count", "code_switch_count", "updated_at",
    ])


def _now():
    from django.utils import timezone
    return timezone.now()

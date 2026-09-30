"""
Internal translation for business staff (§33).

A Hausa-speaking business owner may have a customer who writes in Yoruba. The
owner still needs to read that message to do their job.

Two rules make this safe:

1. **The original is sacred.** `content` is never modified or overwritten. A
   translation is stored alongside it, tagged with its source and target
   language and a confidence score.
2. **A translation is never presented as the customer's words.** Callers get
   the original and the rendering separately so the UI can label them
   "View original message" / "View translated summary" (§32).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# Only surface a translation to staff when the system is reasonably sure of it.
# Below this, staff should see the original and a "needs review" flag rather
# than a confident-looking but possibly wrong rendering.
STAFF_TRANSLATION_MIN_CONFIDENCE = Decimal("0.70")


@dataclass
class StaffTranslation:
    """A translation for staff eyes only. Never replaces the original."""
    original_text: str
    original_language: str
    translated_text: str
    translated_language: str
    confidence: Decimal
    provider: str

    @property
    def is_reliable(self) -> bool:
        return self.confidence >= STAFF_TRANSLATION_MIN_CONFIDENCE

    def as_dict(self) -> dict:
        return {
            "original_text": self.original_text,
            "original_language": self.original_language,
            "translated_text": self.translated_text,
            "translated_language": self.translated_language,
            "confidence": float(self.confidence),
            "is_reliable": self.is_reliable,
            "provider": self.provider,
        }


def needs_translation(text: str, source_language: str, target_language: str) -> bool:
    """True when staff would benefit from a translation."""
    if not text or not text.strip():
        return False
    src = (source_language or "").strip().lower()
    dst = (target_language or "").strip().lower()
    if not dst:
        return False
    # Same language (or an unknown source) means nothing to translate.
    return bool(src) and src != dst


def build_staff_translation(
    original_text: str,
    original_language: str,
    target_language: str,
    translate_fn=None,
) -> Optional[StaffTranslation]:
    """
    Produce a staff-facing translation, or None when not needed.

    `translate_fn(text, source, target) -> (str, Decimal, str)` is injected so
    this module stays free of provider dependencies and is unit-testable. The
    caller supplies the LLM-backed implementation in production; without one we
    return None rather than fabricate a translation.
    """
    if not needs_translation(original_text, original_language, target_language):
        return None
    if translate_fn is None:
        return None
    translated, confidence, provider = translate_fn(
        original_text, original_language, target_language
    )
    if not translated:
        return None
    return StaffTranslation(
        original_text=original_text,
        original_language=original_language,
        translated_text=translated,
        translated_language=target_language,
        confidence=Decimal(str(confidence)),
        provider=provider,
    )

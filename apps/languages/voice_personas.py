"""
Multilingual voice personas (§22).

A single TTS voice cannot sound native across Nigerian languages. This module
holds per-language voice configuration so the voice agent can pick a voice that
actually speaks that language, at a rate that suits how the language is spoken.

Deliberately Django-free so it can be unit-tested and imported by the router
without touching the ORM.

`text_to_speech_supported` in the Language registry is the gate: a language
without a validated provider voice must never silently fall back to an English
voice, because that is exactly the "robotic translation" outcome §22 warns
about. `resolve_voice` reports that as an explicit `usable: False` so the
caller can escalate (§23) rather than send a bad call.
"""

from dataclasses import dataclass, field
from typing import Optional

# Voice ids follow the common <lang>-<region>-Neural convention. These are
# provider-agnostic placeholders; swap the concrete ids per provider in
# deployment config rather than editing call sites.
VOICE_PERSONAS = {
    "en": {
        "voice_id": "en-NG-Neural",
        "gender": "neutral",
        "rate": "1.0",
        "pitch": "0",
        "tone": "warm, professional, unhurried",
        "formality": "professional",
        "pronunciation": {
            "naira": "Naira",
            "digit_grouping": "3,000",
            "read_plus": "plus",
        },
        "notes": "Nigerian English; avoid US-centred number reading habits.",
    },
    "ha": {
        "voice_id": "ha-NG-Neural",
        "gender": "male",
        "rate": "0.95",
        "pitch": "0",
        "tone": "respectful, calm, elder-honouring",
        "formality": "formal",
        "pronunciation": {
            "naira": "Naira",
            "digit_grouping": "3,000",
            "glottal": "imploded consonants in 'ɗ' and 'ƙ' must remain distinct",
        },
        "notes": "Hausa implosives are phonemic; a voice that flattens them is unusable.",
    },
    "yo": {
        "voice_id": "yo-NG-Neural",
        "gender": "neutral",
        "rate": "0.95",
        "pitch": "0",
        "tone": "respectful, warm, elder-respecting",
        "formality": "formal",
        "pronunciation": {
            "naira": "Naira",
            "digit_grouping": "3,000",
            "tone_marking": "Yoruba is a tonal language; do not flatten pitch",
        },
        "notes": "Tone marks (acute/grave) change meaning. Wrong tone can invert a request.",
    },
    "ig": {
        "voice_id": "ig-NG-Neural",
        "gender": "neutral",
        "rate": "0.95",
        "pitch": "0",
        "tone": "warm, communal, respectful",
        "formality": "professional",
        "pronunciation": {
            "naira": "Naira",
            "digit_grouping": "3,000",
            "nasalisation": "preserve nasal vowels in 'ị' and 'ụ'",
        },
        "notes": "Underdots distinguish homophones; keep them audible.",
    },
    "pcm": {
        "voice_id": "pcm-NG-Neural",
        "gender": "neutral",
        "rate": "1.05",
        "pitch": "0",
        "tone": "friendly, direct, encouraging",
        "formality": "informal",
        "pronunciation": {
            "naira": "Naira",
            "digit_grouping": "3,000",
            "stress": "phrase-final emphasis is natural in Pidgin",
        },
        "notes": "Slightly faster; Pidgin is conversational and compresses phrases.",
    },
}

# Languages with a registered persona. ff/kr/tiv deliberately have none yet:
# shipping a language on the voice channel before a validated voice exists
# would violate §25/§26.
REGISTERED_VOICE_LANGUAGES = frozenset(VOICE_PERSONAS)


def get_voice_persona(language_code: str) -> Optional[dict]:
    """Return the voice persona for a language, or None if not yet validated."""
    if not language_code:
        return None
    return VOICE_PERSONAS.get(language_code.strip().lower())


def has_native_voice(language_code: str) -> bool:
    return (language_code or "").strip().lower() in REGISTERED_VOICE_LANGUAGES


def resolve_voice(language_code: str, org=None, allow_english_fallback: bool = False) -> dict:
    """
    Resolve a full voice configuration for a language.

    Returns a dict with `usable` so the caller can decide between speaking and
    escalating.

    `allow_english_fallback` defaults to **False**. Falling back to an English
    voice is the "robotic translation" outcome §22 exists to prevent, and §23
    requires escalation over confidently-wrong communication — so the caller
    has to opt in deliberately rather than inherit a silent downgrade.
    """
    code = (language_code or "en").strip().lower()
    persona = get_voice_persona(code)
    if persona:
        return {
            "language": code,
            "usable": True,
            "is_fallback": False,
            **persona,
        }

    return {
        "language": "en",
        "usable": bool(allow_english_fallback),
        "is_fallback": True,
        "reason": f"no_validated_native_voice_for_{code}",
        "requested_language": code,
        **VOICE_PERSONAS["en"],
    }

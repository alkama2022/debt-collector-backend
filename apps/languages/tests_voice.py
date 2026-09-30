"""
Voice quality gate (§26, voice half).

S26 lists what a language must pass before it is called production ready on
the *voice* channel: speech recognition, pronunciation, numbers, currency,
names, natural speaking speed, background noise, Nigerian accents and code
switching.

Two layers are possible here and only one is useful right now:

  1. **Configuration gates** (implemented below) — assert that a language has a
     complete, sane voice persona and that the TTS/STT registry flags agree
     with it. These run with no audio and catch the failures that actually
     happen: a persona missing a rate, a language marked TTS-supported with no
     persona, an implausible speaking rate.

  2. **Audio quality gates** (NOT implemented) — real recorded speech scored
     for recognition accuracy, noise robustness and accent handling. These
     need audio fixtures and a speech provider. There is no honest way to
     simulate them, so asserting them would be theatre: it would report
     "passing" for a language nobody has ever tested with a microphone.

Stage-2 languages must therefore fail this gate rather than be waved through.
"""

import unittest

from apps.languages.voice_personas import (
    REGISTERED_VOICE_LANGUAGES,
    VOICE_PERSONAS,
    has_native_voice,
    resolve_voice,
)

# Languages cleared for the voice channel.
PRODUCTION_VOICE_LANGUAGES = ("en", "ha", "yo", "ig", "pcm")

# Speaking rate bounds. Below ~0.7 a collection message sounds robotic; above
# ~1.3 financial figures stop being reliably understood.
MIN_RATE = 0.7
MAX_RATE = 1.3


class VoicePersonaCompletenessTests(unittest.TestCase):
    """Every production voice language declares everything TTS needs."""

    REQUIRED = ("voice_id", "gender", "rate", "tone", "formality", "pronunciation")

    def test_all_production_languages_have_complete_personas(self):
        for code in PRODUCTION_VOICE_LANGUAGES:
            with self.subTest(language=code):
                self.assertIn(code, VOICE_PERSONAS)
                for field in self.REQUIRED:
                    self.assertTrue(
                        VOICE_PERSONAS[code].get(field),
                        f"{code} persona missing {field}",
                    )

    def test_pronunciation_rules_cover_money(self):
        """S26: numbers and currency must be explicitly addressed per language."""
        for code in PRODUCTION_VOICE_LANGUAGES:
            pron = VOICE_PERSONAS[code].get("pronunciation", {})
            with self.subTest(language=code):
                self.assertTrue(
                    pron.get("naira"),
                    f"{code} has no rule for pronouncing the currency",
                )
                self.assertTrue(
                    pron.get("digit_grouping"),
                    f"{code} has no rule for reading digit groups",
                )

    def test_speaking_rate_is_plausible(self):
        for code, persona in VOICE_PERSONAS.items():
            with self.subTest(language=code):
                try:
                    rate = float(persona["rate"])
                except (KeyError, TypeError, ValueError):
                    self.fail(f"{code} has a non-numeric rate: {persona.get('rate')!r}")
                self.assertGreaterEqual(rate, MIN_RATE, f"{code} speaks too slowly to sound natural")
                self.assertLessEqual(rate, MAX_RATE, f"{code} speaks too fast to be understood")

    def test_voice_id_matches_language(self):
        """A voice id for the wrong language is the classic silent failure."""
        for code, persona in VOICE_PERSONAS.items():
            with self.subTest(language=code):
                self.assertTrue(
                    persona["voice_id"].startswith(code),
                    f"{code} is mapped to voice {persona['voice_id']!r}",
                )

    def test_tonally_languages_declare_tone_handling(self):
        """
        Yoruba is tonal: a voice that flattens pitch changes the meaning of a
        request. The persona must say so, or the risk is unrecorded.
        """
        yo = VOICE_PERSONAS.get("yo", {})
        self.assertTrue(
            any("ton" in str(v).lower() for v in (yo.get("pronunciation", {}), yo.get("notes", ""))),
            "Yoruba persona does not address tonal pronunciation",
        )


class VoiceRegistryConsistencyTests(unittest.TestCase):
    """Registry flags and personas must not disagree."""

    def test_unregistered_languages_are_not_dialable(self):
        for code in ("ff", "kr", "tiv"):
            with self.subTest(language=code):
                self.assertFalse(
                    has_native_voice(code),
                    f"{code} has no validated voice and must not be callable",
                )
                out = resolve_voice(code)
                self.assertFalse(out["usable"])
                self.assertTrue(out["is_fallback"])
                self.assertEqual(out["requested_language"], code)

    def test_registered_set_matches_persona_table(self):
        self.assertEqual(REGISTERED_VOICE_LANGUAGES, frozenset(VOICE_PERSONAS))


class VoiceEscalationTests(unittest.TestCase):
    """S23 — the agent must escalate rather than speak the wrong language."""

    def test_missing_voice_defaults_to_escalation(self):
        out = resolve_voice("kr")
        self.assertFalse(out["usable"], "a language with no voice must not be usable")
        self.assertIn("no_validated_native_voice", out["reason"])

    def test_english_fallback_requires_explicit_opt_in(self):
        permissive = resolve_voice("kr", allow_english_fallback=True)
        self.assertTrue(permissive["usable"])
        self.assertTrue(permissive["is_fallback"])
        self.assertEqual(permissive["language"], "en")
        # The requested language is preserved so staff can see what we wanted.
        self.assertEqual(permissive["requested_language"], "kr")

    def test_known_language_never_falls_back(self):
        for code in PRODUCTION_VOICE_LANGUAGES:
            with self.subTest(language=code):
                out = resolve_voice(code)
                self.assertTrue(out["usable"])
                self.assertFalse(out["is_fallback"])
                self.assertEqual(out["language"], code)


class AudioGateNotImplementedTests(unittest.TestCase):
    """
    Makes the gap explicit rather than silently green.

    S26 requires audio-level checks. Until fixtures exist, a language must not
    be able to claim it passed them. This test documents the missing gate so a
    future change has to confront it.
    """

    #: Checks from S26 that require real audio and a speech provider.
    AUDIO_GATES = (
        "speech_recognition_accuracy",
        "background_noise_robustness",
        "nigerian_accent_handling",
        "spoken_number_accuracy",
        "spoken_name_accuracy",
        "code_switch_speech_handling",
    )

    def test_audio_gates_are_declared_as_pending(self):
        # If someone wires real audio fixtures in, this should be replaced by
        # actual measurements. Until then we assert the gap is known.
        self.assertEqual(len(self.AUDIO_GATES), 6)
        for gate in self.AUDIO_GATES:
            self.assertTrue(gate)

    def test_voice_production_claim_requires_audio_review(self):
        """
        A language may hold a persona, but the persona alone is not evidence
        that it passed the audio gates. Callers must treat audio validation as
        outstanding until fixtures exist.
        """
        for code in PRODUCTION_VOICE_LANGUAGES:
            with self.subTest(language=code):
                persona = VOICE_PERSONAS[code]
                self.assertNotIn(
                    "audio_validated", persona,
                    f"{code} claims audio validation but no audio fixtures exist",
                )

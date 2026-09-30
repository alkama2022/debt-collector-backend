"""
Language quality gate (§26).

A language must not be labelled "production ready" until it passes these
checks. The tests are split into two groups:

  * Pure-content gates — run without a database. These catch the failure modes
    that actually bite in practice: a missing financial term, a template that
    dropped a `{{payment_link}}` placeholder, diacritics lost to an encoding
    round-trip, or a language silently falling back to English text.

  * Registry gates — require the database and assert that only languages which
    pass the content gates are marked `active`/`production`.

Run just these with:

    .venv/Scripts/python.exe manage.py test apps.languages
"""
import re
import unittest
from decimal import Decimal

from apps.languages.code_switch import LOANWORDS, STRONG_MARKERS, detect_code_switch, split_segments
from apps.languages.cultural_profiles import CULTURAL_PROFILES, get_profile
from apps.languages.router import LANGUAGE_KEYWORDS, MultilingualLanguageRouter
from apps.languages.staff_translation import (
    STAFF_TRANSLATION_MIN_CONFIDENCE,
    build_staff_translation,
    needs_translation,
)
from apps.languages.templates import NATURAL_VARIANTS, TERMINOLOGY, render_template
from apps.languages.voice_personas import VOICE_PERSONAS, has_native_voice, resolve_voice

# Languages in the first production release (§1).
PRODUCTION_LANGUAGES = ("en", "ha", "yo", "ig", "pcm")

# Every financial concept the AI must be able to express (§13).
REQUIRED_TERMS = (
    "amount_owed", "outstanding_balance", "invoice", "due_date", "payment",
    "pay_money", "pay_now", "reminder", "thank_you", "overdue", "balance",
    "total", "currency", "greeting", "dear_customer", "kindly_pay",
    "we_appreciate",
)

# Message categories the collection engine must be able to send (§21).
REQUIRED_TEMPLATES = ("reminder", "overdue")

# Variables that must survive rendering (§16). The requirement is per message
# *category*, not uniform: asking for money needs a way to pay, confirming a
# payment must not tell someone to pay again.
MONEY_REQUEST_TEMPLATES = ("reminder", "overdue", "negotiation", "promise")
CONFIRMATION_TEMPLATES = ("receipt",)

MONEY_REQUEST_VARS = ("{{customer_name}}", "{{amount_owed}}", "{{pay_link}}")
RECEIPT_VARS = ("{{customer_name}}", "{{amount_owed}}", "{{outstanding_balance}}")

# Characters that must survive in Yoruba/Igbo/Hausa. A '?' between two ASCII
# letters is the signature of a diacritic destroyed by a bad encoding
# round-trip (this repo has been bitten by it before).
_LOSSY_MARKER = re.compile(r"[A-Za-z]\?[A-Za-z]")


class TerminologyCompletenessTests(unittest.TestCase):
    """§13 — controlled terminology dictionary per language."""

    def test_every_production_language_has_full_terminology(self):
        for code in PRODUCTION_LANGUAGES:
            with self.subTest(language=code):
                self.assertIn(code, TERMINOLOGY, f"{code} missing from TERMINOLOGY")
                missing = [t for t in REQUIRED_TERMS if not TERMINOLOGY[code].get(t)]
                self.assertEqual(
                    missing, [], f"{code} is missing financial terms: {missing}"
                )

    def test_no_terminology_value_is_empty_or_placeholder(self):
        for code, terms in TERMINOLOGY.items():
            for key, value in terms.items():
                with self.subTest(language=code, term=key):
                    self.assertTrue(value and value.strip())
                    self.assertNotIn("{{", value, "terminology must not contain placeholders")
                    self.assertNotIn("???", value, "terminology looks corrupted")

    def test_diacritics_not_lost_to_encoding_roundtrip(self):
        """
        Guards a real regression: an editing pass that rewrote these files with
        the wrong codepage replaced every Yoruba/Igbo/Hausa diacritic with '?'.
        """
        for code, terms in TERMINOLOGY.items():
            for key, value in terms.items():
                with self.subTest(language=code, term=key):
                    self.assertIsNone(
                        _LOSSY_MARKER.search(value),
                        f"{code}.{key} contains a lost diacritic: {value!r}",
                    )


class NonLatinScriptIntegrityTests(unittest.TestCase):
    """§12/§25 — a 'native' language that is plain ASCII is not actually native."""

    #: characters that must be present for a script to count as real
    SCRIPT_SAMPLES = {
        "ha": ("ƙ", "ɗ", "ɓ"),   # Hausa implosives
        "yo": ("ọ", "ṣ", "ẹ"),   # Yoruba underdots
        "ig": ("ị", "ụ", "ọ"),   # Igbo underdots
    }

    def test_non_latin_languages_retain_their_script(self):
        for code, required in self.SCRIPT_SAMPLES.items():
            blob = " ".join(TERMINOLOGY[code].values()) + " " + " ".join(
                v
                for variants in NATURAL_VARIANTS.get(code, {}).values()
                for v in ([variants] if isinstance(variants, str) else variants)
            )
            with self.subTest(language=code):
                for char in required:
                    self.assertIn(
                        char, blob,
                        f"{code} lost the character {char!r} — templates may be transliterated",
                    )


class TemplateIntegrityTests(unittest.TestCase):
    """§16 — templates, placeholders and rendering."""

    def test_every_production_language_has_required_templates(self):
        for code in PRODUCTION_LANGUAGES:
            for name in REQUIRED_TEMPLATES:
                with self.subTest(language=code, template=name):
                    self.assertIn(
                        name, NATURAL_VARIANTS.get(code, {}),
                        f"{code} has no {name} template",
                    )

    def test_money_request_templates_keep_critical_variables(self):
        """A customer told to pay must be given a way to pay."""
        for code, cats in NATURAL_VARIANTS.items():
            for name in MONEY_REQUEST_TEMPLATES:
                for i, tmpl in enumerate(cats.get(name, [])):
                    for var in MONEY_REQUEST_VARS:
                        with self.subTest(language=code, template=name, variant=i):
                            self.assertIn(
                                var, tmpl,
                                f"{code}/{name}[{i}] lost {var} — customer could not pay",
                            )

    def test_receipt_confirms_payment_without_asking_again(self):
        """
        A receipt must restate what was received and what remains. It must not
        push a payment link: the customer has already paid, and re-asking is
        both confusing and corrosive to trust.
        """
        for code, cats in NATURAL_VARIANTS.items():
            for i, tmpl in enumerate(cats.get("receipt", [])):
                with self.subTest(language=code, variant=i):
                    for var in RECEIPT_VARS:
                        self.assertIn(var, tmpl, f"{code}/receipt[{i}] lost {var}")
                    self.assertNotIn(
                        "{{pay_link}}", tmpl,
                        f"{code}/receipt[{i}] asks a customer who already paid to pay again",
                    )

    def test_templates_contain_no_dangling_placeholders(self):
        """An unknown {{var}} renders literally, which looks broken to a customer."""
        known = set(TERMINOLOGY["en"]) | {
            "customer_name", "business_name", "invoice_number", "pay_link",
            "payment_link", "amount_owed", "amount_due", "outstanding_balance",
            "due_date", "due_date_value", "currency", "greeting", "thank_you",
            "invoice", "total", "balance", "overdue", "reminder", "payment",
        }
        pattern = re.compile(r"\{\{\s*(\w+)\s*\}\}")
        for code, cats in NATURAL_VARIANTS.items():
            for name, variants in cats.items():
                for tmpl in variants:
                    for var in pattern.findall(tmpl):
                        with self.subTest(language=code, template=name, var=var):
                            self.assertIn(
                                var, known,
                                f"{code}/{name} references unknown variable {{{{{var}}}}}",
                            )

    def test_render_preserves_amount_exactly(self):
        """
        §14 — a financial value must survive rendering byte-for-byte. The AI
        styles the sentence; it must never restate or recompute the figure.
        """
        for code in PRODUCTION_LANGUAGES:
            with self.subTest(language=code):
                out = render_template(
                    "reminder", code,
                    {"amount_owed": "85,000", "customer_name": "Test", "invoice_number": "INV-1"},
                )
                self.assertIn("85,000", out)
                for wrong in ("8,500", "850,000", "85.00", "85000"):
                    self.assertNotIn(
                        wrong, out.replace("85,000", ""),
                        f"{code} rendering altered the amount to {wrong}",
                    )

    def test_render_does_not_leak_braces(self):
        for code in PRODUCTION_LANGUAGES:
            out = render_template("reminder", code, {"customer_name": "Amina"})
            with self.subTest(language=code):
                self.assertNotIn("{{", out)
                self.assertNotIn("}}", out)


class CodeSwitchTests(unittest.TestCase):
    """§27 — mixed-language messages must be understood, not rejected."""

    def test_spec_example_is_recognised_as_code_switch(self):
        r = detect_code_switch(
            "I understand the balance, but wallahi I need small time.",
            LANGUAGE_KEYWORDS,
        )
        self.assertTrue(r.is_code_switched)
        self.assertEqual(r.primary, "en")
        self.assertEqual(r.secondary, "pcm")

    def test_pure_language_is_not_a_code_switch(self):
        for text, code in (
            ("Ina kwana? Zan biya gobe.", "ha"),
            ("I go pay am tomorrow.", "pcm"),
            ("Please pay your balance today.", "en"),
        ):
            with self.subTest(text=text):
                r = detect_code_switch(text, LANGUAGE_KEYWORDS)
                self.assertFalse(r.is_code_switched, f"{text} should not be a switch")
                self.assertEqual(r.primary, code)

    def test_loanwords_do_not_create_false_switches(self):
        """Shared Nigerian English vocabulary must not flip the language."""
        for text in (
            "I need small time to pay this money.",
            "Please send the payment link for my invoice.",
        ):
            with self.subTest(text=text):
                r = detect_code_switch(text, LANGUAGE_KEYWORDS)
                self.assertFalse(r.is_code_switched, f"{text} wrongly flagged as switch")
                self.assertEqual(r.primary, "en")

    def test_marker_words_are_not_treated_as_noise(self):
        """wallahi/abeg are the signal, not noise — regression guard."""
        for marker in ("wallahi", "abeg", "oya", "japa"):
            with self.subTest(marker=marker):
                self.assertIn(marker, STRONG_MARKERS)
                self.assertNotIn(
                    marker, LOANWORDS,
                    f"{marker} is a register marker and must not be suppressed",
                )

    def test_empty_and_neutral_input_is_safe(self):
        for text in ("", "   ", "Ok", "..."):
            with self.subTest(text=text):
                r = detect_code_switch(text, LANGUAGE_KEYWORDS, default_language="ha")
                self.assertTrue(r.primary)
                self.assertFalse(r.is_code_switched)

    def test_segments_cover_all_input(self):
        text = "Sannu! Zan biya gobe. Abeg send the link."
        segs = split_segments(text)
        self.assertGreaterEqual(len(segs), 3)
        r = detect_code_switch(text, LANGUAGE_KEYWORDS)
        self.assertEqual(len(r.segments), len(segs))


class RouterResolutionTests(unittest.TestCase):
    """§5/§8/§20 — priority and continuity."""

    def setUp(self):
        self.router = MultilingualLanguageRouter()

    def test_customer_preference_beats_detection(self):
        class C:
            preferred_language_id = "ha"
        self.assertEqual(self.router.get_customer_language(C()), "ha")

    def test_conversation_memory_used_when_detection_is_weak(self):
        out = self.router.resolve_code_switched_language(
            "Ok", customer=None, conversation_language="ha"
        )
        self.assertEqual(out["language"], "ha")
        self.assertEqual(out["reason"], "conversation_continuity")

    def test_customer_preference_wins_when_present_in_message(self):
        class C:
            preferred_language_id = "ha"
        out = self.router.resolve_code_switched_language(
            "Zan biya gobe. Abeg send the link.", customer=C(),
            conversation_language="ha",
        )
        self.assertEqual(out["language"], "ha")

    def test_mixed_output_validation_passes(self):
        ok, reason = self.router.validate_language_output(
            "No wahala, I go send the payment for the invoice now.", "en"
        )
        self.assertTrue(ok, reason)

    def test_wrong_language_output_is_rejected(self):
        ok, reason = self.router.validate_language_output(
            "Kedu ka ị mere? Ihe ncheta sitere na ABC School.", "ha"
        )
        self.assertFalse(ok)
        self.assertIn("expected ha", reason)


class VoicePersonaTests(unittest.TestCase):
    """§22 — one voice cannot be native across languages."""

    def test_every_production_language_has_a_voice_persona(self):
        for code in PRODUCTION_LANGUAGES:
            with self.subTest(language=code):
                self.assertTrue(has_native_voice(code))
                self.assertIn(code, VOICE_PERSONAS)

    def test_persona_declares_required_fields(self):
        required = ("voice_id", "gender", "rate", "tone", "formality", "pronunciation")
        for code, persona in VOICE_PERSONAS.items():
            for field in required:
                with self.subTest(language=code, field=field):
                    self.assertIn(field, persona)
                    self.assertTrue(persona[field])

    def test_unvalidated_language_is_reported_unusable(self):
        """A language with no validated voice must not silently use English."""
        out = resolve_voice("kr")
        self.assertFalse(out["usable"])
        self.assertTrue(out["is_fallback"])
        self.assertIn("no_validated_native_voice_for_kr", out["reason"])

    def test_known_language_is_usable(self):
        out = resolve_voice("yo")
        self.assertTrue(out["usable"])
        self.assertFalse(out["is_fallback"])


class StaffTranslationTests(unittest.TestCase):
    """§33 — staff translation never overwrites the original."""

    def test_translation_needed_only_across_languages(self):
        self.assertTrue(needs_translation("Bawo ni o?", "yo", "ha"))
        self.assertFalse(needs_translation("Bawo ni o?", "yo", "yo"))
        self.assertFalse(needs_translation("", "yo", "ha"))

    def test_original_is_preserved_verbatim(self):
        original = "Mo ti san pe mo ni gbese."
        result = build_staff_translation(
            original, "yo", "ha",
            translate_fn=lambda t, s, d: ("Na san cikin akwai bujuru na.", Decimal("0.92"), "test"),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.original_text, original)
        self.assertNotEqual(result.original_text, result.translated_text)
        self.assertEqual(result.original_language, "yo")
        self.assertEqual(result.translated_language, "ha")
        self.assertTrue(result.is_reliable)

    def test_low_confidence_translation_is_flagged(self):
        result = build_staff_translation(
            "Bawo ni o?", "yo", "ha",
            translate_fn=lambda t, s, d: ("guess", Decimal("0.40"), "test"),
        )
        self.assertFalse(result.is_reliable)

    def test_no_translator_returns_none_rather_than_fabricating(self):
        self.assertIsNone(build_staff_translation("Bawo ni o?", "yo", "ha"))


class CulturalProfileTests(unittest.TestCase):
    """§12 — communication profiles."""

    def test_every_production_language_has_a_profile(self):
        for code in PRODUCTION_LANGUAGES:
            with self.subTest(language=code):
                profile = get_profile(code)
                self.assertEqual(profile["code"], code)
                self.assertIn("greetings", profile)
                self.assertIn("tone", profile)
                self.assertIn("number_format", profile)

    def test_greetings_include_time_of_day(self):
        for code in ("ha", "yo", "ig"):
            greetings = get_profile(code)["greetings"]
            with self.subTest(language=code):
                for slot in ("morning", "afternoon", "evening"):
                    self.assertTrue(
                        greetings.get(slot),
                        f"{code} missing a {slot} greeting",
                    )

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(get_profile("zz")["code"], "en")


class ScalabilityTests(unittest.TestCase):
    """§1 — adding a language must not require code changes."""

    def test_inactive_languages_have_profiles_but_are_not_active(self):
        for code in ("ff", "kr", "tiv"):
            with self.subTest(language=code):
                self.assertIn(code, CULTURAL_PROFILES)
                self.assertFalse(has_native_voice(code), f"{code} has no validated voice yet")

    def test_every_registry_language_has_a_profile(self):
        for code in CULTURAL_PROFILES:
            self.assertIn(code, CULTURAL_PROFILES[code]["code"])


# ── Registry gates (require the database) ────────────────────────────────────

try:  # pragma: no cover - import guard so content tests run without Django set up
    from django.test import TestCase as DjangoTestCase
    from apps.languages.models import Language

    class LanguageRegistryGateTests(DjangoTestCase):
        """§25/§26 — only reviewed languages may be active and production."""

        @classmethod
        def setUpTestData(cls):
            for code, name, native in (
                ("en", "English", "English"),
                ("ha", "Hausa", "Hausa"),
                ("yo", "Yoruba", "Yorùbá"),
                ("ig", "Igbo", "Igbo"),
                ("pcm", "Nigerian Pidgin", "Naija Pidgin"),
            ):
                Language.objects.get_or_create(
                    code=code,
                    defaults={"name": name, "native_name": native, "locale": f"{code}-NG",
                              "active": True, "quality_status": Language.QualityStatus.PRODUCTION,
                              "text_to_speech_supported": True,
                              "speech_to_text_supported": True},
                )

        def test_active_languages_have_complete_terminology(self):
            for lang in Language.objects.filter(active=True):
                with self.subTest(language=lang.code):
                    self.assertIn(lang.code, TERMINOLOGY)
                    missing = [t for t in REQUIRED_TERMS if not TERMINOLOGY[lang.code].get(t)]
                    self.assertEqual(missing, [], f"{lang.code} active but missing {missing}")

        def test_production_status_requires_templates(self):
            for lang in Language.objects.filter(
                active=True, quality_status=Language.QualityStatus.PRODUCTION
            ):
                with self.subTest(language=lang.code):
                    for name in REQUIRED_TEMPLATES:
                        self.assertIn(name, NATURAL_VARIANTS.get(lang.code, {}))

        def test_production_status_requires_validated_voice(self):
            for lang in Language.objects.filter(
                active=True, quality_status=Language.QualityStatus.PRODUCTION
            ):
                with self.subTest(language=lang.code):
                    self.assertTrue(
                        lang.text_to_speech_supported,
                        f"{lang.code} marked production without a validated TTS voice",
                    )
                    self.assertTrue(has_native_voice(lang.code))

except Exception:  # pragma: no cover
    pass

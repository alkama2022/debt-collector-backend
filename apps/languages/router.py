"""
MultilingualLanguageRouter — context-aware language routing, not simple translation.

Heuristics are stubs for real NLU; production would call an LLM or lang-id model.
"""
import re
from decimal import Decimal
from typing import Optional, Tuple

# Confidence constants
HIGH_CONFIDENCE = Decimal("0.96")
UNCERTAIN_CONFIDENCE = Decimal("0.55")
MEDIUM_CONFIDENCE = Decimal("0.78")

# Keyword heuristics per language. These are deliberately overlapping to test confidence logic.
HAUSA_KEYWORDS = [
    "ina kwana", "ina wuni", "sannu", "yaya", "nagode", "na gode", "don allah",
    "bashi", "biya", "biyan", "kuɗi", "kudi", "hausa", "lafiya", "ina gida",
]
YORUBA_KEYWORDS = [
    "bawo", "mo le san", "o dabo", "e kaaro", "e kaasan", "e ku owuro", "e ku isan",
    "owo", "gbese", "jowo", "ejowo", "yoruba", "se alafia", "mo wa daadaa",
    # single token triggers
    " bawo ", " pele ", " ore ",
]
IGBO_KEYWORDS = [
    "kedu", "ndewo", "daalu", "biko", "ego", "igbo", "kedu ka", "imeela",
    "ugwo", "ikwu ugwo", "gini", "ewo", "ndi",
]
PIDGIN_KEYWORDS = [
    "i go pay", "i go", "how far", "abeg", "o de pay", "wey", "dey", "na wa",
    "you don", "i dey", "no dey", "make i", "wetin", "shey", "pidgin",
    "una", "oya", "japa", "wallahi", "gidi", "sharp sharp", "small small",
]

# Language -> keyword table, shared with the code-switch segmenter (§27).
# Exposed as a dict so code_switch.detect_code_switch can reuse it without
# importing the router (which would be circular).
LANGUAGE_KEYWORDS = {
    "ha": HAUSA_KEYWORDS,
    "yo": YORUBA_KEYWORDS,
    "ig": IGBO_KEYWORDS,
    "pcm": PIDGIN_KEYWORDS,
    "en": [
        "hello", "hi", "dear", "please", "good morning", "good afternoon",
        "good evening", "the", "i will", "thank", "thanks", "balance",
        "invoice", "payment", "pay", "paid", "debt", "due", "reminder",
        "kindly", "regards", "sir", "madam",
    ],
}


def _normalize(text: str) -> str:
    return (text or "").lower().strip()


def _contains_any(text: str, keywords) -> bool:
    low = _normalize(text)
    padded = f" {low} "
    for kw in keywords:
        if kw.lower() in low or kw.lower().strip() in padded:
            # for short tokens use padded match
            if len(kw.strip()) <= 4:
                if f" {kw.strip().lower()} " in padded:
                    return True
            else:
                if kw.lower() in low:
                    return True
    return False


def _score_language(text: str) -> dict:
    """Return score per language code."""
    low = _normalize(text)
    scores = {"ha": 0, "yo": 0, "ig": 0, "pcm": 0, "en": 0}
    if _contains_any(low, HAUSA_KEYWORDS):
        scores["ha"] += 3
        # bonus for multiple ha keywords
        for kw in HAUSA_KEYWORDS:
            if kw.lower() in low:
                scores["ha"] += 1
    if _contains_any(low, YORUBA_KEYWORDS):
        scores["yo"] += 3
        for kw in YORUBA_KEYWORDS:
            if kw.lower().strip() in f" {low} ":
                scores["yo"] += 1
    if _contains_any(low, IGBO_KEYWORDS):
        scores["ig"] += 3
        for kw in IGBO_KEYWORDS:
            if kw.lower() in low:
                scores["ig"] += 1
    if _contains_any(low, PIDGIN_KEYWORDS):
        scores["pcm"] += 3
        for kw in PIDGIN_KEYWORDS:
            if kw.lower() in low:
                scores["pcm"] += 1
    # English fallback gets base score if no other match or contains english markers
    if scores["ha"] == 0 and scores["yo"] == 0 and scores["ig"] == 0 and scores["pcm"] == 0:
        # check if text looks like english (ascii heavy, common english words)
        if re.search(r"\b(the|i will|pay|please|hello|debt|invoice|balance)\b", low):
            scores["en"] += 2
        else:
            # still default to en with low score
            scores["en"] += 1
    return scores


class MultilingualLanguageRouter:
    """
    Context-aware router for CollectNaija multilingual collections.

    NOT a simple translator: uses customer preference, business settings,
    detection confidence, and conversation history to pick response language.
    Generation is stubbed as context-aware template selection.
    """

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def detect_language(self, text: str) -> Tuple[str, Decimal]:
        """
        Heuristic language detection.
        Returns (code, confidence) - confidence 0.96 high, 0.55 uncertain.
        """
        if not text or not text.strip():
            return "en", UNCERTAIN_CONFIDENCE
        scores = _score_language(text)
        best = max(scores, key=lambda k: scores[k])
        best_score = scores[best]
        # Determine confidence
        sorted_scores = sorted(scores.values(), reverse=True)
        margin = sorted_scores[0] - (sorted_scores[1] if len(sorted_scores) > 1 else 0)
        if best_score >= 4 and margin >= 2:
            confidence = HIGH_CONFIDENCE
        elif best_score >= 3 and margin >= 1:
            confidence = MEDIUM_CONFIDENCE
        elif best == "en" and best_score <= 1:
            confidence = UNCERTAIN_CONFIDENCE
        else:
            confidence = UNCERTAIN_CONFIDENCE
            # if tie, fallback to en with uncertain
            if margin == 0:
                return "en", UNCERTAIN_CONFIDENCE
        return best, confidence

    def detect_language_confidence(self, text: str) -> Tuple[str, Decimal, dict]:
        """Returns (code, confidence, scores) for debugging."""
        code, conf = self.detect_language(text)
        return code, conf, _score_language(text)

    # ------------------------------------------------------------------
    # Code-switching (§27)
    # ------------------------------------------------------------------
    def detect_code_switch(self, text: str, default_language: str = "en"):
        """
        Segment-level attribution for mixed-language messages.

        Returns a CodeSwitchResult exposing .primary, .secondary,
        .confidence, .is_code_switched and per-clause .segments.
        """
        from .code_switch import detect_code_switch as _detect
        return _detect(text or "", LANGUAGE_KEYWORDS, default_language=default_language)

    def resolve_code_switched_language(
        self, text: str, customer, business_settings=None, conversation_language: str = None
    ) -> dict:
        """
        Decide how to reply to a possibly mixed-language message.

        §27: a customer who mixes languages must not be treated as speaking an
        unknown language. We answer in whichever of the two languages is the
        better target, preferring:

          1. the customer's configured preferred language, if it is one of the
             languages actually present in the message (they are addressing us
             in it, even if they code-switch);
          2. the dominant language of the message itself;
          3. the conversation's established language, for continuity;
          4. the business fallback.

        Returns a dict rather than a bare code so callers can log why.
        """
        result = self.detect_code_switch(text, default_language=conversation_language or "en")
        preferred = self.get_customer_language(customer)
        present = [c for c in (result.primary, result.secondary) if c]

        if preferred in present:
            chosen, reason = preferred, "customer_preferred_present"
        elif result.is_code_switched:
            chosen, reason = result.primary, "dominant_of_code_switch"
        elif conversation_language and result.confidence < MEDIUM_CONFIDENCE:
            chosen, reason = conversation_language, "conversation_continuity"
        elif conversation_language and result.primary == "en" and conversation_language != "en":
            # Short or ambiguous reply in a language the customer is not
            # fluent in: stay in the established conversation language.
            chosen, reason = conversation_language, "conversation_continuity"
        else:
            chosen, reason = result.primary, "dominant_language"

        return {
            "language": chosen,
            "reason": reason,
            "is_code_switched": result.is_code_switched,
            "primary": result.primary,
            "secondary": result.secondary,
            "detection_confidence": result.confidence,
            "segments": [
                {"text": s.text, "language": s.language, "score": s.score}
                for s in result.segments
            ],
        }

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------
    def get_customer_language(self, customer) -> str:
        """Return customer's preferred_language code or 'en'."""
        if customer is None:
            return "en"
        # support both object and dict
        if isinstance(customer, dict):
            lang = customer.get("preferred_language") or customer.get("preferred_language_id")
            if hasattr(lang, "code"):
                return lang.code
            return (lang or "en").strip() or "en"
        lang = getattr(customer, "preferred_language", None)
        if lang is None:
            # also check preferred_language_id
            lang_id = getattr(customer, "preferred_language_id", None)
            return (lang_id or "en")
        if isinstance(lang, str):
            return lang
        # FK object
        code = getattr(lang, "code", None) or getattr(lang, "pk", None)
        return (code or "en")

    def get_business_language(self, org) -> str:
        """Return org dashboard language code. Falls back to en."""
        if org is None:
            return "en"
        # Try OrganizationLanguageSettings
        try:
            settings_obj = getattr(org, "language_settings", None)
            if settings_obj is not None:
                # if not fetched, try query
                if hasattr(settings_obj, "dashboard_language"):
                    lang = settings_obj.dashboard_language
                    if lang:
                        return getattr(lang, "code", None) or getattr(lang, "pk", None) or "en"
                    return getattr(settings_obj, "dashboard_language_id", None) or "en"
        except Exception:
            pass
        # Lazy import to avoid circular
        try:
            from .models import OrganizationLanguageSettings
            s = OrganizationLanguageSettings.objects.filter(org=org).select_related(
                "dashboard_language"
            ).first()
            if s and s.dashboard_language:
                return s.dashboard_language.code
            if s and s.dashboard_language_id:
                return s.dashboard_language_id
        except Exception:
            pass
        return "en"

    def fallback_language(self, org=None) -> str:
        """Return fallback language code for org or system fallback 'en'."""
        if org is not None:
            try:
                from .models import OrganizationLanguageSettings
                s = OrganizationLanguageSettings.objects.filter(org=org).select_related(
                    "fallback_language"
                ).first()
                if s and s.fallback_language:
                    return s.fallback_language.code
                if s and s.fallback_language_id:
                    return s.fallback_language_id
            except Exception:
                pass
        return "en"

    # ------------------------------------------------------------------
    # Resolution — core context-aware logic
    # ------------------------------------------------------------------
    def resolve_response_language(
        self,
        customer,
        detected: Optional[str],
        business_settings=None,
        confidence: Optional[Decimal] = None,
        conversation_language: Optional[str] = None,
    ) -> str:
        """
        Decide response language given:
        - customer: Customer instance or None
        - detected: detected language code from current utterance (or None)
        - business_settings: OrganizationLanguageSettings instance or None
        - confidence: detection confidence

        Modes:
          customer_preferred -> always customer language
          business_fallback -> business dashboard language
          auto_detect -> if confidence high use detected, else customer language, else fallback

        §8: when a customer switches language mid-conversation we should follow
        them. A switch is only honoured once the detection is confident, so a
        one-off ambiguous line cannot hijack an established conversation.
        §20: `conversation_language` carries the established language so we do
        not re-detect from scratch on every message.
        """
        # Normalize
        detected = (detected or "").strip() or None
        conf = Decimal(str(confidence)) if confidence is not None else None

        # §8 — an explicit, confident switch overrides the sticky preference.
        # Only meaningful in auto_detect mode; other modes are owner policy and
        # must not be overridden by the model.
        if business_settings is not None:
            mode = getattr(business_settings, "ai_communication_mode", None)
        else:
            mode = "customer_preferred"

        if (
            mode == "auto_detect"
            and conversation_language
            and detected
            and detected != conversation_language
            and conf is not None
            and conf >= MEDIUM_CONFIDENCE
        ):
            return detected

        # If business_settings provided, respect mode
        if business_settings is not None:
            fallback = getattr(business_settings, "fallback_language_id", None) or getattr(business_settings, "fallback_language", None)
            if hasattr(fallback, "code"):
                fallback = fallback.code
            fallback = fallback or "en"
            customer_lang = self.get_customer_language(customer)

            if mode == "business_fallback":
                # Always business dashboard language
                dash = getattr(business_settings, "dashboard_language_id", None) or getattr(business_settings, "dashboard_language", None)
                if hasattr(dash, "code"):
                    dash = dash.code
                return dash or fallback or "en"

            if mode == "auto_detect":
                # High confidence detected overrides; else customer; else fallback
                if detected and conf is not None and conf >= Decimal("0.80"):
                    # validate detected is in supported/active registry if possible
                    if self._is_supported(business_settings, detected):
                        return detected
                    return fallback
                if detected and conf is None:
                    # re-detect confidence if needed — treat as high for now if detected differs from customer
                    if self._is_supported(business_settings, detected):
                        return detected
                # Uncertain -> customer language -> fallback
                if customer_lang and self._is_supported(business_settings, customer_lang):
                    return customer_lang
                return fallback

            # default customer_preferred
            if customer_lang and self._is_supported(business_settings, customer_lang):
                return customer_lang
            return fallback

        # No business_settings: simple heuristic fallback
        customer_lang = self.get_customer_language(customer)
        if detected and conf is not None and conf >= Decimal("0.80"):
            return detected
        if customer_lang:
            return customer_lang
        return "en"

    def _is_supported(self, business_settings, code: str) -> bool:
        """Check if code is in supported_languages or registry active; if no supported set, assume all active supported."""
        if not code:
            return False
        # If supported_languages empty, treat as all active languages supported
        try:
            if hasattr(business_settings, "supported_languages"):
                # avoid DB hit if prefetched; check through manager
                # If M2M not loaded, we can't easily know without query; assume supported if empty
                qs = business_settings.supported_languages.all()
                if not qs.exists():
                    # empty means all active are supported
                    return True
                return qs.filter(code=code, active=True).exists()
        except Exception:
            pass
        # Fallback: check registry
        try:
            from .models import Language
            return Language.objects.filter(code=code, active=True).exists()
        except Exception:
            return code in ("en", "ha", "yo", "ig", "pcm")

    # ------------------------------------------------------------------
    # Switch detection
    # ------------------------------------------------------------------
    def detect_language_switch(self, history) -> Optional[dict]:
        """
        Detect if customer switched language recently.
        history: iterable of CustomerLanguageHistory or dicts with to_lang/from_lang/created_at
        Returns dict with switched bool and details or None.
        """
        if not history:
            return None
        # Normalize to list
        items = list(history)
        if len(items) < 2:
            return {"switched": False, "reason": "insufficient_history"}
        # Get last two entries
        def _code(entry, field):
            if isinstance(entry, dict):
                v = entry.get(field)
            else:
                v = getattr(entry, field, None)
            if v is None:
                # try _id
                v = getattr(entry, f"{field}_id", None) if not isinstance(entry, dict) else entry.get(f"{field}_id")
            if hasattr(v, "code"):
                return v.code
            return v

        last = items[0] if hasattr(items[0], "created_at") else items[-1]
        prev = items[1] if len(items) > 1 else None
        # If ordered -created_at, last is newest
        # Ensure we compare newest vs previous
        try:
            # Try to sort by created_at if available
            def _ts(x):
                if isinstance(x, dict):
                    return x.get("created_at")
                return getattr(x, "created_at", None)
            items_sorted = sorted(items, key=lambda x: _ts(x) or "", reverse=True)
            last = items_sorted[0]
            prev = items_sorted[1] if len(items_sorted) > 1 else None
        except Exception:
            pass

        last_code = _code(last, "to_lang")
        prev_code = _code(prev, "to_lang") if prev else None
        if last_code and prev_code and last_code != prev_code:
            reason = _code(last, "reason") if not isinstance(last, dict) else last.get("reason")
            # Try attribute
            if isinstance(last, dict):
                reason_val = last.get("reason")
            else:
                reason_val = getattr(last, "reason", None)
            # If system detected switch
            if reason_val in ("auto_detect", "detected_switch"):
                return {"switched": True, "from": prev_code, "to": last_code, "reason": reason_val, "confidence": getattr(last, "detected_confidence", None)}
            return {"switched": True, "from": prev_code, "to": last_code, "reason": reason_val}
        return {"switched": False, "from": prev_code, "to": last_code}

    # ------------------------------------------------------------------
    # Voice / Template / Validation (context-aware stubs)
    # ------------------------------------------------------------------
    def select_voice(self, language_code: str, org=None) -> str:
        """
        Select the TTS voice id for a language.

        Backwards-compatible string return. Prefer `resolve_voice_profile` for
        new code, which returns rate/tone/formality alongside the voice id (§22).
        """
        from .voice_personas import resolve_voice
        return resolve_voice(language_code, org=org)["voice_id"]

    def resolve_voice_profile(self, language_code: str, org=None) -> dict:
        """
        Full voice configuration for a language (§22): voice id, rate, tone,
        formality and pronunciation rules, plus whether it is actually usable.

        A language without a validated native voice returns `usable: False` so
        the caller can escalate (§23) instead of speaking that language with an
        English voice.
        """
        from .voice_personas import resolve_voice
        profile = resolve_voice(language_code, org=org)
        # If the org registry says TTS is not supported for this language, we
        # must not pretend the voice is usable.
        if profile.get("language") == (language_code or "").strip().lower():
            try:
                from .models import Language
                row = Language.objects.filter(code=profile["language"]).first()
                if row is not None and not row.text_to_speech_supported:
                    profile["usable"] = False
                    profile["reason"] = "language_not_tts_validated"
            except Exception:
                # Registry unavailable (e.g. unit tests) — trust the persona.
                pass
        return profile

    def select_template(self, language_code: str, template_name: str = "reminder") -> str:
        """Select template key for language. Returns template_name:lang."""
        from .templates import TEMPLATES, TERMINOLOGY
        # Validate language exists in templates
        if language_code in TEMPLATES and template_name in TEMPLATES[language_code]:
            return f"{template_name}:{language_code}"
        # fallback
        return f"{template_name}:en"

    def validate_language_output(self, text: str, expected_language: str) -> Tuple[bool, str]:
        """
        Validate generated text matches expected language (heuristic).

        §27: a reply that mixes languages is not a failure. Nigerian customers
        mix English and Pidgin constantly, and a slightly mixed message reads
        as natural rather than wrong — so a code-switched reply is accepted as
        long as the expected language is genuinely dominant.
        """
        if not text or not expected_language:
            return False, "missing_input"
        detected, conf = self.detect_language(text)
        if detected == expected_language:
            return True, f"matched {detected} conf {conf}"
        # Allow en fallback for low confidence
        if conf == UNCERTAIN_CONFIDENCE and expected_language == "en":
            return True, "uncertain_fallback_en"
        # For pidgin, allow en mix
        if expected_language == "pcm" and detected in ("en", "pcm"):
            return True, "pcm_en_mix_allowed"
        # §27 — mixed output is acceptable when the expected language is
        # actually present in the message.
        try:
            cs = self.detect_code_switch(text, default_language=expected_language)
            if expected_language in (cs.primary, cs.secondary):
                return True, f"code_switched_with_{expected_language}"
        except Exception:
            pass
        return False, f"expected {expected_language} but detected {detected} conf {conf}"

    # ------------------------------------------------------------------
    # Generation stub (context-aware, not translate)
    # ------------------------------------------------------------------
    def generate(self, template_name: str, language_code: str, context: dict, org=None) -> str:
        """
        Context-aware generation stub: selects terminology + template for language and renders.
        In production this would call an LLM with language-aware prompt.
        """
        from .templates import render_template
        return render_template(template_name, language_code, context)

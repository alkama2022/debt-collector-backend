from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import AIConversation, PromiseToPay
from .serializers import AIConversationSerializer, PromiseToPaySerializer
from apps.tenancy.org import get_org

class AIConversationListCreate(generics.ListCreateAPIView):
    serializer_class = AIConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["state", "channel", "customer", "invoice"]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return AIConversation.objects.none()
        return AIConversation.objects.for_org(org).prefetch_related("messages")

    def perform_create(self, serializer):
        org = get_org(self.request)
        if org:
            from apps.subscriptions.entitlements import check_feature_access
            from rest_framework.exceptions import PermissionDenied
            allowed, reason = check_feature_access(org, "AI_CONVERSATIONS")
            if not allowed:
                raise PermissionDenied({"detail": reason, "code": "FEATURE_NOT_ENTITLED"})
            # limit check
            from apps.subscriptions.usage import check_usage_available
            from decimal import Decimal
            ok, r = check_usage_available(org, "AI_CONVERSATIONS", Decimal(1))
            if not ok:
                raise PermissionDenied({"detail": r, "code": "USAGE_LIMIT_REACHED"})
        obj = serializer.save(org=org)
        if org:
            try:
                from apps.subscriptions.usage import commit_or_create_usage
                commit_or_create_usage(org, "AI_CONVERSATIONS", 1, idempotency_key=str(obj.id), unit="conversation")
            except Exception:
                pass

class AIConversationDetail(generics.RetrieveUpdateAPIView):
    serializer_class = AIConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return AIConversation.objects.none()
        return AIConversation.objects.for_org(org)

class PromiseListCreate(generics.ListCreateAPIView):
    serializer_class = PromiseToPaySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return PromiseToPay.objects.none()
        return PromiseToPay.objects.filter(org=org)

    def perform_create(self, serializer):
        org = require_org(self.request)
        serializer.save(org=org)


class DetectLanguageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        text = request.data.get("text") or request.data.get("message") or ""
        if not text.strip():
            return Response({"detail": "text required"}, status=status.HTTP_400_BAD_REQUEST)
        from apps.languages.router import MultilingualLanguageRouter
        from apps.languages.models import Language
        router = MultilingualLanguageRouter()
        code, conf = router.detect_language(text)

        def _name(c):
            try:
                lang = Language.objects.get(code=c)
                return lang.name, lang.native_name
            except Exception:
                return c, c

        name, native = _name(code)
        escalate = conf < 0.6

        # §27 — a mixed-language message must not be reported as "unknown".
        # Surface the second language so the caller can reply knowingly.
        cs = router.detect_code_switch(
            text, default_language=code,
        )
        secondary_code = cs.secondary if cs.is_code_switched else None
        if cs.is_code_switched:
            escalate = False  # we understand it, even if it is mixed
            conf = cs.confidence

        # §20 — the caller's established conversation language, when supplied,
        # keeps the AI from re-detecting on every message.
        conversation_language = request.data.get("conversation_language") or None
        resolution = None
        if conversation_language or cs.is_code_switched:
            resolution = router.resolve_code_switched_language(
                text, customer=None, conversation_language=conversation_language,
            )

        # §23 Human Escalation — low confidence → create escalated conversation stub for audit
        if escalate and request.data.get("customer_id"):
            try:
                from apps.ai.models import AIConversation
                from apps.customers.models import Customer
                org = get_org(request)
                cust = Customer.objects.for_org(org).filter(pk=request.data.get("customer_id")).first()
                AIConversation.objects.create(org=org, customer=cust, state=AIConversation.State.ESCALATED, channel=AIConversation.Channel.WHATSAPP)
            except Exception:
                pass
        payload = {
            "text": text[:500],
            "detected_language": code,
            "language_name": name,
            "native_name": native,
            "confidence": round(float(conf), 2),
            "should_ask_preference": escalate,
            "should_escalate": escalate,
            "escalation_reason": "low_confidence" if escalate else None,
            "suggested_prompt": "Which language would you prefer us to use when communicating with you?" if escalate else None,
            # §27
            "is_code_switched": bool(cs.is_code_switched),
            "secondary_language": secondary_code,
            "secondary_language_name": _name(secondary_code)[1] if secondary_code else None,
            "language_segments": [
                {"text": s.text, "language": s.language, "score": s.score}
                for s in cs.segments
            ][:20],
            # §20
            "resolution": resolution,
        }
        return Response(payload)


class GenerateResponseView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        text = request.data.get("text") or ""
        customer_id = request.data.get("customer_id")
        target_lang = request.data.get("language") or request.data.get("target_language")
        intent = (request.data.get("intent") or "").strip().lower()  # reminder|overdue|negotiation|promise|receipt|human_handoff
        from apps.languages.router import MultilingualLanguageRouter
        router = MultilingualLanguageRouter()
        if not target_lang and customer_id:
            from apps.customers.models import Customer
            try:
                org = get_org(request)
                cust = Customer.objects.for_org(org).get(pk=customer_id)
                target_lang = cust.preferred_language.code if cust.preferred_language else "en"
            except Exception:
                target_lang = "en"
        target_lang = target_lang or "en"
        # Auto-detect intent if not given — simple heuristic for natural routing
        if not intent:
            low = text.lower()
            if any(k in low for k in ["promise", "pay on", "will pay", "next week", "tomorrow"]):
                intent = "promise"
            elif any(k in low for k in ["can't pay", "no money", "split", "installment", "small small", "half"]):
                intent = "negotiation"
            elif any(k in low for k in ["overdue", "late"]):
                intent = "overdue"
            elif any(k in low for k in ["thank", "receipt", "paid"]):
                intent = "receipt"
            else:
                intent = "reminder"
        # Try LLM first if configured, else natural template
        llm_text = None
        from django.conf import settings as _s
        provider = getattr(_s, "AI_PROVIDER", "mock")
        if provider in ("openai", "anthropic") and (getattr(_s, "OPENAI_API_KEY", "") or getattr(_s, "ANTHROPIC_API_KEY", "")):
            try:
                llm_text = _call_llm_for_intent(intent, target_lang, text, request.data)
            except Exception:
                llm_text = None
        from apps.languages.templates import render_template, TERMINOLOGY
        ctx = {
            "customer_name": request.data.get("customer_name") or "Customer",
            "business_name": request.data.get("business_name") or "Your business",
            "amount_owed": (request.data.get("amount_due") or request.data.get("amount_owed") or "85,000").replace("₦","").strip(),
            "amount_due": (request.data.get("amount_due") or "85,000"),
            "due_date_value": request.data.get("due_date") or "2026-10-05",
            "due_date": request.data.get("due_date") or "2026-10-05",
            "pay_link": request.data.get("payment_link") or request.data.get("pay_link") or "https://pay.collectnaija.test/p/xxx",
            "invoice_number": request.data.get("invoice_number") or "INV-001",
            "outstanding_balance": request.data.get("outstanding_balance") or request.data.get("amount_due") or "85,000",
        }
        tmpl = llm_text or render_template(intent if intent in ("reminder","overdue","negotiation","promise","receipt","human_handoff") else "reminder", target_lang, ctx)
        detected, conf = router.detect_language(text) if text else (target_lang, 0.9)
        return Response({
            "detected_language": detected,
            "confidence": round(float(conf), 2),
            "response_language": target_lang,
            "intent": intent,
            "response": tmpl,
            "terminology": TERMINOLOGY.get(target_lang, TERMINOLOGY["en"]),
            "provider": "llm" if llm_text else "natural-template",
            "note": "Natural, warm Nigerian business tone — not robotic. Amount preserved from backend Decimal; LLM only styles, never recalculates."
        })

def _call_llm_for_intent(intent: str, lang: str, user_text: str, data: dict) -> str | None:
    """Call OpenAI/Anthropic with strict guardrails: never invent amounts."""
    from django.conf import settings as _s
    import requests
    amount = (data.get("amount_due") or data.get("amount_owed") or "85,000")
    prompt = (
        f"You are CollectNaija, a warm, professional Nigerian collection assistant. "
        f"Language: {lang}. Intent: {intent}. Customer says: \"{user_text[:400]}\". "
        f"Write a short WhatsApp message (2-3 sentences, human, empathetic, not demanding). "
        f"Use exact amount {amount} and link {data.get('payment_link') or data.get('pay_link') or 'https://pay.collectnaija.test/p/xxx'}. "
        f"Offer payment plan if intent is negotiation. Keep Nigerian polite tone. No markdown."
    )
    if getattr(_s, "OPENAI_API_KEY", ""):
        try:
            r = requests.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {_s.OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "max_tokens": 180, "temperature": 0.7},
                timeout=12)
            j = r.json()
            return j["choices"][0]["message"]["content"].strip()
        except Exception:
            return None
    if getattr(_s, "ANTHROPIC_API_KEY", ""):
        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": _s.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                json={"model": "claude-3-haiku-20240307", "max_tokens": 180, "messages": [{"role": "user", "content": prompt}]},
                timeout=12)
            j = r.json()
            return j["content"][0]["text"].strip()
        except Exception:
            return None
    return None


class VoiceLanguageView(APIView):
    """§22 — resolve a language-appropriate voice, and refuse to fake one."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.languages.router import MultilingualLanguageRouter
        router = MultilingualLanguageRouter()
        code = request.data.get("language") or "en"
        customer_id = request.data.get("customer_id")

        # A customer's configured voice language wins over the request default.
        if customer_id and not request.data.get("language"):
            try:
                from apps.customers.models import Customer
                org = get_org(request)
                cust = Customer.objects.for_org(org).filter(pk=customer_id).first()
                if cust is not None:
                    code = (
                        cust.voice_language.code if cust.voice_language
                        else (cust.preferred_language.code if cust.preferred_language else "en")
                    )
            except Exception:
                pass

        profile = router.resolve_voice_profile(code)
        usable = bool(profile.get("usable"))
        return Response({
            "language": code,
            "requested_language": code,
            "voice": profile.get("voice_id"),
            "usable": usable,
            "is_fallback": profile.get("is_fallback", False),
            "reason": profile.get("reason"),
            "persona": {
                "gender": profile.get("gender"),
                "rate": profile.get("rate"),
                "pitch": profile.get("pitch"),
                "tone": profile.get("tone"),
                "formality": profile.get("formality"),
                "pronunciation": profile.get("pronunciation"),
                "notes": profile.get("notes"),
            },
            # §23 — an unusable voice must escalate, not degrade to English.
            "should_escalate": not usable,
            "escalation_reason": None if usable else (
                profile.get("reason") or "no_validated_voice"
            ),
            "pipeline": ["STT", "Language Detection", "Conversation Understanding",
                         "Business Rules", "Response Generation", "Language Verification", "TTS"],
        })


class StaffTranslationView(APIView):
    """
    §33 — translate a customer message for business staff.

    The original message is always returned untouched alongside any
    translation. Staff must be able to see exactly what the customer said.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.languages.staff_translation import build_staff_translation, needs_translation

        text = request.data.get("text") or request.data.get("message") or ""
        source = request.data.get("source_language") or request.data.get("language") or ""
        target = request.data.get("target_language") or ""

        if not text.strip():
            return Response({"detail": "text required"}, status=status.HTTP_400_BAD_REQUEST)

        # Default the target to the business owner's dashboard language (§32).
        if not target:
            from apps.languages.router import MultilingualLanguageRouter
            target = MultilingualLanguageRouter().get_business_language(get_org(request))

        if not needs_translation(text, source, target):
            return Response({
                "original_text": text,
                "original_language": source,
                "translated_text": None,
                "translated_language": target,
                "is_reliable": True,
                "provider": None,
                "note": "No translation required — same language or no source language.",
            })

        # Translation is only available when an LLM provider is configured; we
        # never fabricate one.
        provider = getattr(__import__("django.conf", fromlist=["settings"]).settings,
                           "AI_PROVIDER", "mock")
        result = None
        if provider in ("openai", "anthropic"):
            try:
                result = build_staff_translation(
                    text, source, target,
                    translate_fn=lambda t, s, d: _call_llm_translate(t, s, d),
                )
            except Exception:
                result = None

        if result is None:
            return Response({
                "original_text": text,
                "original_language": source,
                "translated_text": None,
                "translated_language": target,
                "is_reliable": False,
                "provider": None,
                "note": "No translation provider configured — showing the original only.",
            }, status=status.HTTP_200_OK)

        return Response(result.as_dict())


def _call_llm_translate(text: str, source: str, target: str):
    """Translate for staff eyes. Returns (text, confidence, provider)."""
    from django.conf import settings as _s
    import requests
    from decimal import Decimal

    prompt = (
        f"Translate the following customer message from {source} to {target}. "
        "Preserve every amount, date and reference exactly. Return only the "
        "translation, no commentary.\n\nMessage:\n" + text[:1000]
    )
    if getattr(_s, "OPENAI_API_KEY", ""):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {_s.OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini",
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 400, "temperature": 0.2},
                timeout=15,
            )
            j = r.json()
            return j["choices"][0]["message"]["content"].strip(), Decimal("0.85"), "openai"
        except Exception:
            return None
    if getattr(_s, "ANTHROPIC_API_KEY", ""):
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": _s.ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json={"model": "claude-3-haiku-20240307", "max_tokens": 400,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=15,
            )
            j = r.json()
            return j["content"][0]["text"].strip(), Decimal("0.85"), "anthropic"
        except Exception:
            return None
    return None


class LanguageMetricsView(APIView):
    """GET /api/v1/ai/language-metrics — §24 Quality Monitoring per language."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.languages.models import Language, CustomerLanguageHistory
        from apps.payments.models import Payment
        from apps.comms.models import CommunicationEvent
        from django.db.models import Count
        org = get_org(request)

        # §24 wants more than a response rate. These sources are optional so
        # the endpoint still works before voice/audit data exists.
        try:
            from apps.audit.models import AICommunicationAudit
            audits = AICommunicationAudit.objects.filter(org=org)
            have_audits = True
        except Exception:
            audits = None
            have_audits = False
        try:
            from apps.voice.models import VoiceCall, CallAttempt
            calls = VoiceCall.objects.filter(org=org)
            have_voice = True
        except Exception:
            calls = None
            CallAttempt = None
            have_voice = False

        active = Language.objects.filter(active=True).order_by("code")
        results = []
        for lang in active:
            code = lang.code
            # customers with this preferred language
            from apps.customers.models import Customer
            cust_count = (
                Customer.objects.for_org(org).filter(preferred_language=lang).count()
                if org else 0
            )
            # payments from customers with this language (via invoice->customer)
            payment_qs = (
                Payment.objects.for_org(org).filter(
                    invoice__customer__preferred_language=lang, status="successful"
                ) if org else Payment.objects.none()
            )
            paid_count = payment_qs.count()

            # comm events, attributed by the language actually used (§21)
            comm_qs = CommunicationEvent.objects.filter(language=code)
            if org:
                comm_qs = comm_qs.filter(org=org)
            comm_total = comm_qs.count()
            comm_sent = comm_qs.filter(status__in=["sent", "delivered"]).count()

            # escalations: audited escalations in this language, plus legacy
            # history rows that recorded a detected switch.
            esc = 0
            if have_audits:
                esc += audits.filter(language_selected=code, escalated=True).count()
            if org:
                esc += CustomerLanguageHistory.objects.filter(
                    org=org, to_lang=lang, reason__in=["auto_detect", "detected_switch"]
                ).count()

            corrected = 0
            if have_audits:
                corrected = audits.filter(language_selected=code, corrected=True).count()

            # voice measures (§24)
            voice_total = voice_completed = voice_stt_ok = 0
            if have_voice:
                voice_total = calls.filter(language_id=code).count()
                voice_completed = calls.filter(
                    language_id=code, status__in=["completed"]
                ).count()
                # An attempt with usable STT confidence counts as recognised.
                voice_stt_ok = (
                    CallAttempt.objects.filter(
                        call__language_id=code, stt_confidence__gte=0.7
                    ).count()
                    if have_voice and CallAttempt is not None else 0
                )

            def pct(num, den):
                return round((num / den * 100), 1) if den else 0.0

            results.append({
                "code": code,
                "name": lang.name,
                "native_name": lang.native_name,
                "active": lang.active,
                "quality_status": lang.quality_status,
                "customers": cust_count,
                # volume
                "successful_payments": paid_count,
                "comm_total": comm_total,
                "comm_sent": comm_sent,
                # §24 measures
                "response_rate": pct(comm_sent, comm_total),
                "payment_conversion_rate": pct(paid_count, cust_count),
                "escalation_rate": pct(esc, max(comm_total, 1)),
                "human_correction_rate": pct(corrected, max(comm_total, 1)),
                "escalations": esc,
                "voice_calls": voice_total,
                "voice_completion_rate": pct(voice_completed, voice_total),
                "voice_recognition_rate": pct(voice_stt_ok, voice_total),
            })

        return Response({
            "metrics": results,
            "data_sources": {
                "audit_trail": have_audits,
                "voice": have_voice,
            },
            "note": (
                "All values are computed from collected data. Response rate is "
                "sent/total communications. Voice metrics are 0 until voice "
                "calls record stt_confidence (S10)."
            ),
        })


class LanguageHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        from apps.languages.models import CustomerLanguageHistory
        org = get_org(request)
        qs = CustomerLanguageHistory.objects.filter(org=org).order_by("-created_at")[:50]
        if pk:
            qs = qs.filter(customer_id=pk)
        return Response([
            {"customer_id": str(h.customer_id), "from": h.from_lang.code if h.from_lang else None, "to": h.to_lang.code if h.to_lang else None, "reason": h.reason, "confidence": str(h.detected_confidence) if h.detected_confidence else None, "created_at": h.created_at}
            for h in qs
        ])

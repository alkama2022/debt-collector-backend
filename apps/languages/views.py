from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Language, OrganizationLanguageSettings
from .serializers import LanguageSerializer, OrganizationLanguageSettingsSerializer
from apps.tenancy.org import get_org


class LanguageDetectView(APIView):
    """
    POST /api/v1/languages/detect
    Body: { "text": "..." }
    Returns detected language code, confidence, and alternatives.
    Delegates to the AI app's router so the logic lives in one place.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        text = (request.data.get("text") or "").strip()
        if not text:
            return Response({"detail": "text is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from apps.languages.router import MultilingualLanguageRouter
            router = MultilingualLanguageRouter()
            code, conf = router.detect_language(text)
        except Exception:
            code, conf = "en", 0.5

        try:
            lang = Language.objects.get(code=code)
            name, native_name = lang.name, lang.native_name
        except Language.DoesNotExist:
            name = native_name = code

        return Response({
            "detected_language": code,
            "language_name": name,
            "native_name": native_name,
            "confidence": round(float(conf), 2),
            "alternatives": [],
        })


class LanguageResolveView(APIView):
    """
    GET /api/v1/languages/resolve?customer_id=<uuid>&text=<str>
    Resolves which language should be used for a response given a customer and/or text.
    Priority: customer preferred → auto-detect from text → org fallback → 'en'.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        customer_id = request.query_params.get("customer_id")
        text = (request.query_params.get("text") or "").strip()

        org = get_org(request)

        # 1. Customer preferred language
        if customer_id:
            try:
                from apps.customers.models import Customer
                cust = Customer.objects.for_org(org).get(pk=customer_id)
                if cust.preferred_language:
                    return Response({
                        "response_language": cust.preferred_language.code,
                        "source": "customer_preferred",
                    })
            except Exception:
                pass

        # 2. Auto-detect from text
        if text:
            try:
                from apps.languages.router import MultilingualLanguageRouter
                router = MultilingualLanguageRouter()
                code, conf = router.detect_language(text)
                if conf >= 0.6:
                    return Response({
                        "response_language": code,
                        "source": "auto_detected",
                        "detected": code,
                        "confidence": round(float(conf), 2),
                    })
            except Exception:
                pass

        # 3. Org fallback language
        if org:
            try:
                settings_obj = OrganizationLanguageSettings.objects.filter(org=org).first()
                if settings_obj and settings_obj.fallback_language:
                    return Response({
                        "response_language": settings_obj.fallback_language.code,
                        "source": "fallback",
                    })
            except Exception:
                pass

        # 4. Hard default
        return Response({"response_language": "en", "source": "fallback"})


class LanguageListView(generics.ListAPIView):
    """GET /api/v1/languages — list all active languages, or all if ?all=true for admin."""
    serializer_class = LanguageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Language.objects.all()
        all_param = self.request.query_params.get("all")
        active_only = self.request.query_params.get("active")
        if all_param and all_param.lower() in ("1", "true", "yes"):
            return qs.order_by("code")
        # default: active only unless ?active=false
        if active_only is not None and active_only.lower() in ("0", "false", "no"):
            return qs.order_by("code")
        return qs.filter(active=True).order_by("code")


class LanguageDetailView(generics.RetrieveAPIView):
    serializer_class = LanguageSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Language.objects.all()
    lookup_field = "code"


class OrganizationLanguageSettingsView(APIView):
    """GET /api/v1/org/language-settings, PATCH /api/v1/org/language-settings"""
    permission_classes = [permissions.IsAuthenticated]

    def _get_org(self, request):
        return get_org(request)

    def _get_or_create(self, org):
        obj, created = OrganizationLanguageSettings.objects.get_or_create(
            org=org,
            defaults={
                "dashboard_language_id": "en",
                "default_customer_language_id": "en",
                "fallback_language_id": "en",
            },
        )
        if created:
            # default supported = active languages
            active_codes = list(Language.objects.filter(active=True).values_list("code", flat=True))
            if active_codes:
                obj.supported_languages.set(Language.objects.filter(code__in=active_codes))
        return obj

    def get(self, request):
        org = self._get_org(request)
        if org is None:
            return Response({"detail": "Organization not found. Provide X-Org-Id header."}, status=status.HTTP_400_BAD_REQUEST)
        settings_obj = self._get_or_create(org)
        serializer = OrganizationLanguageSettingsSerializer(settings_obj)
        return Response(serializer.data)

    def patch(self, request):
        org = self._get_org(request)
        if org is None:
            return Response({"detail": "Organization not found. Provide X-Org-Id header."}, status=status.HTTP_400_BAD_REQUEST)
        settings_obj = self._get_or_create(org)
        serializer = OrganizationLanguageSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def put(self, request):
        return self.patch(request)

from rest_framework import generics, permissions, filters, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.utils import timezone
import uuid
from .models import Customer
from .serializers import CustomerSerializer
from apps.tenancy.org import get_org

class CustomerListCreate(generics.ListCreateAPIView):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["customer_code", "opt_out"]
    search_fields = ["name", "customer_code", "email", "phone"]
    ordering_fields = ["created_at", "name", "outstanding"]
    ordering = ["-created_at"]

    def _get_org(self):
        return get_org(self.request)

    def get_queryset(self):
        org = self._get_org()
        if org is None:
            return Customer.objects.none()
        qs = Customer.objects.for_org(org).filter(deleted_at__isnull=True)
        return qs

    def perform_create(self, serializer):
        org = self._get_org()
        if org:
            from apps.subscriptions.entitlements import check_limit
            allowed, reason, info = check_limit(org, "CUSTOMER_LIMIT", 1)
            if not allowed:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied({"detail": reason, "code": "LIMIT_REACHED", "limit": info.get("limit"), "used": info.get("used")})
        serializer.save(org=org) if org else serializer.save()

class CustomerDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_org(self):
        return get_org(self.request)

    def get_queryset(self):
        org = self._get_org()
        if org is None:
            return Customer.objects.none()
        return Customer.objects.for_org(org).filter(deleted_at__isnull=True)

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


class CustomerBulkCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_org(self, request):
        return get_org(request)

    def post(self, request):
        org = self._get_org(request)
        if org is None:
            return Response({"success": False, "message": "Organization required"}, status=status.HTTP_401_UNAUTHORIZED)

        data = request.data
        rows = data.get("customers") or data.get("rows") or data
        if isinstance(rows, dict) and "customers" in rows:
            rows = rows["customers"]
        if not isinstance(rows, list):
            return Response({"success": False, "message": "Expected {customers: [{name, phone, email, preferred_language}] }"}, status=status.HTTP_400_BAD_REQUEST)
        if len(rows) == 0:
            return Response({"success": False, "message": "No rows provided"}, status=status.HTTP_400_BAD_REQUEST)
        if len(rows) > 500:
            return Response({"success": False, "message": "Max 500 per batch. Split and retry."}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve language codes once
        lang_map = {}
        try:
            from apps.languages.models import Language
            for lang in Language.objects.filter(active=True):
                lang_map[lang.code] = lang
                lang_map[lang.code.lower()] = lang
        except Exception:
            pass

        # Entitlement: check batch would exceed limit
        from apps.subscriptions.entitlements import check_limit
        allowed, reason, info = check_limit(org, "CUSTOMER_LIMIT", len(rows))
        if not allowed:
            return Response({"success": False, "message": reason, "code": "LIMIT_REACHED", "limit": info.get("limit"), "used": info.get("used")}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        created = []
        errors = []
        # Pre-fetch existing phones to avoid dup (soft check, DB will enforce customer_code uniqueness not phone)
        with transaction.atomic():
            for idx, row in enumerate(rows):
                name = (row.get("name") or "").strip()
                phone = (row.get("phone") or "").strip()
                email = (row.get("email") or "").strip()
                pref = (row.get("preferred_language") or row.get("preferredLanguage") or row.get("language") or "en").strip().lower() or "en"
                if not name:
                    errors.append({"index": idx, "row": row, "error": "name required"})
                    continue
                if len(name) < 2:
                    errors.append({"index": idx, "row": row, "error": "name too short"})
                    continue
                # basic phone normalize: keep digits/+
                if phone and len(phone) < 5:
                    errors.append({"index": idx, "row": row, "error": "phone too short"})
                    continue
                lang_obj = lang_map.get(pref)
                if pref not in lang_map and pref != "en":
                    # fallback to en but record warning as not error
                    lang_obj = lang_map.get("en")
                customer_code = row.get("customer_code") or f"CUS-{str(uuid.uuid4())[:8].upper()}"
                # uniq per org
                if Customer.objects.filter(org=org, customer_code=customer_code, deleted_at__isnull=True).exists():
                    customer_code = f"CUS-{str(uuid.uuid4())[:8].upper()}"
                try:
                    cust = Customer(
                        org=org,
                        customer_code=customer_code,
                        name=name[:255],
                        phone=phone[:32],
                        email=email[:255],
                        preferred_language=lang_obj,
                    )
                    cust.full_clean(exclude=["org"])
                    cust.save()
                    created.append(cust)
                except Exception as e:
                    errors.append({"index": idx, "row": row, "error": str(e)[:200]})

        ser = CustomerSerializer(created, many=True)
        return Response({
            "success": True,
            "data": {
                "created": len(created),
                "failed": len(errors),
                "customers": ser.data,
                "errors": errors[:20],  # cap
            },
            "message": f"Imported {len(created)} customers, {len(errors)} failed"
        }, status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST)


class CustomerLanguageView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_org(self, request):
        return get_org(request)

    def get(self, request, pk):
        org = self._get_org(request)
        if org is None:
            return Response({"detail": "Organization required"}, status=400)
        try:
            customer = Customer.objects.for_org(org).get(pk=pk, deleted_at__isnull=True)
        except Customer.DoesNotExist:
            return Response({"detail": "Not found"}, status=404)
        from apps.languages.models import CustomerLanguageHistory
        history = CustomerLanguageHistory.objects.filter(customer=customer).order_by("-created_at")[:20]
        return Response({
            "customer_id": str(customer.id),
            "preferred_language": customer.preferred_language.code if customer.preferred_language else "en",
            "voice_language": customer.voice_language.code if customer.voice_language else None,
            "language_detection_enabled": customer.language_detection_enabled,
            "language_updated_at": customer.language_updated_at,
            "history": [
                {
                    "from_lang": h.from_lang.code if h.from_lang else None,
                    "to_lang": h.to_lang.code if h.to_lang else None,
                    "reason": h.reason,
                    "confidence": str(h.detected_confidence) if h.detected_confidence else None,
                    "created_at": h.created_at,
                } for h in history
            ]
        })

    def patch(self, request, pk):
        from apps.languages.models import Language, CustomerLanguageHistory
        from django.utils import timezone
        org = self._get_org(request)
        if org is None:
            return Response({"detail": "Organization required"}, status=400)
        try:
            customer = Customer.objects.for_org(org).get(pk=pk, deleted_at__isnull=True)
        except Customer.DoesNotExist:
            return Response({"detail": "Not found"}, status=404)
        code = request.data.get("preferred_language") or request.data.get("language")
        if not code:
            return Response({"detail": "preferred_language required"}, status=400)
        try:
            lang = Language.objects.get(code=code, active=True)
        except Language.DoesNotExist:
            return Response({"detail": f"Language {code} not active"}, status=400)
        from_lang = customer.preferred_language
        customer.preferred_language = lang
        customer.language_updated_at = timezone.now()
        if "voice_language" in request.data:
            vcode = request.data.get("voice_language")
            if vcode:
                try:
                    vlang = Language.objects.get(code=vcode)
                    customer.voice_language = vlang
                except Language.DoesNotExist:
                    pass
            else:
                customer.voice_language = None
        if "language_detection_enabled" in request.data:
            customer.language_detection_enabled = bool(request.data.get("language_detection_enabled"))
        customer.save()
        CustomerLanguageHistory.objects.create(
            org=org, customer=customer, from_lang=from_lang, to_lang=lang,
            reason="business_change", changed_by=request.user
        )
        return Response({
            "customer_id": str(customer.id),
            "preferred_language": lang.code,
            "voice_language": customer.voice_language.code if customer.voice_language else None,
        })

    def post(self, request, pk):
        return self.patch(request, pk)

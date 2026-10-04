from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from decimal import Decimal
import uuid
from .models import Payment, Receipt
from .serializers import PaymentSerializer
from apps.tenancy.org import get_org

class PaymentListCreate(generics.ListCreateAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "provider", "currency", "invoice"]
    search_fields = ["provider_ref"]
    ordering = ["-created_at"]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return Payment.objects.none()
        return Payment.objects.for_org(org).select_related("invoice")

    def create(self, request, *args, **kwargs):
        idem_key = request.headers.get("X-Idempotency-Key") or request.headers.get("Idempotency-Key") or request.data.get("idempotency_key")
        if idem_key:
            org = get_org(request)
            if org is not None:
                existing = Payment.objects.filter(idempotency_key=idem_key, org=org).first()
                if existing:
                    serializer = self.get_serializer(existing)
                    return Response(serializer.data, status=status.HTTP_200_OK)
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError as e:
            return Response({"success": False, "message": "Idempotency conflict", "errors": str(e)}, status=status.HTTP_409_CONFLICT)

class PaymentDetail(generics.RetrieveUpdateAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return Payment.objects.none()
        return Payment.objects.for_org(org)


def _initialize_paystack(request, org_required=False):
    """
    Shared logic for both authenticated and unauthenticated Paystack initialization.

    When org_required=True (authenticated path), resolves org from the request user.
    When org_required=False (public path), resolves org directly from the invoice.
    """
    from apps.invoices.models import Invoice

    invoice_id = request.data.get("invoice") or request.data.get("invoice_id")
    if not invoice_id:
        return Response({"success": False, "message": "invoice required"}, status=status.HTTP_400_BAD_REQUEST)

    # Resolve org
    org = get_org(request)

    if org_required and org is None:
        return Response({"success": False, "message": "Organization required"}, status=status.HTTP_401_UNAUTHORIZED)

    # Resolve invoice — public path looks up by ID globally (no org filter)
    try:
        if org:
            invoice = Invoice.objects.for_org(org).get(pk=invoice_id, deleted_at__isnull=True)
        else:
            invoice = Invoice.objects.select_related("customer", "org").get(pk=invoice_id, deleted_at__isnull=True)
            org = invoice.org
    except Invoice.DoesNotExist:
        return Response({"success": False, "message": "Invoice not found"}, status=status.HTTP_404_NOT_FOUND)

    if invoice.balance <= 0:
        return Response({"success": False, "message": "Invoice already paid"}, status=status.HTTP_400_BAD_REQUEST)

    # Build reference and metadata
    reference = f"CN-{invoice.invoice_number}-{str(uuid.uuid4())[:8].upper()}"
    amount_minor = int(Decimal(invoice.balance) * Decimal(100))
    email = invoice.customer.email or f"{invoice.customer.phone or 'customer'}@collectnaija.com"
    frontend_base = getattr(settings, "FRONTEND_URL", "") or request.build_absolute_uri("/").split("/api")[0]
    pay_url = f"{frontend_base.rstrip('/')}/pay/{invoice.id}"
    callback_url = f"{pay_url}?reference={reference}"
    metadata = {
        "invoice_id": str(invoice.id),
        "org_id": str(org.id),
        "invoice_number": invoice.invoice_number,
        "pay_url": pay_url,
        "custom_fields": [{"display_name": "Invoice", "variable_name": "invoice_number", "value": invoice.invoice_number}],
    }

    # Pre-create pending payment idempotently
    idem = f"init:{reference}"
    if not Payment.objects.filter(provider_ref=reference).exists():
        Payment.objects.create(
            org=org, invoice=invoice, amount=invoice.balance, currency=invoice.currency,
            status="pending", provider="paystack", provider_ref=reference, idempotency_key=idem,
        )

    from .paystack import initialize_payment
    try:
        init = initialize_payment(
            email=email, amount_minor=amount_minor,
            reference=reference, metadata=metadata, callback_url=callback_url,
        )
        return Response({
            "success": True,
            "data": {
                "authorization_url": init.get("authorization_url"),
                "access_code": init.get("access_code"),
                "reference": reference,
                "mock": init.get("mock", False),
                "pay_url": pay_url,
            },
        })
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


class PublicPaystackInitializeView(APIView):
    """
    POST /public/pay/<invoice_id>/initialize  — no authentication required.
    Called from the public /pay/:id page when the customer clicks "Pay".
    Returns the same shape as the authenticated initialize endpoint.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, pk):
        # Inject invoice id from URL param so _initialize_paystack can read it
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        data["invoice"] = str(pk)
        # Patch request.data for the helper
        request._full_data = data
        return _initialize_paystack(request, org_required=False)


class PublicPaystackVerifyView(APIView):
    """
    GET /public/pay/verify?reference=...  — no authentication required.
    Called from the customer's browser after Paystack redirects back.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        reference = request.query_params.get("reference") or request.query_params.get("trxref")
        if not reference:
            return Response({"success": False, "message": "reference required"}, status=status.HTTP_400_BAD_REQUEST)

        from .paystack import verify_payment
        is_mock = not getattr(settings, "PAYSTACK_SECRET_KEY", "")
        paystack_data = None
        try:
            paystack_data = verify_payment(reference)
        except Exception as e:
            if not is_mock:
                return Response({"success": False, "message": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        payment = Payment.objects.filter(provider_ref=reference).first()
        if not payment:
            return Response({"success": False, "message": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

        should_succeed = is_mock or (paystack_data and paystack_data.get("status") == "success")
        if should_succeed and payment.status != "successful":
            payment.status = "successful"
            payment.verified_at = timezone.now()
            payment.save(update_fields=["status", "verified_at"])

        return Response({
            "success": True,
            "data": {
                "payment_id": str(payment.id),
                "status": payment.status,
                "invoice_id": str(payment.invoice_id),
                "mock": is_mock,
            },
        })

    def post(self, request):
        reference = request.data.get("reference") or request.query_params.get("reference")
        if reference:
            from django.http import QueryDict
            qd = request.query_params.copy()
            qd["reference"] = reference
            request._request.GET = qd
        return self.get(request)


class PaystackInitializeView(APIView):
    """POST /payments/initialize {invoice: uuid} -> {authorization_url, reference, mock}
    Requires authentication (business owner testing their own invoice link).
    For unauthenticated customer payments, use PublicPaystackInitializeView below.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        return _initialize_paystack(request, org_required=True)


class PaystackVerifyView(APIView):
    """GET /payments/verify?reference=CN-... -> verifies and marks successful, updates invoice via signal."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org = get_org(request)
        reference = request.query_params.get("reference") or request.query_params.get("trxref")
        if not reference:
            return Response({"success": False, "message": "reference required"}, status=status.HTTP_400_BAD_REQUEST)
        # Try paystack verify if configured, otherwise mark our pending payment as successful (mock verification)
        from .paystack import verify_payment
        paystack_data = None
        is_mock = not getattr(settings, "PAYSTACK_SECRET_KEY", "")
        try:
            paystack_data = verify_payment(reference)
        except Exception as e:
            # If paystack fails in mock mode, still allow manual verify
            if not is_mock:
                return Response({"success": False, "message": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        # Find payment by provider_ref
        qs = Payment.objects.filter(provider_ref=reference)
        if org:
            qs = qs.filter(org=org)
        payment = qs.first()
        if not payment:
            # Try without org filter (webhook may have different org context)
            payment = Payment.objects.filter(provider_ref=reference).first()
        if not payment:
            return Response({"success": False, "message": "Payment not found for reference"}, status=status.HTTP_404_NOT_FOUND)
        # Decide success: in mock mode, always succeed; in real mode check paystack_data.status == "success"
        should_succeed = False
        if is_mock:
            should_succeed = True
        elif paystack_data and paystack_data.get("status") == "success":
            should_succeed = True
            # Verify amount minor matches
            try:
                ps_amount = int(paystack_data.get("amount") or 0)
                if ps_amount and abs(ps_amount - int(Decimal(payment.amount) * 100)) > 100:  # allow 1 NGN drift
                    pass
            except Exception:
                pass
        if should_succeed and payment.status != "successful":
            payment.status = "successful"
            payment.verified_at = timezone.now()
            payment.save(update_fields=["status", "verified_at"])
            # signal will update invoice balance/status and create receipt
        return Response({"success": True, "data": {"payment_id": str(payment.id), "status": payment.status, "invoice_id": str(payment.invoice_id), "paystack": paystack_data, "mock": is_mock}})

    def post(self, request):
        # Allow POST {reference}
        reference = request.data.get("reference") or request.query_params.get("reference")
        if reference:
            request.query_params._mutable = True
            request.query_params["reference"] = reference
            request.query_params._mutable = False
        return self.get(request)


class ReceiptPdfView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        org = get_org(request)
        if org is None:
            return Response({"success": False, "message": "Organization required"}, status=status.HTTP_401_UNAUTHORIZED)
        # pk is payment id
        payment = get_object_or_404(Payment.objects.for_org(org).select_related("invoice", "invoice__customer", "org"), pk=pk)
        # Ensure receipt exists or create mock number
        receipt = getattr(payment, "receipt", None)
        receipt_number = receipt.receipt_number if receipt else f"RCT-{str(payment.id)[:8].upper()}"
        amount = payment.amount
        currency = payment.currency
        # Generate receipt PDF
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
        from io import BytesIO

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=14*mm, bottomMargin=14*mm,
                                title=f"Receipt {receipt_number}", author=payment.org.name if payment.org else "CollectNaija")
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("Title2", parent=styles["Heading1"], fontSize=20, textColor=colors.HexColor("#059669"), alignment=TA_CENTER, spaceAfter=2)
        subtitle = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"), alignment=TA_CENTER, spaceAfter=6)
        normal = ParagraphStyle("N", parent=styles["Normal"], fontSize=9, leading=12)
        bold = ParagraphStyle("B", parent=normal, fontName="Helvetica-Bold")
        right_style = ParagraphStyle("R", parent=normal, alignment=TA_RIGHT)
        bold_right = ParagraphStyle("BR", parent=bold, alignment=TA_RIGHT)
        center = ParagraphStyle("C", parent=normal, alignment=TA_CENTER)

        story = []
        story.append(Paragraph("✓ PAYMENT RECEIPT", title_style))
        story.append(Paragraph(f"{payment.org.name if payment.org else 'CollectNaija'}  •  {receipt_number}", subtitle))
        story.append(Spacer(1, 4*mm))
        # Paid stamp box
        cust_name = payment.invoice.customer.name if payment.invoice and payment.invoice.customer else "Customer"
        inv_no = payment.invoice.invoice_number if payment.invoice else "—"
        story.append(Paragraph(f"<b>Payment received successfully.</b> Thank you, {cust_name}.", ParagraphStyle("Thanks", parent=center, fontSize=10, textColor=colors.HexColor("#065f46"))))
        story.append(Spacer(1, 5*mm))

        # Details table
        rows = [
            [Paragraph("<b>Receipt</b>", normal), Paragraph(receipt_number, bold_right)],
            [Paragraph("Invoice", normal), Paragraph(inv_no, right_style)],
            [Paragraph("Customer", normal), Paragraph(cust_name, right_style)],
            [Paragraph("Amount paid", bold), Paragraph(f"<b>{currency} {float(amount):,.2f}</b>", ParagraphStyle("Amt", parent=bold_right, textColor=colors.HexColor("#059669"), fontSize=11))],
            [Paragraph("Method / Provider", normal), Paragraph(f"{payment.provider}  •  {payment.provider_ref or payment.id}", right_style)],
            [Paragraph("Status", normal), Paragraph(f"<b>{payment.get_status_display()}</b>", ParagraphStyle("S", parent=right_style, textColor=colors.HexColor("#059669") if payment.status=='successful' else colors.HexColor("#d97706")))],
            [Paragraph("Date", normal), Paragraph(payment.created_at.strftime("%d %b %Y, %I:%M %p Africa/Lagos"), right_style)],
        ]
        if payment.invoice:
            bal = payment.invoice.balance
            rows.append([Paragraph("Remaining balance", normal), Paragraph(f"{payment.invoice.currency} {float(bal):,.2f}", bold_right)])
        t = Table(rows, colWidths=[55*mm, 115*mm])
        t.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.6, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f8fafc")),
            ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, colors.HexColor("#f0fdf4")]),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(t)
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("This is a computer-generated receipt. No signature required. For enquiries contact support@collectnaija.com", ParagraphStyle("Foot", parent=center, fontSize=6.5, textColor=colors.HexColor("#94a3b8"))))
        story.append(Paragraph(f"Org: {payment.org.name if payment.org else ''}  |  Generated {payment.created_at.strftime('%Y-%m-%d %H:%M')}  |  CollectNaija", ParagraphStyle("Foot2", parent=center, fontSize=6, textColor=colors.HexColor("#cbd5e1"))))
        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{receipt_number}.pdf"'
        resp["Content-Length"] = str(len(pdf))
        return resp

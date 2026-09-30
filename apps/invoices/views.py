from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status
import uuid
from .models import Invoice
from .serializers import InvoiceSerializer
from apps.tenancy.org import get_org

class InvoiceListCreate(generics.ListCreateAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "customer", "currency", "invoice_number"]
    search_fields = ["invoice_number"]
    ordering_fields = ["created_at", "due_date", "total"]
    ordering = ["-created_at"]

    def _get_org(self):
        return get_org(self.request)

    def get_queryset(self):
        org = self._get_org()
        if org is None:
            return Invoice.objects.none()
        qs = Invoice.objects.for_org(org).filter(deleted_at__isnull=True)
        # query param filtering already via filterset, but support status param explicitly
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs.select_related("customer").prefetch_related("items")

    def create(self, request, *args, **kwargs):
        # Idempotency handling via header
        idem_key = request.headers.get("X-Idempotency-Key") or request.headers.get("Idempotency-Key") or request.headers.get("X-IDEMPOTENCY-KEY")
        if idem_key:
            org = self._get_org()
            if org is not None:
                existing = Invoice.objects.filter(idempotency_key=idem_key, org=org).first()
                if existing:
                    serializer = self.get_serializer(existing)
                    return Response(serializer.data, status=http_status.HTTP_200_OK)
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError as e:
            return Response({"success": False, "message": "Duplicate invoice or idempotency conflict", "errors": str(e)}, status=http_status.HTTP_409_CONFLICT)

class InvoiceDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_org(self):
        return get_org(self.request)

    def get_queryset(self):
        org = self._get_org()
        if org is None:
            return Invoice.objects.none()
        return Invoice.objects.for_org(org).filter(deleted_at__isnull=True).prefetch_related("items")

    def perform_destroy(self, instance):
        from django.utils import timezone
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])


class InvoicePdfView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        org = get_org(request)
        if org is None:
            return Response({"success": False, "message": "Organization required"}, status=http_status.HTTP_401_UNAUTHORIZED)
        invoice = get_object_or_404(Invoice.objects.for_org(org).prefetch_related("items").select_related("customer", "org"), pk=pk, deleted_at__isnull=True)
        # Generate PDF with reportlab
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT
        from io import BytesIO

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=14*mm, bottomMargin=14*mm,
                                title=f"Invoice {invoice.invoice_number}", author=invoice.org.name if invoice.org else "CollectNaija")
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("Title2", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#0f4c81"), spaceAfter=6)
        h2 = ParagraphStyle("H2", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#64748b"), spaceAfter=2)
        normal = ParagraphStyle("N", parent=styles["Normal"], fontSize=9, leading=12)
        bold = ParagraphStyle("B", parent=normal, fontName="Helvetica-Bold")
        right_style = ParagraphStyle("R", parent=normal, alignment=TA_RIGHT)
        bold_right = ParagraphStyle("BR", parent=bold, alignment=TA_RIGHT)

        story = []
        # Header
        story.append(Paragraph(f"{invoice.org.name if invoice.org else 'CollectNaija'}", title_style))
        story.append(Paragraph(f"Invoice <b>{invoice.invoice_number}</b> &nbsp;|&nbsp; {invoice.get_status_display()} &nbsp;|&nbsp; {invoice.currency}", h2))
        story.append(Spacer(1, 6*mm))

        # Bill-to + meta
        cust = invoice.customer
        org_name = invoice.org.name if invoice.org else ""
        meta_data = [
            [Paragraph(f"<b>Bill to</b><br/>{cust.name}<br/>{cust.phone}<br/>{cust.email or ''}", normal),
             Paragraph(f"<b>Invoice:</b> {invoice.invoice_number}<br/><b>Issue:</b> {invoice.created_at.strftime('%d %b %Y')}<br/><b>Due:</b> {invoice.due_date.strftime('%d %b %Y') if invoice.due_date else '—'}<br/><b>Balance due:</b> {invoice.currency} {invoice.balance:,.2f}", right_style)]
        ]
        t = Table(meta_data, colWidths=[85*mm, 85*mm])
        t.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6)]))
        story.append(t)
        story.append(Spacer(1, 6*mm))

        # Items table
        items = list(invoice.items.all())
        if not items:
            # fallback single line from totals
            items_data = [["Description", "Qty", "Unit", "Total"],
                          ["Service", "1", f"{invoice.currency} {invoice.total:,.2f}", f"{invoice.currency} {invoice.total:,.2f}"]]
        else:
            items_data = [["Description", "Qty", "Unit", "Total"]]
            for it in items:
                unit = float(it.unit_price_minor) / 100
                total = float(it.line_total)
                items_data.append([Paragraph(it.name, normal), str(it.qty), f"{invoice.currency} {unit:,.2f}", f"{invoice.currency} {total:,.2f}"])

        # Convert first row header styling via TableStyle
        # Ensure all rows are Paragraph-friendly
        tbl_data = []
        for r_idx, row in enumerate(items_data):
            if r_idx == 0:
                tbl_data.append([Paragraph(f"<b>{c}</b>", ParagraphStyle("H", parent=normal, textColor=colors.white, alignment=TA_LEFT if i==0 else TA_RIGHT)) for i,c in enumerate(row)])
            else:
                tbl_data.append(row)
        col_w = [85*mm, 22*mm, 32*mm, 32*mm]
        itable = Table(tbl_data, colWidths=col_w, repeatRows=1)
        itable.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f2d55")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("ALIGN", (1,0), (-1,-1), "RIGHT"),
            ("ALIGN", (0,0), (0,-1), "LEFT"),
            ("GRID", (0,0), (-1,-1), 0.6, colors.HexColor("#e2e8f0")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(itable)
        story.append(Spacer(1, 4*mm))

        # Totals box
        totals = [
            [Paragraph("Subtotal", normal), Paragraph(f"{invoice.currency} {float(invoice.subtotal):,.2f}", bold_right)],
            [Paragraph("Discount", normal), Paragraph(f"-{invoice.currency} {float(invoice.discount):,.2f}", right_style)],
            [Paragraph("Tax", normal), Paragraph(f"{invoice.currency} {float(invoice.tax):,.2f}", right_style)],
            [Paragraph("<b>Total</b>", bold), Paragraph(f"<b>{invoice.currency} {float(invoice.total):,.2f}</b>", bold_right)],
            [Paragraph("<b>Amount paid</b>", ParagraphStyle("G", parent=normal, textColor=colors.HexColor("#059669"))), Paragraph(f"{invoice.currency} {float(invoice.total - invoice.balance):,.2f}", ParagraphStyle("GR", parent=bold_right, textColor=colors.HexColor("#059669")))],
            [Paragraph("<b>Balance due</b>", ParagraphStyle("B2", parent=bold, textColor=colors.HexColor("#0f4c81"), fontSize=11)), Paragraph(f"<b>{invoice.currency} {float(invoice.balance):,.2f}</b>", ParagraphStyle("BR2", parent=bold_right, textColor=colors.HexColor("#0f4c81"), fontSize=11))],
        ]
        t2 = Table(totals, colWidths=[120*mm, 50*mm])
        t2.setStyle(TableStyle([
            ("LINEABOVE", (0,3), (-1,3), 1, colors.HexColor("#0f2d55")),
            ("LINEABOVE", (0,5), (-1,5), 1.2, colors.HexColor("#0f2d55")),
            ("ALIGN", (1,0), (-1,-1), "RIGHT"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(t2)
        story.append(Spacer(1, 8*mm))
        pay_url_hint = f"Pay securely: {request.build_absolute_uri('/').rstrip('/')}/pay/{invoice.id}"
        story.append(Paragraph(f"Thank you for your business. Questions? Contact {org_name}. &nbsp;|&nbsp; Pay link: {pay_url_hint}", ParagraphStyle("Foot", parent=normal, fontSize=7, textColor=colors.HexColor("#94a3b8"), alignment=TA_LEFT)))
        story.append(Paragraph("Generated by CollectNaija — backend-calculated totals, no float authority on client.", ParagraphStyle("Foot2", parent=normal, fontSize=6, textColor=colors.HexColor("#cbd5e1"))))

        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{invoice.invoice_number}.pdf"'
        resp["Content-Length"] = str(len(pdf))
        return resp


class InvoicePayLinkView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        org = get_org(request)
        if org is None:
            return Response({"success": False, "message": "Organization required"}, status=http_status.HTTP_401_UNAUTHORIZED)
        invoice = get_object_or_404(Invoice, pk=pk, org=org, deleted_at__isnull=True)
        # Build pay URL — frontend route /pay/:id . In production this would be pay.collectnaija.com
        # Use X-Forwarded host or request host for demo
        frontend_base = getattr(settings, "FRONTEND_URL", None) or request.headers.get("X-Frontend-Url") or request.build_absolute_uri("/").rstrip("/")
        # Prefer configured frontend; fallback to same origin
        if "api" in frontend_base:
            # strip /api suffix if present
            frontend_base = frontend_base.split("/api")[0]
        token = invoice.id  # for MVP, invoice id is token; could be signed JWT in future
        pay_url = f"{frontend_base}/pay/{token}"
        # If Paystack configured, include provider hint
        provider = "paystack" if getattr(settings, "PAYSTACK_SECRET_KEY", "") else "mock"
        return Response({"success": True, "data": {"pay_url": pay_url, "token": str(token), "invoice_number": invoice.invoice_number, "amount": str(invoice.balance), "currency": invoice.currency, "provider": provider}})


class PublicPayInfoView(APIView):
    """GET /public/pay/<uuid> — no auth, returns safe invoice fields for customer pay page."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, pk):
        try:
            invoice = Invoice.objects.select_related("customer", "org").get(pk=pk, deleted_at__isnull=True)
        except Invoice.DoesNotExist:
            return Response({"success": False, "message": "Invoice not found"}, status=http_status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": {
            "invoice_number": invoice.invoice_number,
            "customer_name": invoice.customer.name if invoice.customer else "Customer",
            "due_date": str(invoice.due_date) if invoice.due_date else None,
            "total": str(invoice.total),
            "balance": str(invoice.balance),
            "currency": invoice.currency,
            "status": invoice.status,
            "org_name": invoice.org.name if invoice.org else "CollectNaija Business",
        }})

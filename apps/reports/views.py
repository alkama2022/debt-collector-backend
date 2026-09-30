"""
views.py — Reports API endpoints for CollectNaija.

Endpoints:
  GET /api/v1/reports/summary?range=30   — KPIs + charts data
  GET /api/v1/reports/export?format=csv&range=30  — CSV export
  GET /api/v1/reports/export?format=pdf&range=30  — PDF export (ReportLab)
"""
import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.tenancy.org import get_org


def _get_org(request):
    org = get_org(request)
    return org


def _parse_range(request) -> int:
    """Parse ?range=N (days) parameter, default 30."""
    try:
        return max(1, min(int(request.query_params.get("range", 30)), 365))
    except (ValueError, TypeError):
        return 30


class ReportsSummaryView(APIView):
    """
    GET /api/v1/reports/summary?range=30

    Returns:
      - kpis: Total outstanding, overdue, collected, collection rate
      - cash_flow: Daily collected/outstanding series for the chart
      - aging: Invoice aging buckets (0-30, 31-60, 61-90, 90+ days)
      - channel_stats: Reminder effectiveness by channel
      - top_debtors: Top 10 customers by outstanding balance
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        if not org:
            return Response({"success": False, "message": "Organization required"}, status=401)

        days = _parse_range(request)
        since = timezone.now() - timedelta(days=days)
        today = timezone.now().date()

        from apps.invoices.models import Invoice
        from apps.payments.models import Payment
        from apps.comms.models import CommunicationEvent
        from apps.customers.models import Customer

        # ── KPIs ──────────────────────────────────────────────────────────────
        inv_qs = Invoice.objects.for_org(org).filter(deleted_at__isnull=True)
        pay_qs = Payment.objects.for_org(org)

        total_outstanding = inv_qs.filter(balance__gt=0).aggregate(
            s=Sum("balance")
        )["s"] or Decimal("0")

        total_overdue = inv_qs.filter(
            balance__gt=0, status="overdue"
        ).aggregate(s=Sum("balance"))["s"] or Decimal("0")

        total_collected = pay_qs.filter(
            status="successful", created_at__gte=since
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0")

        total_invoiced = inv_qs.filter(created_at__gte=since).aggregate(
            s=Sum("total")
        )["s"] or Decimal("1")

        collection_rate = (
            round(float(total_collected) / float(total_collected + total_outstanding) * 100, 1)
            if (total_collected + total_outstanding) > 0 else 0.0
        )

        # ── Cash Flow — daily series ──────────────────────────────────────────
        cash_flow = []
        for i in range(min(days, 90), -1, -1):  # cap at 90 data points
            d = today - timedelta(days=i)
            day_collected = pay_qs.filter(
                status="successful", created_at__date=d
            ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
            day_outstanding = inv_qs.filter(
                balance__gt=0, created_at__date__lte=d
            ).aggregate(s=Sum("balance"))["s"] or Decimal("0")
            cash_flow.append({
                "date": str(d),
                "collected": float(day_collected),
                "outstanding": float(day_outstanding),
            })

        # ── Aging Buckets ──────────────────────────────────────────────────────
        def aging_bucket(min_days, max_days=None):
            f = inv_qs.filter(balance__gt=0, due_date__isnull=False)
            if max_days is not None:
                cutoff_end = today - timedelta(days=min_days)
                cutoff_start = today - timedelta(days=max_days)
                f = f.filter(due_date__gt=cutoff_start, due_date__lte=cutoff_end)
            else:
                cutoff = today - timedelta(days=min_days)
                f = f.filter(due_date__lte=cutoff)
            agg = f.aggregate(total=Sum("balance"), count=Count("id"))
            return {
                "total": float(agg["total"] or 0),
                "count": agg["count"] or 0,
            }

        aging = {
            "current": aging_bucket(0, 0),      # not yet overdue
            "1_30": aging_bucket(1, 30),
            "31_60": aging_bucket(31, 60),
            "61_90": aging_bucket(61, 90),
            "90_plus": aging_bucket(91),
        }
        # current = invoices not yet due
        current_q = inv_qs.filter(balance__gt=0, due_date__gte=today)
        aging["current"] = {
            "total": float(current_q.aggregate(s=Sum("balance"))["s"] or 0),
            "count": current_q.count(),
        }

        # ── Channel Effectiveness ─────────────────────────────────────────────
        channels = ["whatsapp", "sms", "email", "voice"]
        channel_stats = []
        for ch in channels:
            total = CommunicationEvent.objects.for_org(org).filter(
                channel=ch, created_at__gte=since
            ).count()
            sent = CommunicationEvent.objects.for_org(org).filter(
                channel=ch, status__in=["sent", "delivered"], created_at__gte=since
            ).count()
            failed = CommunicationEvent.objects.for_org(org).filter(
                channel=ch, status="failed", created_at__gte=since
            ).count()
            channel_stats.append({
                "channel": ch,
                "total": total,
                "sent": sent,
                "failed": failed,
                "success_rate": round(sent / total * 100, 1) if total else 0,
            })

        # ── Top Debtors ───────────────────────────────────────────────────────
        from apps.customers.models import Customer
        top_debtors_qs = (
            Customer.objects.for_org(org)
            .filter(deleted_at__isnull=True, outstanding__gt=0)
            .order_by("-outstanding")[:10]
        )
        top_debtors = [
            {
                "id": str(c.id),
                "name": c.name,
                "phone": c.phone,
                "outstanding": float(c.outstanding),
                "overdue": float(c.overdue),
                "invoice_count": inv_qs.filter(customer=c, balance__gt=0).count(),
            }
            for c in top_debtors_qs
        ]

        return Response({
            "success": True,
            "data": {
                "range_days": days,
                "kpis": {
                    "total_outstanding": float(total_outstanding),
                    "total_overdue": float(total_overdue),
                    "total_collected": float(total_collected),
                    "collection_rate": collection_rate,
                    "open_invoices": inv_qs.filter(balance__gt=0).count(),
                    "overdue_invoices": inv_qs.filter(balance__gt=0, status="overdue").count(),
                    "total_customers": Customer.objects.for_org(org).filter(deleted_at__isnull=True).count(),
                    "total_payments": pay_qs.filter(status="successful", created_at__gte=since).count(),
                },
                "cash_flow": cash_flow,
                "aging": aging,
                "channel_stats": channel_stats,
                "top_debtors": top_debtors,
            }
        })


class ReportsExportView(APIView):
    """
    GET /api/v1/reports/export?format=csv&range=30
    GET /api/v1/reports/export?format=pdf&range=30
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        if not org:
            return Response({"success": False, "message": "Organization required"}, status=401)

        fmt = request.query_params.get("format", "csv").lower()
        days = _parse_range(request)

        if fmt == "csv":
            return self._export_csv(org, days)
        elif fmt == "pdf":
            return self._export_pdf(org, days)
        else:
            return Response({"success": False, "message": "format must be csv or pdf"}, status=400)

    def _export_csv(self, org, days):
        from apps.invoices.models import Invoice
        from datetime import timedelta

        since = timezone.now() - timedelta(days=days)
        invoices = (
            Invoice.objects.for_org(org)
            .filter(deleted_at__isnull=True, created_at__gte=since)
            .select_related("customer")
            .order_by("-created_at")
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Invoice #", "Customer", "Phone", "Email",
            "Status", "Total", "Balance", "Due Date", "Created At"
        ])
        for inv in invoices:
            writer.writerow([
                inv.invoice_number,
                inv.customer.name if inv.customer else "",
                inv.customer.phone if inv.customer else "",
                inv.customer.email if inv.customer else "",
                inv.status,
                float(inv.total),
                float(inv.balance),
                str(inv.due_date) if inv.due_date else "",
                inv.created_at.strftime("%Y-%m-%d %H:%M"),
            ])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="collectnaija-report-{days}d.csv"'
        return response

    def _export_pdf(self, org, days):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from apps.invoices.models import Invoice
        from apps.payments.models import Payment
        from datetime import timedelta

        since = timezone.now() - timedelta(days=days)
        BRAND = colors.HexColor("#0f4c81")
        GREEN = colors.HexColor("#059669")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=18*mm, rightMargin=18*mm, topMargin=14*mm, bottomMargin=14*mm,
            title=f"CollectNaija Report — {org.name}",
        )
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, textColor=BRAND, spaceAfter=4)
        sub = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#64748b"), spaceAfter=8)
        normal = ParagraphStyle("N", parent=styles["Normal"], fontSize=9)
        bold = ParagraphStyle("B", parent=normal, fontName="Helvetica-Bold")
        right = ParagraphStyle("R", parent=normal, alignment=TA_RIGHT)

        story = []
        story.append(Paragraph(f"📊 Collections Report — {org.name}", h1))
        story.append(Paragraph(f"Period: Last {days} days | Generated {timezone.now().strftime('%d %b %Y %H:%M')} WAT", sub))
        story.append(HRFlowable(width="100%", color=BRAND, thickness=1))
        story.append(Spacer(1, 5*mm))

        # KPI summary table
        inv_qs = Invoice.objects.for_org(org).filter(deleted_at__isnull=True)
        total_out = inv_qs.filter(balance__gt=0).aggregate(s=Sum("balance"))["s"] or Decimal("0")
        total_over = inv_qs.filter(balance__gt=0, status="overdue").aggregate(s=Sum("balance"))["s"] or Decimal("0")
        total_col = Payment.objects.for_org(org).filter(status="successful", created_at__gte=since).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        rate = round(float(total_col) / float(total_col + total_out) * 100, 1) if (total_col + total_out) > 0 else 0

        kpi_data = [
            [Paragraph("<b>Metric</b>", bold), Paragraph("<b>Value</b>", ParagraphStyle("BR", parent=bold, alignment=TA_RIGHT))],
            [Paragraph("Total Outstanding", normal), Paragraph(f"NGN {float(total_out):,.2f}", right)],
            [Paragraph("Total Overdue", normal), Paragraph(f"NGN {float(total_over):,.2f}", ParagraphStyle("Red", parent=right, textColor=colors.HexColor("#dc2626")))],
            [Paragraph(f"Collected (last {days}d)", normal), Paragraph(f"NGN {float(total_col):,.2f}", ParagraphStyle("Grn", parent=right, textColor=GREEN))],
            [Paragraph("Collection Rate", bold), Paragraph(f"<b>{rate}%</b>", ParagraphStyle("RateR", parent=right, textColor=GREEN if rate >= 50 else colors.HexColor("#d97706")))],
        ]
        t = Table(kpi_data, colWidths=[80*mm, 90*mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(t)
        story.append(Spacer(1, 8*mm))

        # Invoice table
        story.append(Paragraph("<b>Invoice Summary</b>", bold))
        story.append(Spacer(1, 3*mm))
        invoices = inv_qs.filter(created_at__gte=since).select_related("customer").order_by("-created_at")[:50]
        rows = [[
            Paragraph("<b>Invoice #</b>", bold),
            Paragraph("<b>Customer</b>", bold),
            Paragraph("<b>Status</b>", bold),
            Paragraph("<b>Balance</b>", ParagraphStyle("BldR", parent=bold, alignment=TA_RIGHT)),
        ]]
        status_colors = {
            "paid": GREEN, "overdue": colors.HexColor("#dc2626"),
            "partial": colors.HexColor("#d97706"), "sent": BRAND,
            "draft": colors.HexColor("#94a3b8"),
        }
        for inv in invoices:
            sc = status_colors.get(inv.status, colors.black)
            rows.append([
                Paragraph(inv.invoice_number, normal),
                Paragraph(inv.customer.name if inv.customer else "—", normal),
                Paragraph(inv.status.upper(), ParagraphStyle(f"S{inv.status}", parent=normal, textColor=sc)),
                Paragraph(f"NGN {float(inv.balance):,.2f}", right),
            ])
        inv_table = Table(rows, colWidths=[35*mm, 70*mm, 25*mm, 40*mm])
        inv_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(inv_table)
        story.append(Spacer(1, 6*mm))
        story.append(Paragraph(
            f"Generated by CollectNaija | {org.name} | {timezone.now().strftime('%Y-%m-%d %H:%M')} WAT",
            ParagraphStyle("Foot", parent=styles["Normal"], fontSize=7, textColor=colors.HexColor("#94a3b8"), alignment=TA_CENTER)
        ))

        doc.build(story)
        pdf = buffer.getvalue()
        buffer.close()
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="collectnaija-report-{days}d.pdf"'
        resp["Content-Length"] = str(len(pdf))
        return resp

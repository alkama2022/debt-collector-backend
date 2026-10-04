"""
email_provider.py — Django SMTP/console email provider.
Uses Django's built-in email system.
Falls back to console backend in DEBUG mode.

Required settings:
    EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
    DEFAULT_FROM_EMAIL — e.g. "CollectNaija <noreply@collectnaija.com>"
"""
import logging
from django.core.mail import send_mail
from django.conf import settings
from .base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)


class EmailProvider(BaseProvider):
    channel = "email"

    def send(self, event) -> ProviderResult:
        email = self._get_email(event)
        if not email:
            return ProviderResult(
                success=False,
                error_code="NO_EMAIL",
                error_message="Customer has no email address",
            )

        body = self._render_template(event)
        subject = self._build_subject(event)
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "CollectNaija <noreply@collectnaija.com>")

        try:
            send_mail(
                subject=subject,
                message=body,
                html_message=self._html_wrap(body, event),
                from_email=from_email,
                recipient_list=[email],
                fail_silently=False,
            )
            logger.info("[EMAIL] Sent to %s | subject=%r | org=%s", email, subject, event.org_id)
            return ProviderResult(
                success=True,
                provider_msg_id=f"email-{event.id}",
                cost_minor=0,
                raw={"to": email, "subject": subject},
            )
        except Exception as e:
            logger.error("[EMAIL] Failed to send to %s: %s", email, e)
            return ProviderResult(
                success=False,
                error_code="SMTP_ERROR",
                error_message=str(e),
            )

    def _build_subject(self, event) -> str:
        invoice = event.invoice
        org_name = event.org.name if event.org else "CollectNaija"
        if invoice:
            return f"Payment Reminder: Invoice {invoice.invoice_number} from {org_name}"
        return f"Payment Reminder from {org_name}"

    def _html_wrap(self, body: str, event) -> str:
        """Wrap plain-text body in a simple branded HTML email."""
        org_name = event.org.name if event.org else "CollectNaija"
        pay_link = self._get_pay_link(event)
        lines = body.replace("\n", "<br>")
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><style>
body{{font-family:Inter,Arial,sans-serif;background:#f8fafc;margin:0;padding:0}}
.card{{background:#fff;max-width:560px;margin:32px auto;border-radius:16px;padding:32px;box-shadow:0 2px 16px rgba(0,0,0,.08)}}
.header{{color:#0f4c81;font-size:22px;font-weight:700;margin-bottom:16px}}
.body{{color:#334155;line-height:1.7;font-size:15px}}
.btn{{display:inline-block;background:#0f4c81;color:#fff;padding:12px 28px;border-radius:10px;text-decoration:none;font-weight:600;margin-top:20px}}
.footer{{color:#94a3b8;font-size:12px;margin-top:24px;text-align:center}}
</style></head>
<body>
<div class="card">
  <div class="header">Payment Reminder — {org_name}</div>
  <div class="body">{lines}</div>
  <a class="btn" href="{pay_link}">Pay Now</a>
  <div class="footer">This is an automated reminder from {org_name} via CollectNaija.<br>
  If you have already paid, please disregard this message.</div>
</div>
</body></html>"""

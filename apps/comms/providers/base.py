"""
base.py — Abstract provider interface for all comms channels.
Every provider (Africa's Talking, Twilio, Email, Mock) implements this.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    """Result returned from a provider send() call."""
    success: bool
    provider_msg_id: str = ""
    error_code: str = ""
    error_message: str = ""
    cost_minor: Optional[int] = None  # cost in kobo/smallest currency unit
    raw: dict = field(default_factory=dict)

    def __repr__(self):
        return f"<ProviderResult success={self.success} msg_id={self.provider_msg_id!r} err={self.error_code!r}>"


class BaseProvider(ABC):
    """Abstract base class for all communication providers."""

    channel: str = ""  # 'whatsapp', 'sms', 'email', 'voice'

    @abstractmethod
    def send(self, event) -> ProviderResult:
        """
        Send a CommunicationEvent.

        Args:
            event: CommunicationEvent model instance with all fields populated.

        Returns:
            ProviderResult indicating success or failure.
        """
        ...

    def test_connection(self) -> bool:
        """Optionally override to test provider connectivity."""
        return True

    def _render_template(self, event) -> str:
        """
        Render the event body using the invoice/customer template variables.
        Falls back to a sensible default message.

        §14: the amount is passed as a *number only*. Currency is supplied
        separately so the language template can localise it ("Naira"), rather
        than hard-coding "NGN" inside the figure. The Decimal is formatted
        directly — never via float() — so a balance can never be rounded.
        """
        from apps.languages.templates import render_template
        invoice = event.invoice
        customer = event.customer

        amount = self._format_amount(invoice.balance if invoice else None)
        ctx = {
            "customer_name": customer.name if customer else "Customer",
            "business_name": event.org.name if event.org else "Your business",
            "invoice_number": invoice.invoice_number if invoice else "N/A",
            "amount_due": amount,
            "amount_owed": amount,
            "currency": self._currency_label(invoice),
            "due_date": str(invoice.due_date) if invoice and invoice.due_date else "as agreed",
            "due_date_value": str(invoice.due_date) if invoice and invoice.due_date else "as agreed",
            "outstanding_balance": amount,
            "pay_link": self._get_pay_link(event),
        }

        # §21 — language precedence: explicit override, then customer
        # preference, then the org default. The resolved language is recorded
        # on the event so we can always prove what was sent.
        lang = self._resolve_language(event)

        # If a custom template is stored on the event, render its variables
        if event.template_id and "{{" in event.template_id:
            body = event.template_id
            for k, v in ctx.items():
                body = body.replace("{{" + k + "}}", str(v))
            return body

        # Otherwise use the language template system
        intent = "reminder"
        if invoice and invoice.status == "overdue":
            intent = "overdue"
        try:
            return render_template(intent, lang, ctx)
        except Exception:
            return (
                f"Hello {ctx['customer_name']}, this is a reminder from {ctx['business_name']}. "
                f"Invoice {ctx['invoice_number']} for {ctx['amount_due']} is due. "
                f"Pay here: {ctx['pay_link']}"
            )

    @staticmethod
    def _format_amount(balance) -> str:
        """
        Format a money Decimal without going through float().

        §14 — a balance of 85,000 must never render as 8,500 or 850,000.
        float() on a Decimal can lose precision on large balances and always
        adds a spurious ".00" for whole-naira amounts.
        """
        if balance is None:
            return "0"
        try:
            # Whole amounts render without decimals; kobo amounts keep them.
            value = (
                balance.quantize(Decimal("1"))
                if balance == balance.to_integral_value()
                else balance
            )
        except Exception:
            value = balance
        return f"{value:,}"

    def _currency_label(self, invoice) -> str:
        """Human currency name for the message (never a raw ISO code)."""
        code = str(getattr(invoice, "currency", None) or "NGN").upper()
        names = {"NGN": "Naira", "USD": "Dollar", "GHS": "Cedi", "KES": "Shilling"}
        return names.get(code, code)

    def _resolve_language(self, event) -> str:
        """
        Decide the message language (§21 / §5 precedence).

        Explicit event language > customer preference > org default > English.
        """
        # 1. Explicit override recorded on the event.
        override = getattr(event, "language", "") or ""
        if override and override != "auto":
            return override

        # 2. Customer's individual preference — the point of the product.
        customer = getattr(event, "customer", None)
        if customer is not None:
            pref = getattr(customer, "preferred_language", None)
            if pref is not None:
                code = getattr(pref, "code", None) or str(pref)
                if code:
                    return code

        # 3. Organisation default.
        org = getattr(event, "org", None)
        if org is not None:
            try:
                from apps.languages.models import OrganizationLanguageSettings
                s = OrganizationLanguageSettings.objects.filter(
                    org=org
                ).select_related("default_customer_language").first()
                if s and s.default_customer_language_id:
                    return s.default_customer_language_id
            except Exception:
                pass

        # 4. Safe fallback.
        return "en"

    def _get_pay_link(self, event) -> str:
        from django.conf import settings
        frontend_url = getattr(settings, "FRONTEND_URL", "https://collectnaija.com")
        if event.invoice:
            return f"{frontend_url}/pay/{event.invoice_id}"
        return frontend_url

    def _get_phone(self, event) -> str:
        """Get E.164 phone number for the customer."""
        customer = event.customer
        if not customer:
            return ""
        phone = getattr(customer, "phone", "") or ""
        # Normalize Nigerian numbers to +234
        phone = phone.strip().replace(" ", "").replace("-", "")
        if phone.startswith("0") and len(phone) == 11:
            phone = "+234" + phone[1:]
        elif phone.startswith("234") and not phone.startswith("+"):
            phone = "+" + phone
        return phone

    def _get_email(self, event) -> str:
        customer = event.customer
        if not customer:
            return ""
        return getattr(customer, "email", "") or ""

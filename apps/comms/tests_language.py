"""
Tests for the collection-message rendering path (§14, §21).

These guard the two rules that matter most when the system talks to someone
about money:

  §14  a balance is rendered exactly, never via float(), never with the
       currency code glued into the figure.
  §21  every customer is contacted in *their own* language, and the language
       used is recorded so it can be proven after the fact.
"""
import unittest
from decimal import Decimal

from apps.comms.providers.base import BaseProvider


class _FakeProvider(BaseProvider):
    """Concrete provider so we can exercise BaseProvider's rendering."""

    channel = "whatsapp"

    def send(self, event):  # pragma: no cover - not used
        raise NotImplementedError


class _Invoice:
    def __init__(self, balance, currency="NGN", status="sent", due_date=None):
        self.balance = balance
        self.currency = currency
        self.status = status
        self.invoice_number = "INV-1"
        self.due_date = due_date


class _Lang:
    def __init__(self, code):
        self.code = code


class _Customer:
    def __init__(self, name, preferred=None, voice=None):
        self.name = name
        self.phone = "+2348000000000"
        self.email = ""
        self.preferred_language = _Lang(preferred) if preferred else None
        self.voice_language = _Lang(voice) if voice else None


class _Org:
    def __init__(self, name="ABC School"):
        self.name = name


class _Event:
    """Stand-in for CommunicationEvent that avoids the Django ORM."""

    def __init__(self, customer=None, invoice=None, org=None, language="",
                 language_source="", template_id=""):
        self.customer = customer
        self.invoice = invoice
        self.org = org or _Org()
        self.invoice_id = "inv-uuid"
        self.template_id = template_id
        self.language = language
        self.language_source = language_source


class AmountFormattingTests(unittest.TestCase):
    """§14 — the figure must survive intact."""

    def setUp(self):
        self.p = _FakeProvider()

    def test_whole_amount_has_no_decimal_noise(self):
        self.assertEqual(self.p._format_amount(Decimal("85000")), "85,000")
        self.assertEqual(self.p._format_amount(Decimal("850000")), "850,000")
        self.assertEqual(self.p._format_amount(Decimal("0")), "0")

    def test_kobo_precision_is_preserved(self):
        self.assertEqual(self.p._format_amount(Decimal("85000.50")), "85,000.50")
        self.assertEqual(self.p._format_amount(Decimal("0.05")), "0.05")

    def test_spec_example_is_exact(self):
        """S14: 85,000 must never become 8,500 or 850,000."""
        out = self.p._format_amount(Decimal("85000"))
        self.assertEqual(out, "85,000")
        self.assertNotIn("8,500", out)
        self.assertNotIn("850,000", out)

    def test_large_balance_does_not_lose_precision(self):
        """float() on a large Decimal is where silent corruption starts."""
        big = Decimal("12345678901234.99")
        out = self.p._format_amount(big)
        self.assertIn("12,345,678,901,234", out)
        # float() would render 1.2345678901235e+13 here
        self.assertNotIn("e+", out)

    def test_none_balance_is_safe(self):
        self.assertEqual(self.p._format_amount(None), "0")

    def test_currency_is_a_name_not_an_iso_code(self):
        self.assertEqual(self.p._currency_label(_Invoice(Decimal("1"))), "Naira")
        self.assertEqual(self.p._currency_label(_Invoice(Decimal("1"), "USD")), "Dollar")


class RenderedMessageTests(unittest.TestCase):
    """End-to-end: the text a customer actually receives."""

    def setUp(self):
        self.p = _FakeProvider()

    def test_amount_appears_without_duplicated_currency(self):
        ev = _Event(
            customer=_Customer("Amina", preferred="ha"),
            invoice=_Invoice(Decimal("85000")),
        )
        body = self.p._render_template(ev)
        self.assertIn("85,000", body)
        # The ISO code must not be glued to the figure.
        self.assertNotIn("NGN", body)
        self.assertNotIn("85,000.00", body)

    def test_no_placeholder_survives_to_the_customer(self):
        for lang in ("en", "ha", "yo", "ig", "pcm"):
            with self.subTest(language=lang):
                ev = _Event(
                    customer=_Customer("Test", preferred=lang),
                    invoice=_Invoice(Decimal("85000")),
                )
                body = self.p._render_template(ev)
                self.assertNotIn("{{", body, f"{lang} message leaked a placeholder")
                self.assertNotIn("}}", body)

    def test_overdue_invoice_uses_overdue_template(self):
        ev = _Event(
            customer=_Customer("Amina", preferred="en"),
            invoice=_Invoice(Decimal("85000"), status="overdue"),
        )
        self.assertIn("85,000", self.p._render_template(ev))


class LanguageResolutionTests(unittest.TestCase):
    """S21 / S5 precedence."""

    def setUp(self):
        self.p = _FakeProvider()

    def test_customer_preference_is_used(self):
        ev = _Event(customer=_Customer("Amina", preferred="yo"))
        self.assertEqual(self.p._resolve_language(ev), "yo")

    def test_explicit_event_language_overrides_preference(self):
        ev = _Event(customer=_Customer("Amina", preferred="yo"), language="ig")
        self.assertEqual(self.p._resolve_language(ev), "ig")

    def test_auto_means_use_preference_not_force_auto(self):
        ev = _Event(customer=_Customer("Amina", preferred="ha"), language="auto")
        self.assertEqual(self.p._resolve_language(ev), "ha")

    def test_missing_preference_falls_back_safely(self):
        ev = _Event(customer=_Customer("John"))
        self.assertEqual(self.p._resolve_language(ev), "en")

    def test_two_customers_get_different_languages(self):
        """S21: one business, many customers, many languages."""
        a = _Event(customer=_Customer("Aisha", preferred="ha"),
                   invoice=_Invoice(Decimal("50000")))
        b = _Event(customer=_Customer("Chinedu", preferred="ig"),
                   invoice=_Invoice(Decimal("50000")))
        c = _Event(customer=_Customer("Tunde", preferred="yo"),
                   invoice=_Invoice(Decimal("50000")))
        langs = {self.p._resolve_language(e) for e in (a, b, c)}
        self.assertEqual(langs, {"ha", "ig", "yo"})
        # And the rendered text actually differs.
        bodies = {self.p._render_template(e) for e in (a, b, c)}
        self.assertEqual(len(bodies), 3, "customers in different languages got identical text")

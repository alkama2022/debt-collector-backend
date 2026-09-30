"""
tests.py — Comms dispatch, idempotency, and opt-out tests.
"""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.tenancy.models import Organization, Membership
from apps.customers.models import Customer
from apps.invoices.models import Invoice
from apps.comms.models import CommunicationEvent, CommunicationPreference, ReminderRule

User = get_user_model()


def _setup_comms():
    user = User.objects.create_user(email="comms@test.com", password="pass1234", name="Comms Tester")
    org = Organization.objects.create(name="CommsOrg", slug="commsorg", timezone="Africa/Lagos")
    Membership.objects.create(user=user, org=org, role="owner")
    customer = Customer.objects.create(
        org=org, name="Fatima", phone="+2348099999999",
        email="fatima@test.com", customer_code="C-FAT",
    )
    invoice = Invoice(
        org=org, customer=customer, invoice_number="INV-COMMS-001",
        status=Invoice.Status.SENT,
        subtotal=Decimal("20000"), discount=Decimal("0"),
        tax=Decimal("0"), total=Decimal("20000"), balance=Decimal("20000"),
        currency="NGN",
        due_date=timezone.now().date(),
    )
    invoice.save()
    return org, user, customer, invoice


class MockProviderDispatchTests(TestCase):
    """Test that dispatch_queued_events correctly processes events using MockProvider."""

    def setUp(self):
        self.org, self.user, self.customer, self.invoice = _setup_comms()

    def _make_event(self, channel="whatsapp", status="queued", idem_key=None):
        return CommunicationEvent.objects.create(
            org=self.org,
            invoice=self.invoice,
            customer=self.customer,
            channel=channel,
            status=status,
            scheduled_for=timezone.now(),
            template_id="Hello {{customer_name}}, your invoice {{invoice_number}} is due.",
            idempotency_key=idem_key or f"test-{channel}-{timezone.now().timestamp()}",
        )

    def test_queued_event_becomes_sent_via_mock(self):
        """A queued event should be marked sent by the dispatcher (mock mode)."""
        ev = self._make_event()
        from apps.comms.tasks import dispatch_queued_events
        dispatch_queued_events()
        ev.refresh_from_db()
        self.assertEqual(ev.status, CommunicationEvent.Status.SENT)
        self.assertTrue(ev.provider_msg_id.startswith("mock-"))

    def test_dispatch_does_not_double_send(self):
        """Running dispatch twice should not re-send already sent events."""
        ev = self._make_event()
        from apps.comms.tasks import dispatch_queued_events
        dispatch_queued_events()
        dispatch_queued_events()
        ev.refresh_from_db()
        # Still sent, not duplicated
        self.assertEqual(ev.status, CommunicationEvent.Status.SENT)

    def test_paid_invoice_cancels_event_during_dispatch(self):
        """If invoice is fully paid before dispatch, event should be cancelled."""
        self.invoice.balance = Decimal("0")
        self.invoice.save(update_fields=["balance"])

        ev = self._make_event()
        from apps.comms.tasks import dispatch_queued_events
        dispatch_queued_events()
        ev.refresh_from_db()
        self.assertEqual(ev.status, CommunicationEvent.Status.CANCELLED)

    def test_opted_out_customer_skipped(self):
        """Customer who opted out should not receive a message."""
        CommunicationPreference.objects.create(
            org=self.org,
            customer=self.customer,
            channel="whatsapp",
            enabled=False,
            opted_out_at=timezone.now(),
        )
        ev = self._make_event(channel="whatsapp")
        from apps.comms.tasks import dispatch_queued_events
        dispatch_queued_events()
        ev.refresh_from_db()
        self.assertEqual(ev.status, CommunicationEvent.Status.CANCELLED)

    def test_email_event_dispatched(self):
        """Email channel events should also be dispatched via MockProvider."""
        ev = self._make_event(channel="email")
        from apps.comms.tasks import dispatch_queued_events
        dispatch_queued_events()
        ev.refresh_from_db()
        self.assertEqual(ev.status, CommunicationEvent.Status.SENT)


class EnqueueRemindersTests(TestCase):
    """Test that enqueue_due_reminders creates events correctly from ReminderRules."""

    def setUp(self):
        self.org, self.user, self.customer, self.invoice = _setup_comms()

    @patch("apps.collections.tasks._is_quiet_hours", return_value=False)
    def test_on_due_rule_creates_event_for_due_today(self, _mock_qh):
        """A rule with trigger=on_due should create an event for invoice due today."""
        ReminderRule.objects.create(
            org=self.org,
            name="Due today reminder",
            trigger=ReminderRule.Trigger.ON_DUE,
            offset_days=0,
            channel="whatsapp",
            enabled=True,
        )
        from apps.collections.tasks import enqueue_due_reminders
        count = enqueue_due_reminders()
        self.assertGreater(count, 0)
        self.assertTrue(
            CommunicationEvent.objects.filter(
                org=self.org, invoice=self.invoice, status="queued"
            ).exists()
        )

    @patch("apps.collections.tasks._is_quiet_hours", return_value=False)
    def test_idempotency_prevents_duplicate_events(self, _mock_qh):
        """Running enqueue twice on the same day should not create duplicate events."""
        ReminderRule.objects.create(
            org=self.org,
            name="Dupe test",
            trigger=ReminderRule.Trigger.ON_DUE,
            offset_days=0,
            channel="sms",
            enabled=True,
        )
        from apps.collections.tasks import enqueue_due_reminders
        enqueue_due_reminders()
        enqueue_due_reminders()

        count = CommunicationEvent.objects.filter(
            org=self.org, invoice=self.invoice, channel="sms"
        ).count()
        self.assertEqual(count, 1)  # Only one, not two

    @patch("apps.collections.tasks._is_quiet_hours", return_value=False)
    def test_disabled_rule_skipped(self, _mock_qh):
        """Disabled ReminderRules should not create events."""
        ReminderRule.objects.create(
            org=self.org,
            name="Disabled",
            trigger=ReminderRule.Trigger.ON_DUE,
            offset_days=0,
            channel="email",
            enabled=False,
        )
        from apps.collections.tasks import enqueue_due_reminders
        enqueue_due_reminders()
        self.assertFalse(
            CommunicationEvent.objects.filter(org=self.org, channel="email").exists()
        )

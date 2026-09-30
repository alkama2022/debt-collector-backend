"""
Locust performance test for CollectNaija backend.

Simulates realistic multi-tenant SaaS traffic across all major endpoints:
  - Authentication (login, token refresh, profile)
  - Customer management (CRUD, bulk import, language)
  - Invoices (CRUD, PDF generation, pay links)
  - Collections (campaigns, policy, stats)
  - Communications (events, reminder rules)
  - Reports (summary, CSV/PDF export)
  - Billing & subscriptions (plans, entitlements, usage)
  - Audit logs

Usage:
  locust -f locustfiles/browse.py --host http://localhost:8000
  locust -f locustfiles/browse.py --host http://localhost:8000 -u 50 -r 10 -t 5m
"""

import random
import uuid
from datetime import date, timedelta

from locust import HttpUser, between, task, tag, events
from locust.runners import MasterRunner


# ──────────────────────────────────────────────────────────────────────────────
# Test data constants
# ──────────────────────────────────────────────────────────────────────────────

SEED_ORG_ID = "demo-workspace"  # slug, resolved to UUID at runtime
SEED_USERS = [
    {"email": "owner@collectnaija.test", "password": "Test12345!"},
    {"email": "ade@collectnaija.demo", "password": "demo1234"},
]

CUSTOMER_NAMES = [
    "Ahmed Bello", "Mama Emeka Stores", "Tolu Collections", "Chidi Okafor",
    "Ngozi Eze", "Ibrahim Musa", "Blessing Adeyemi", "Kunle Balogun",
    "Fatima Abubakar", "Emeka Nwosu", "Yakubu Danladi", "Amina Yusuf",
    "Oluwaseun Ade", "Nkechi Obi", "Tunde Alabi", "Rukayat Suleiman",
]

INVOICE_STATUSES = ["draft", "sent", "partial", "paid", "overdue", "cancelled"]
CURRENCIES = ["NGN", "USD", "GHS", "KES"]
CHANNELS = ["whatsapp", "sms", "email", "voice"]
LANGUAGES = ["en", "yo", "ig", "ha", "pcm"]


# ──────────────────────────────────────────────────────────────────────────────
# Helper: authenticated user base
# ──────────────────────────────────────────────────────────────────────────────

class AuthenticatedUser(HttpUser):
    """Base user that handles JWT auth and org resolution."""

    abstract = True
    wait_time = between(1, 3)

    def on_start(self):
        """Login and set up auth headers."""
        self.org_id = None
        self.access_token = None
        self.refresh_token = None
        self.customer_ids = []
        self.invoice_ids = []
        self.campaign_ids = []

        # Pick a random seed user
        creds = random.choice(SEED_USERS)
        self.login(creds["email"], creds["password"])

    def login(self, email: str, password: str):
        """Authenticate and store tokens."""
        with self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            name="auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                self.access_token = data.get("access")
                self.refresh_token = data.get("refresh")
                # Extract org ID from user payload
                user = data.get("user", {})
                org = user.get("org")
                if org:
                    self.org_id = org.get("id")
                resp.success()
            else:
                resp.failure(f"Login failed: {resp.status_code} {resp.text[:200]}")

    def refresh_access_token(self):
        """Refresh the JWT access token."""
        if not self.refresh_token:
            return
        with self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh": self.refresh_token},
            name="auth/refresh",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self.access_token = resp.json().get("access")
                resp.success()
            else:
                # Token expired — re-login
                creds = random.choice(SEED_USERS)
                self.login(creds["email"], creds["password"])

    def _headers(self) -> dict:
        """Build request headers with auth + org context."""
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.org_id:
            headers["X-Org-Id"] = self.org_id
        return headers

    def _get(self, path: str, name: str = None, **kwargs):
        """Authenticated GET with auto-refresh on 401."""
        with self.client.get(
            path, headers=self._headers(), name=name or path, catch_response=True, **kwargs
        ) as resp:
            if resp.status_code == 401:
                self.refresh_access_token()
                # Retry once
                with self.client.get(
                    path, headers=self._headers(), name=name or path, catch_response=True, **kwargs
                ) as resp2:
                    if resp2.status_code != 200:
                        resp2.failure(f"GET {path} failed: {resp2.status_code}")
                    else:
                        resp2.success()
                    return resp2
            elif resp.status_code != 200:
                resp.failure(f"GET {path} failed: {resp.status_code}")
            else:
                resp.success()
            return resp

    def _post(self, path: str, json_data: dict = None, name: str = None, **kwargs):
        """Authenticated POST with auto-refresh on 401."""
        with self.client.post(
            path, json=json_data or {}, headers=self._headers(), name=name or path, catch_response=True, **kwargs
        ) as resp:
            if resp.status_code == 401:
                self.refresh_access_token()
                with self.client.post(
                    path, json=json_data or {}, headers=self._headers(), name=name or path, catch_response=True, **kwargs
                ) as resp2:
                    if resp2.status_code not in (200, 201):
                        resp2.failure(f"POST {path} failed: {resp2.status_code}")
                    else:
                        resp2.success()
                    return resp2
            elif resp.status_code not in (200, 201):
                resp.failure(f"POST {path} failed: {resp.status_code}")
            else:
                resp.success()
            return resp

    def _patch(self, path: str, json_data: dict = None, name: str = None, **kwargs):
        """Authenticated PATCH with auto-refresh on 401."""
        with self.client.patch(
            path, json=json_data or {}, headers=self._headers(), name=name or path, catch_response=True, **kwargs
        ) as resp:
            if resp.status_code == 401:
                self.refresh_access_token()
                with self.client.patch(
                    path, json=json_data or {}, headers=self._headers(), name=name or path, catch_response=True, **kwargs
                ) as resp2:
                    if resp2.status_code != 200:
                        resp2.failure(f"PATCH {path} failed: {resp2.status_code}")
                    else:
                        resp2.success()
                    return resp2
            elif resp.status_code != 200:
                resp.failure(f"PATCH {path} failed: {resp.status_code}")
            else:
                resp.success()
            return resp

    def _delete(self, path: str, name: str = None, **kwargs):
        """Authenticated DELETE with auto-refresh on 401."""
        with self.client.delete(
            path, headers=self._headers(), name=name or path, catch_response=True, **kwargs
        ) as resp:
            if resp.status_code == 401:
                self.refresh_access_token()
                with self.client.delete(
                    path, headers=self._headers(), name=name or path, catch_response=True, **kwargs
                ) as resp2:
                    if resp2.status_code not in (200, 204):
                        resp2.failure(f"DELETE {path} failed: {resp2.status_code}")
                    else:
                        resp2.success()
                    return resp2
            elif resp.status_code not in (200, 204):
                resp.failure(f"DELETE {path} failed: {resp.status_code}")
            else:
                resp.success()
            return resp


# ──────────────────────────────────────────────────────────────────────────────
# Main user: realistic SaaS dashboard traffic
# ──────────────────────────────────────────────────────────────────────────────

class DashboardUser(AuthenticatedUser):
    """
    Simulates a logged-in user performing typical dashboard operations.
    Weighted toward reads (80/20) to match real SaaS usage patterns.
    """

    weight = 10

    # ── Auth ──────────────────────────────────────────────────────────────────

    @task(2)
    def get_profile(self):
        """GET /api/v1/auth/me — load user profile."""
        self._get("/api/v1/auth/me", name="auth/me")

    # ── Customers ─────────────────────────────────────────────────────────────

    @task(10)
    def list_customers(self):
        """GET /api/v1/customers — list with pagination."""
        page = random.randint(1, 5)
        self._get(f"/api/v1/customers?page={page}", name="customers/list")

    @task(5)
    def search_customers(self):
        """GET /api/v1/customers?search= — search by name/phone."""
        term = random.choice(["Ahmed", "Mama", "Tolu", "Chidi", "080", "test"])
        self._get(f"/api/v1/customers?search={term}", name="customers/search")

    @task(3)
    def get_customer_detail(self):
        """GET /api/v1/customers/<id> — view customer profile."""
        if self.customer_ids:
            cid = random.choice(self.customer_ids)
            self._get(f"/api/v1/customers/{cid}", name="customers/detail")
        else:
            # Fetch list first
            resp = self._get("/api/v1/customers?page=1", name="customers/list-for-detail")
            try:
                data = resp.json().get("data", {})
                results = data.get("results", data) if isinstance(data, dict) else data
                if isinstance(results, list) and results:
                    self.customer_ids = [c["id"] for c in results[:10]]
            except Exception:
                pass

    @task(2)
    def create_customer(self):
        """POST /api/v1/customers — create a new customer."""
        name = random.choice(CUSTOMER_NAMES)
        phone = f"080{random.randint(10000000, 99999999)}"
        payload = {
            "name": f"{name} {uuid.uuid4().hex[:4]}",
            "phone": phone,
            "email": f"cust_{uuid.uuid4().hex[:6]}@test.com",
            "preferred_language": random.choice(LANGUAGES),
        }
        resp = self._post("/api/v1/customers", json_data=payload, name="customers/create")
        try:
            cid = resp.json().get("data", {}).get("id")
            if cid:
                self.customer_ids.append(cid)
        except Exception:
            pass

    @task(1)
    def bulk_create_customers(self):
        """POST /api/v1/customers/bulk — bulk import customers."""
        rows = []
        for _ in range(random.randint(5, 20)):
            rows.append({
                "name": f"{random.choice(CUSTOMER_NAMES)} {uuid.uuid4().hex[:4]}",
                "phone": f"080{random.randint(10000000, 99999999)}",
                "email": f"bulk_{uuid.uuid4().hex[:6]}@test.com",
                "preferred_language": random.choice(LANGUAGES),
            })
        self._post("/api/v1/customers/bulk", json_data={"customers": rows}, name="customers/bulk")

    @task(2)
    def update_customer_language(self):
        """PATCH /api/v1/customers/<id>/language — change language preference."""
        if self.customer_ids:
            cid = random.choice(self.customer_ids)
            self._patch(
                f"/api/v1/customers/{cid}/language",
                json_data={"preferred_language": random.choice(LANGUAGES)},
                name="customers/language",
            )

    # ── Invoices ──────────────────────────────────────────────────────────────

    @task(10)
    def list_invoices(self):
        """GET /api/v1/invoices — list with filters."""
        status = random.choice(INVOICE_STATUSES + [""])
        page = random.randint(1, 5)
        path = f"/api/v1/invoices?page={page}"
        if status:
            path += f"&status={status}"
        self._get(path, name="invoices/list")

    @task(5)
    def get_invoice_detail(self):
        """GET /api/v1/invoices/<id> — view invoice."""
        if self.invoice_ids:
            iid = random.choice(self.invoice_ids)
            self._get(f"/api/v1/invoices/{iid}", name="invoices/detail")
        else:
            resp = self._get("/api/v1/invoices?page=1", name="invoices/list-for-detail")
            try:
                data = resp.json().get("data", {})
                results = data.get("results", data) if isinstance(data, dict) else data
                if isinstance(results, list) and results:
                    self.invoice_ids = [inv["id"] for inv in results[:10]]
            except Exception:
                pass

    @task(3)
    def create_invoice(self):
        """POST /api/v1/invoices — create invoice with items."""
        if not self.customer_ids:
            resp = self._get("/api/v1/customers?page=1", name="customers/list-for-invoice")
            try:
                data = resp.json().get("data", {})
                results = data.get("results", data) if isinstance(data, dict) else data
                if isinstance(results, list) and results:
                    self.customer_ids = [c["id"] for c in results[:5]]
            except Exception:
                return

        if not self.customer_ids:
            return

        customer_id = random.choice(self.customer_ids)
        items = []
        for _ in range(random.randint(1, 5)):
            qty = random.randint(1, 10)
            unit_price = random.randint(1000, 500000)
            items.append({
                "name": f"Service {uuid.uuid4().hex[:6]}",
                "qty": qty,
                "unit_price_minor": unit_price,
            })

        subtotal = sum(i["qty"] * i["unit_price_minor"] / 100 for i in items)
        payload = {
            "customer": customer_id,
            "status": random.choice(["draft", "sent"]),
            "due_date": str(date.today() + timedelta(days=random.randint(7, 60))),
            "currency": random.choice(CURRENCIES),
            "items": items,
            "subtotal": str(subtotal),
            "discount": "0.00",
            "tax": "0.00",
            "total": str(subtotal),
            "balance": str(subtotal),
        }
        resp = self._post("/api/v1/invoices", json_data=payload, name="invoices/create")
        try:
            iid = resp.json().get("data", {}).get("id")
            if iid:
                self.invoice_ids.append(iid)
        except Exception:
            pass

    @task(2)
    def get_invoice_pdf(self):
        """GET /api/v1/invoices/<id>/pdf — generate PDF."""
        if self.invoice_ids:
            iid = random.choice(self.invoice_ids)
            self._get(f"/api/v1/invoices/{iid}/pdf", name="invoices/pdf")

    @task(2)
    def get_invoice_pay_link(self):
        """GET /api/v1/invoices/<id>/pay-link — get payment link."""
        if self.invoice_ids:
            iid = random.choice(self.invoice_ids)
            self._get(f"/api/v1/invoices/{iid}/pay-link", name="invoices/pay-link")

    # ── Collections ───────────────────────────────────────────────────────────

    @task(3)
    def get_collection_policy(self):
        """GET /api/v1/collections/policy — view collection policy."""
        self._get("/api/v1/collections/policy", name="collections/policy")

    @task(5)
    def list_campaigns(self):
        """GET /api/v1/collections/campaigns — list campaigns."""
        self._get("/api/v1/collections/campaigns", name="campaigns/list")

    @task(2)
    def create_campaign(self):
        """POST /api/v1/collections/campaigns — create a campaign."""
        payload = {
            "name": f"Campaign {uuid.uuid4().hex[:6]}",
            "status": "draft",
            "description": "Load test campaign",
            "config": {
                "channel": random.choice(CHANNELS),
                "template": "Hello {{customer_name}}, reminder about invoice {{invoice_number}}",
            },
        }
        resp = self._post("/api/v1/collections/campaigns", json_data=payload, name="campaigns/create")
        try:
            cid = resp.json().get("data", {}).get("id")
            if cid:
                self.campaign_ids.append(cid)
        except Exception:
            pass

    @task(2)
    def get_campaign_stats(self):
        """GET /api/v1/collections/campaigns/<id>/stats — campaign stats."""
        if self.campaign_ids:
            cid = random.choice(self.campaign_ids)
            self._get(f"/api/v1/collections/campaigns/{cid}/stats", name="campaigns/stats")

    # ── Communications ────────────────────────────────────────────────────────

    @task(5)
    def list_comm_events(self):
        """GET /api/v1/comms/events — list communication events."""
        self._get("/api/v1/comms/events?page=1", name="comms/events")

    @task(3)
    def list_reminder_rules(self):
        """GET /api/v1/comms/rules — list reminder rules."""
        self._get("/api/v1/comms/rules", name="comms/rules")

    @task(2)
    def create_comm_event(self):
        """POST /api/v1/comms/events — create communication event."""
        if not self.customer_ids or not self.invoice_ids:
            return
        payload = {
            "customer": random.choice(self.customer_ids),
            "invoice": random.choice(self.invoice_ids),
            "channel": random.choice(CHANNELS),
            "template_id": f"tpl_{uuid.uuid4().hex[:6]}",
            "status": "queued",
        }
        self._post("/api/v1/comms/events", json_data=payload, name="comms/events/create")

    # ── Reports ───────────────────────────────────────────────────────────────

    @task(5)
    def get_reports_summary(self):
        """GET /api/v1/reports/summary — dashboard KPIs."""
        range_days = random.choice([7, 30, 90])
        self._get(f"/api/v1/reports/summary?range={range_days}", name="reports/summary")

    @task(2)
    def export_reports_csv(self):
        """GET /api/v1/reports/export?format=csv — CSV export."""
        range_days = random.choice([30, 90])
        self._get(f"/api/v1/reports/export?format=csv&range={range_days}", name="reports/export-csv")

    @task(1)
    def export_reports_pdf(self):
        """GET /api/v1/reports/export?format=pdf — PDF export."""
        range_days = random.choice([30, 90])
        self._get(f"/api/v1/reports/export?format=pdf&range={range_days}", name="reports/export-pdf")

    # ── Billing & Subscriptions ───────────────────────────────────────────────

    @task(3)
    def get_subscription(self):
        """GET /api/v1/subscriptions/me — current subscription."""
        self._get("/api/v1/subscriptions/me", name="billing/subscription")

    @task(3)
    def get_entitlements(self):
        """GET /api/v1/billing/entitlements — feature entitlements."""
        self._get("/api/v1/billing/entitlements", name="billing/entitlements")

    @task(2)
    def get_usage_summary(self):
        """GET /api/v1/billing/usage — usage summary."""
        self._get("/api/v1/billing/usage", name="billing/usage")

    @task(2)
    def list_plans(self):
        """GET /api/v1/billing/plans — list billing plans."""
        self._get("/api/v1/billing/plans", name="billing/plans")

    @task(1)
    def check_feature(self):
        """GET /api/v1/billing/check-feature — check feature access."""
        feature = random.choice([
            "WHATSAPP_REMINDERS", "SMS_REMINDERS", "EMAIL_REMINDERS",
            "AI_VOICE", "AI_CONVERSATIONS", "AI_MULTILINGUAL",
            "COLLECTION_CAMPAIGNS",
        ])
        self._get(f"/api/v1/billing/check-feature?feature={feature}", name="billing/check-feature")

    @task(1)
    def record_usage(self):
        """POST /api/v1/billing/usage/record — record usage event."""
        payload = {
            "feature": random.choice(["AI_VOICE", "AI_CONVERSATIONS", "WHATSAPP_MESSAGE", "SMS_MESSAGE"]),
            "quantity": random.randint(1, 10),
            "unit": "message",
        }
        self._post("/api/v1/billing/usage/record", json_data=payload, name="billing/usage-record")

    # ── Audit ─────────────────────────────────────────────────────────────────

    @task(2)
    def list_audit_logs(self):
        """GET /api/v1/audit/logs — list audit logs."""
        self._get("/api/v1/audit/logs?page=1", name="audit/logs")

    @task(1)
    def list_ai_audit(self):
        """GET /api/v1/audit/ai-communications — AI comm audit trail."""
        self._get("/api/v1/audit/ai-communications?page=1", name="audit/ai-comms")


# ──────────────────────────────────────────────────────────────────────────────
# Public user: unauthenticated traffic (public pay pages, webhooks)
# ──────────────────────────────────────────────────────────────────────────────

class PublicUser(HttpUser):
    """
    Simulates unauthenticated traffic: public payment pages, webhooks.
    No auth required — tests the public-facing endpoints.
    """

    weight = 3
    wait_time = between(2, 5)

    def on_start(self):
        """Fetch a list of invoice IDs for public endpoints."""
        self.invoice_ids = []
        # We need at least one invoice ID — fetch from a known seed
        # The public endpoint doesn't need auth, but we need a valid UUID
        # We'll try to get one from the database via a simple approach
        # For now, we'll use a placeholder that will 404 gracefully
        self.invoice_ids = []

    @task(5)
    def public_pay_info(self):
        """GET /api/v1/public/pay/<id> — public payment info page."""
        # Use a random UUID — will 404 if not found, which is fine for load testing
        # the endpoint's error handling
        fake_id = str(uuid.uuid4())
        self.client.get(
            f"/api/v1/public/pay/{fake_id}",
            name="public/pay-info",
        )

    @task(2)
    def public_pay_initialize(self):
        """POST /api/v1/public/pay/<id>/initialize — initialize payment."""
        fake_id = str(uuid.uuid4())
        self.client.post(
            f"/api/v1/public/pay/{fake_id}/initialize",
            json={"email": "customer@test.com"},
            name="public/pay-initialize",
        )

    @task(1)
    def webhook_payment(self):
        """POST /api/v1/webhooks/payments/<provider> — payment webhook."""
        payload = {
            "event": "charge.success",
            "data": {
                "reference": f"ref_{uuid.uuid4().hex[:12]}",
                "status": "success",
                "amount": 500000,
                "currency": "NGN",
            },
        }
        self.client.post(
            "/api/v1/webhooks/payments/paystack",
            json=payload,
            name="webhooks/payments",
        )

    @task(1)
    def webhook_at_delivery(self):
        """POST /api/v1/webhooks/at/delivery — Africa's Talking delivery receipt."""
        payload = {
            "id": str(uuid.uuid4()),
            "status": "Delivered",
            "phoneNumber": "+2348012345678",
        }
        self.client.post(
            "/api/v1/webhooks/at/delivery",
            json=payload,
            name="webhooks/at-delivery",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Stress user: heavy write operations (for stress testing)
# ──────────────────────────────────────────────────────────────────────────────

class StressUser(AuthenticatedUser):
    """
    High-intensity user for stress testing.
    Focuses on write-heavy operations and bulk endpoints.
    """

    weight = 1
    wait_time = between(0.5, 1.5)

    @task(5)
    def bulk_customer_creation(self):
        """POST /api/v1/customers/bulk — heavy bulk import."""
        rows = []
        for _ in range(random.randint(50, 200)):
            rows.append({
                "name": f"{random.choice(CUSTOMER_NAMES)} {uuid.uuid4().hex[:6]}",
                "phone": f"080{random.randint(10000000, 99999999)}",
                "email": f"stress_{uuid.uuid4().hex[:8]}@test.com",
                "preferred_language": random.choice(LANGUAGES),
            })
        self._post("/api/v1/customers/bulk", json_data={"customers": rows}, name="stress/bulk-customers")

    @task(3)
    def bulk_invoice_creation(self):
        """POST /api/v1/invoices — create many invoices rapidly."""
        if not self.customer_ids:
            resp = self._get("/api/v1/customers?page=1", name="customers/list-for-stress")
            try:
                data = resp.json().get("data", {})
                results = data.get("results", data) if isinstance(data, dict) else data
                if isinstance(results, list) and results:
                    self.customer_ids = [c["id"] for c in results[:10]]
            except Exception:
                return

        if not self.customer_ids:
            return

        customer_id = random.choice(self.customer_ids)
        items = []
        for _ in range(random.randint(3, 10)):
            items.append({
                "name": f"Item {uuid.uuid4().hex[:6]}",
                "qty": random.randint(1, 20),
                "unit_price_minor": random.randint(500, 100000),
            })
        subtotal = sum(i["qty"] * i["unit_price_minor"] / 100 for i in items)
        payload = {
            "customer": customer_id,
            "status": "draft",
            "due_date": str(date.today() + timedelta(days=30)),
            "currency": "NGN",
            "items": items,
            "subtotal": str(subtotal),
            "discount": "0.00",
            "tax": "0.00",
            "total": str(subtotal),
            "balance": str(subtotal),
        }
        self._post("/api/v1/invoices", json_data=payload, name="stress/create-invoice")

    @task(2)
    def launch_campaign(self):
        """POST /api/v1/collections/campaigns/<id>/launch — launch campaign."""
        # First create a campaign
        resp = self._post(
            "/api/v1/collections/campaigns",
            json_data={
                "name": f"Stress Campaign {uuid.uuid4().hex[:6]}",
                "status": "draft",
                "config": {"channel": "whatsapp", "template": "test"},
            },
            name="stress/create-campaign",
        )
        try:
            cid = resp.json().get("data", {}).get("id")
            if cid:
                self._post(f"/api/v1/collections/campaigns/{cid}/launch", json_data={}, name="stress/launch-campaign")
        except Exception:
            pass

    @task(2)
    def run_reminder_rules(self):
        """POST /api/v1/comms/rules/run-all — run all reminder rules."""
        self._post("/api/v1/comms/rules/run-all", json_data={}, name="stress/run-reminders")


# ──────────────────────────────────────────────────────────────────────────────
# Event hooks for custom metrics
# ──────────────────────────────────────────────────────────────────────────────

@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Log slow requests for analysis."""
    if response_time > 2000:  # Log requests slower than 2 seconds
        print(f"[SLOW] {request_type} {name} took {response_time:.0f}ms")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary when test ends."""
    print("\n" + "=" * 60)
    print("Load test completed")
    print("=" * 60)
    if isinstance(environment.runner, MasterRunner):
        print("Running in master mode")
    else:
        stats = environment.runner.stats
        print(f"Total requests: {stats.total.num_requests}")
        print(f"Failed requests: {stats.total.num_failures}")
        print(f"Average response time: {stats.total.avg_response_time:.1f}ms")
        print(f"95th percentile: {stats.total.get_response_time_percentile(0.95):.1f}ms")

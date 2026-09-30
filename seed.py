"""
Seed demo workspace for CollectNaija — run: python backend/seed.py
Creates org, users, customers, invoices, payments per README.
"""
import os, sys, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
django.setup()

from decimal import Decimal
from django.contrib.auth import get_user_model
from apps.tenancy.models import Organization, Membership
from apps.customers.models import Customer
from apps.invoices.models import Invoice, InvoiceItem

User = get_user_model()

def run():
    # Clean idempotency for rerun
    org, _ = Organization.objects.get_or_create(slug="demo-workspace", defaults={"name":"Demo Workspace","is_demo":True})
    for email, pwd, name in [("owner@collectnaija.test","Test12345!","Test Owner"), ("ade@collectnaija.demo","demo1234","Ade Demo")]:
        u, _ = User.objects.get_or_create(email=email, defaults={"name": name})
        u.set_password(pwd)
        u.is_active = True
        u.save()
        Membership.objects.get_or_create(org=org, user=u, defaults={"role":"owner"})
        print(f"Org {org.id} User {email} / {pwd}")

    # Customers
    customers = []
    data = [
        ("Ahmed Bello", "08011112222", "ahmed@test.com"),
        ("Mama Emeka Stores", "08033334444", "emeka@test.com"),
        ("Tolu Collections", "08055556666", "tolu@test.com"),
    ]
    for name, phone, email in data:
        c, created = Customer.objects.get_or_create(org=org, customer_code=f"CUS-{name[:3].upper()}", defaults={"name":name,"phone":phone,"email":email})
        if created:
            print(f"Created customer {c.name}")
        customers.append(c)

    # Invoices
    if not Invoice.objects.filter(org=org).exists():
        for i, c in enumerate(customers):
            inv = Invoice.objects.create(
                org=org, customer=c, invoice_number=f"INV-2026-00{i+1}", due_date="2026-10-05",
                subtotal=Decimal("85000.00"), discount=Decimal("0.00"), tax=Decimal("0.00"),
                total=Decimal("85000.00"), balance=Decimal("85000.00"), currency="NGN", status="sent"
            )
            InvoiceItem.objects.create(invoice=inv, name="Term fee", qty=Decimal("1"), unit_price_minor=8500000, line_total=Decimal("85000.00"))
            print(f"Invoice {inv.invoice_number} -> {c.name} balance {inv.balance}")

if __name__ == "__main__":
    run()

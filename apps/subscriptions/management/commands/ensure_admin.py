from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure a superuser exists and is linked to an enterprise-plan org (idempotent)."

    def handle(self, *args, **options):
        from apps.accounts.models import User
        from apps.tenancy.models import Organization, Membership
        from apps.subscriptions.models import Plan, Subscription
        import os

        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@collectnaija.com")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        u, _ = User.objects.get_or_create(
            email=email, defaults={"name": "Admin", "is_staff": True, "is_superuser": True, "is_active": True}
        )
        u.is_staff = True
        u.is_superuser = True
        if password:
            u.set_password(password)
        u.save()

        org, _ = Organization.objects.get_or_create(slug="admin-org", defaults={"name": "Admin Org"})
        Membership.objects.get_or_create(org=org, user=u, defaults={"role": "owner"})

        plan = Plan.objects.filter(slug="enterprise").first()
        sub, _ = Subscription.objects.get_or_create(org=org, defaults={"plan": "enterprise", "status": "active"})
        sub.plan = "enterprise"
        sub.plan_obj = plan
        sub.status = "active"
        sub.save(update_fields=["plan", "plan_obj", "status"])

        self.stdout.write(self.style.SUCCESS(f"Superuser {email} ready (org={org.slug}, plan=enterprise)"))

import uuid
from django.db import models
from django.conf import settings

class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True, max_length=64)
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=64, default="NG")
    currency = models.CharField(max_length=3, default="NGN")
    timezone = models.CharField(max_length=64, default="Africa/Lagos")
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "organizations"

    def __str__(self):
        return self.name

class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        READONLY = "readonly", "Read-only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "memberships"
        unique_together = ("org", "user")

class TenantManager(models.Manager):
    def for_org(self, org):
        if org is None:
            raise ValueError("org is required for tenant-scoped query")
        org_id = org.id if hasattr(org, "id") else org
        return self.get_queryset().filter(org_id=org_id)

class TenantModel(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.RESTRICT, related_name="%(class)s_set")
    class Meta:
        abstract = True
    objects = TenantManager()

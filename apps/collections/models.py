import uuid
from django.db import models
from apps.tenancy.models import TenantManager

class CollectionPolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.OneToOneField("tenancy.Organization", on_delete=models.CASCADE, related_name="collection_policy")
    reminder_intervals = models.JSONField(default=list, blank=True, help_text="List of days before/after due date, e.g. [-3,0,3,7]")
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    max_contacts_per_day = models.IntegerField(default=2)
    max_contacts_per_week = models.IntegerField(default=5)
    escalate_after_attempts = models.IntegerField(default=3)
    auto_pause_on_payment = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "collection_policies"

    def __str__(self):
        return f"Policy for {self.org}"

class CollectionCampaign(TenantManager):
    pass

class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("tenancy.Organization", on_delete=models.RESTRICT, related_name="collection_campaigns")
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    description = models.TextField(blank=True, default="")
    config = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CollectionCampaign()

    class Meta:
        db_table = "collection_campaigns"
        indexes = [models.Index(fields=["org", "status"])]

    def __str__(self):
        return self.name

# Alias for spec naming
CollectionCampaign = Campaign

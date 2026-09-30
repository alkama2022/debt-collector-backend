import uuid
from django.db import models

class WebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32, choices=[("paystack","Paystack"),("flutterwave","Flutterwave"),("manual","Manual")])
    event_id = models.CharField(max_length=128, unique=True)
    payload = models.JSONField(default=dict, blank=True)
    signature = models.CharField(max_length=512, blank=True, default="")
    processed = models.BooleanField(default=False)
    error_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "webhook_events"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "processed"])]

    def __str__(self):
        return f"{self.provider}:{self.event_id}"

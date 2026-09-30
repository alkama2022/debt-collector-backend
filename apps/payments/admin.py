from django.contrib import admin
from .models import Payment, Receipt

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "amount", "currency", "status", "provider", "provider_ref", "org", "created_at")
    list_filter = ("status", "provider", "currency")
    search_fields = ("provider_ref", "idempotency_key")

@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "payment", "amount", "currency", "issued_at")
    search_fields = ("receipt_number",)

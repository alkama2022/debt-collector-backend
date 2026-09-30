from django.contrib import admin
from .models import Customer

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("customer_code", "name", "email", "phone", "outstanding", "overdue", "org", "created_at")
    list_filter = ("opt_out",)
    search_fields = ("customer_code", "name", "email", "phone")

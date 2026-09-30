from django.contrib import admin
from .models import User

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "is_active", "is_staff", "date_joined")
    search_fields = ("email", "name")
    ordering = ("email",)

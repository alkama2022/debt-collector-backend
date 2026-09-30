from django.contrib import admin
from .models import AIConversation, AIMessage, AIAgentAction, PromiseToPay

@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "org", "customer", "state", "channel", "created_at")
    list_filter = ("state", "channel")

@admin.register(AIMessage)
class AIMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "created_at")

@admin.register(AIAgentAction)
class AIAgentActionAdmin(admin.ModelAdmin):
    list_display = ("tool", "conversation", "tokens", "cost_minor", "created_at")

@admin.register(PromiseToPay)
class PromiseToPayAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "promise_date", "amount", "status", "org")
    list_filter = ("status",)

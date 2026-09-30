from django.urls import path
from .views import VoiceCallListCreate, VoiceCallDetail, VoiceCallTriggerView, VoiceCallStatusWebhookView

urlpatterns = [
    path("voice/calls", VoiceCallListCreate.as_view(), name="voice-call-list"),
    path("voice/calls/<uuid:pk>", VoiceCallDetail.as_view(), name="voice-call-detail"),
    path("voice/calls/<uuid:pk>/trigger", VoiceCallTriggerView.as_view(), name="voice-call-trigger"),
    path("voice/webhook/status", VoiceCallStatusWebhookView.as_view(), name="voice-webhook-status"),
]

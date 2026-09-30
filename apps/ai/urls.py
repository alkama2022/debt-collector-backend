from django.urls import path
from .views import (
    AIConversationListCreate, AIConversationDetail, PromiseListCreate,
    DetectLanguageView, GenerateResponseView, VoiceLanguageView,
    LanguageHistoryView, LanguageMetricsView, StaffTranslationView,
)

urlpatterns = [
    path("ai/conversations", AIConversationListCreate.as_view(), name="ai-conversation-list"),
    path("ai/conversations/<uuid:pk>", AIConversationDetail.as_view(), name="ai-conversation-detail"),
    path("ai/promises", PromiseListCreate.as_view(), name="ai-promise-list"),
    path("ai/detect-language", DetectLanguageView.as_view(), name="ai-detect-language"),
    path("ai/generate-response", GenerateResponseView.as_view(), name="ai-generate-response"),
    path("ai/voice-language", VoiceLanguageView.as_view(), name="ai-voice-language"),
    path("ai/language-metrics", LanguageMetricsView.as_view(), name="ai-language-metrics"),
    path("ai/language-history", LanguageHistoryView.as_view(), name="ai-language-history"),
    path("ai/language-history/<uuid:pk>", LanguageHistoryView.as_view(), name="ai-language-history-detail"),
    # §33 — staff-facing translation; never overwrites the original message
    path("ai/staff-translation", StaffTranslationView.as_view(), name="ai-staff-translation"),
]

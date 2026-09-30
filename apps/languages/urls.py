from django.urls import path
from .views import (
    LanguageListView,
    LanguageDetailView,
    LanguageDetectView,
    LanguageResolveView,
    OrganizationLanguageSettingsView,
)

urlpatterns = [
    # Static paths first — must come before any parameterized patterns
    path("languages/detect", LanguageDetectView.as_view(), name="language-detect"),
    path("languages/resolve", LanguageResolveView.as_view(), name="language-resolve"),
    path("languages", LanguageListView.as_view(), name="language-list"),
    path("languages/<str:code>", LanguageDetailView.as_view(), name="language-detail"),
    # Org language settings — three aliased paths for compatibility
    path("org/language-settings", OrganizationLanguageSettingsView.as_view(), name="org-language-settings"),
    # Spec §30 aliases — plural/singular compatibility (both versioned under /api/v1/ via config/urls.py)
    path("organizations/language-settings", OrganizationLanguageSettingsView.as_view(), name="organizations-language-settings"),
    path("organisations/language-settings", OrganizationLanguageSettingsView.as_view(), name="organisations-language-settings-alias"),
]

from django.urls import path
from .views import OrganizationListCreateView, OrganizationDetailView, SwitchOrgView, OrgMembersView

# NOTE: /organizations/language-settings is also aliased here so that
# liveGetOrgLanguageSettings() / liveUpdateOrgLanguageSettings() in the frontend
# resolve correctly. The view itself lives in apps.languages.
from apps.languages.views import OrganizationLanguageSettingsView

urlpatterns = [
    # Static paths MUST come before parameterised <uuid:pk> patterns
    path("organizations/language-settings", OrganizationLanguageSettingsView.as_view(), name="org-language-settings-alias"),
    # Organization CRUD
    path("organizations", OrganizationListCreateView.as_view(), name="org-list-create"),
    path("organizations/<uuid:pk>", OrganizationDetailView.as_view(), name="org-detail"),
    path("organizations/<uuid:pk>/switch", SwitchOrgView.as_view(), name="org-switch"),
    path("organizations/<uuid:pk>/members", OrgMembersView.as_view(), name="org-members"),
]

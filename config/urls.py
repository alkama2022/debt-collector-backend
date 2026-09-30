from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView


urlpatterns = [
    path("admin/", admin.site.urls),
    # auth/login is handled by LoginView (returns user+org+tokens)
    # auth/signup is handled by SignupView (creates user+org)
    path("api/v1/auth/refresh", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.tenancy.urls")),
    path("api/v1/", include("apps.customers.urls")),
    path("api/v1/", include("apps.invoices.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.comms.urls")),
    path("api/v1/", include("apps.collections.urls")),
    path("api/v1/", include("apps.ai.urls")),
    path("api/v1/", include("apps.voice.urls")),
    path("api/v1/", include("apps.webhooks.urls")),
    path("api/v1/", include("apps.audit.urls")),
    path("api/v1/", include("apps.subscriptions.urls")),
    path("api/v1/", include("apps.languages.urls")),
    path("api/v1/", include("apps.reports.urls")),
    path("health", include("apps.tenancy.health_urls")),
    path("", include("apps.collectNaija.urls")),
]

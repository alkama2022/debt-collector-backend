from django.urls import path
from .views import ReportsSummaryView, ReportsExportView

urlpatterns = [
    path("reports/summary", ReportsSummaryView.as_view(), name="reports-summary"),
    path("reports/export", ReportsExportView.as_view(), name="reports-export"),
]

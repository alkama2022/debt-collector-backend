from django.urls import path
from .views import (
    AuditLogList,
    AuditLogCreate,
    AICommunicationAuditList,
    AICommunicationAuditCreate,
)

urlpatterns = [
    path("audit/logs", AuditLogList.as_view(), name="audit-log-list"),
    path("audit/logs/create", AuditLogCreate.as_view(), name="audit-log-create"),
    # §34 — multilingual AI communication audit trail
    path("audit/ai-communications", AICommunicationAuditList.as_view(), name="ai-comm-audit-list"),
    path("audit/ai-communications/create", AICommunicationAuditCreate.as_view(), name="ai-comm-audit-create"),
]

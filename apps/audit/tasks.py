"""
Retention enforcement for AI communication audits (§34).

"Do not store more sensitive content than necessary. Apply appropriate
retention policies."

Policy, most-sensitive-first:
  * voice recordings   ->  30 days
  * verbatim content   ->  90 days
  * structured metadata-> 365 days  (kept: §24 reporting needs it, identifies no one)

Purging blanks the content columns rather than deleting the row, so the
quality metrics that power the language dashboard survive the purge.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def purge_expired_ai_audit_content():
    """
    Strip verbatim content from AI communication audits past its retention
    window. Idempotent — safe to run daily.
    """
    from apps.audit.models import AICommunicationAudit
    from apps.audit.policy import RETENTION_DAYS_RECORDING, RETENTION_DAYS_TRANSCRIPT

    now = timezone.now()
    content_cutoff = now - timedelta(days=RETENTION_DAYS_TRANSCRIPT)
    recording_cutoff = now - timedelta(days=RETENTION_DAYS_RECORDING)

    # 1. Recordings expire first.
    recordings = AICommunicationAudit.objects.filter(
        created_at__lt=recording_cutoff
    ).exclude(recording_url="").update(recording_url="")

    # 2. Then verbatim text. Structured columns are intentionally preserved.
    transcripts = AICommunicationAudit.objects.filter(
        created_at__lt=content_cutoff
    ).exclude(response_text="").update(
        response_text="", request_summary="", staff_translation=""
    )

    logger.info(
        "[purge_expired_ai_audit_content] cleared recordings=%d transcripts=%d",
        recordings, transcripts,
    )
    return {"recordings_cleared": recordings, "transcripts_cleared": transcripts}

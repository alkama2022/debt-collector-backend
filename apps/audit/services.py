"""
Helper for writing §34 AI communication audit rows.

Centralised so every code path (generate-response, comms dispatch, voice)
records the same fields, and so a failure to audit can never silently take
down a customer-facing send.
"""
import logging

logger = logging.getLogger(__name__)

# Never store more of the customer's words than we need to explain a decision.
MAX_SUMMARY_CHARS = 500
MAX_RESPONSE_CHARS = 2000


def redact(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Trim and strip obvious direct identifiers from free text."""
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    # Collapse long digit runs (card numbers, account numbers) that are not
    # needed to explain a language decision.
    import re
    cleaned = re.sub(r"\b\d{6,}\b", "[redacted-number]", cleaned)
    return cleaned[:limit]


def record_ai_communication(org=None, **fields):
    """
    Persist one AICommunicationAudit row. Never raises into the caller.

    Auditing must not be able to break collections; a failure is logged loudly
    but the message still goes out.
    """
    if org is None:
        return None
    try:
        from apps.audit.models import AICommunicationAudit

        payload = dict(fields)
        for key in ("request_summary", "response_text", "staff_translation"):
            if key in payload and payload[key]:
                payload[key] = redact(payload[key], MAX_RESPONSE_CHARS)

        if "detection_confidence" in payload and payload["detection_confidence"] is not None:
            from decimal import Decimal
            payload["detection_confidence"] = Decimal(str(payload["detection_confidence"]))
        if "stt_confidence" in payload and payload["stt_confidence"] is not None:
            from decimal import Decimal
            payload["stt_confidence"] = Decimal(str(payload["stt_confidence"]))

        return AICommunicationAudit.objects.create(org=org, **payload)
    except Exception:
        logger.exception("[audit] failed to record AI communication")
        return None

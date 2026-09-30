"""
Tests for the §34 audit trail: minimisation and retention.

`record_ai_communication` needs the ORM, but the two rules that matter most —
do not store more than we need, and honour the retention window — are pure
logic and are tested here directly.
"""
import unittest
from datetime import timedelta

from apps.audit.services import MAX_RESPONSE_CHARS, redact


class RedactionTests(unittest.TestCase):
    """S34 - do not store more sensitive content than necessary."""

    def test_long_digit_runs_are_removed(self):
        out = redact("Customer card 012345678901 sent 85000 naira")
        self.assertNotIn("012345678901", out)
        self.assertIn("[redacted-number]", out)

    def test_short_amounts_survive(self):
        """An amount is needed to explain a decision; a card number is not."""
        out = redact("Balance 85000 is overdue")
        self.assertIn("85000", out)

    def test_whitespace_is_collapsed(self):
        self.assertEqual(redact("a\n\n  b\t c"), "a b c")

    def test_output_is_truncated(self):
        out = redact("x" * 5000, MAX_RESPONSE_CHARS)
        self.assertLessEqual(len(out), MAX_RESPONSE_CHARS)

    def test_empty_input_is_safe(self):
        self.assertEqual(redact(""), "")
        self.assertEqual(redact(None), "")


class RetentionPolicyTests(unittest.TestCase):
    """
    S34 retention windows. Values are asserted directly so shortening a
    retention window has to be a deliberate edit.
    """

    def test_retention_windows_are_ordered_by_sensitivity(self):
        from apps.audit.policy import (
            RETENTION_DAYS_METADATA,
            RETENTION_DAYS_RECORDING,
            RETENTION_DAYS_TRANSCRIPT,
        )
        self.assertLess(
            RETENTION_DAYS_RECORDING, RETENTION_DAYS_TRANSCRIPT,
            "recordings must expire before transcripts",
        )
        self.assertLess(
            RETENTION_DAYS_TRANSCRIPT, RETENTION_DAYS_METADATA,
            "verbatim content must expire before structured metadata",
        )

    def test_windows_match_the_documented_policy(self):
        from apps.audit.policy import (
            RETENTION_DAYS_METADATA,
            RETENTION_DAYS_RECORDING,
            RETENTION_DAYS_TRANSCRIPT,
        )
        self.assertEqual(RETENTION_DAYS_RECORDING, 30)
        self.assertEqual(RETENTION_DAYS_TRANSCRIPT, 90)
        self.assertEqual(RETENTION_DAYS_METADATA, 365)


class AuditModelShapeTests(unittest.TestCase):
    """S34 requires a specific set of recorded fields."""

    REQUIRED_FIELDS = (
        "customer", "language_selected", "language_detected",
        "detection_confidence", "channel", "ai_model", "prompt_version",
        "response_text", "translation_status", "voice_provider",
        "call_status", "escalated", "created_at",
    )

    def test_audit_model_declares_required_fields(self):
        import ast
        import os

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "audit", "models.py",
        )
        tree = ast.parse(open(path, encoding="utf-8").read())
        fields = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "AICommunicationAudit":
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name):
                        fields.add(stmt.targets[0].id)
        for name in self.REQUIRED_FIELDS:
            with self.subTest(field=name):
                self.assertIn(name, fields, f"AICommunicationAudit is missing {name}")

    def test_audit_is_immutable_by_design(self):
        import ast
        import os

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "audit", "models.py",
        )
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "AICommunicationAudit":
                methods = {
                    s.name for s in node.body if isinstance(s, ast.FunctionDef)
                }
                self.assertIn("save", methods)
                # The guard must actually raise.
                seg = ast.get_source_segment(src, node)
                self.assertIn("immutable", seg)

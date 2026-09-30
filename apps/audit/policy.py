"""
Data-retention policy (§34).

Kept free of Django imports so the policy can be reviewed, asserted and
changed without booting the ORM. `models.py` imports these values; nothing
else defines them.

Most sensitive first:
  * voice recordings    ->  30 days
  * verbatim text       ->  90 days
  * structured metadata -> 365 days

Structured metadata is kept longest on purpose: it is what the §24 language
dashboard reports on, and it identifies no one. Verbatim customer speech and
messages are the data we have the least business retaining.
"""

RETENTION_DAYS_RECORDING = 30
RETENTION_DAYS_TRANSCRIPT = 90
RETENTION_DAYS_METADATA = 365

#: Human-readable form, surfaced on the audit API so consumers know the window.
RETENTION_POLICY = {
    "recording": RETENTION_DAYS_RECORDING,
    "transcript": RETENTION_DAYS_TRANSCRIPT,
    "metadata": RETENTION_DAYS_METADATA,
}

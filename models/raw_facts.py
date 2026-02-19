"""Raw facts ledger for VQS (Virtual Queue Simulation).

Append-only bi-temporal store: event time (reference_period) and knowledge time (publication_date).
Used for backtesting: load only facts with publication_date <= T to reconstruct state at T.
"""

import uuid
from django.db import models


class RawFactSource(models.IntegerChoices):
    """Source of the raw fact. Value 0 reserved for invalid."""

    INVALID = 0, "Invalid/Unknown"
    USCIS_I140 = 1, "USCIS I-140 Receipts (Quarterly)"
    DOL_PERM = 2, "DOL PERM (Lag Distribution)"
    DOS_ANNUAL_REPORT = 3, "DOS Annual Report"
    USCIS_I485_INVENTORY = 4, "USCIS I-485 Inventory"
    DOS_ISSUANCE = 5, "DOS Monthly Issuance"
    DOL_PERM_DISCLOSURE = 6, "DOL PERM Disclosure"


class RawFactsLedger(models.Model):
    """
    Append-only ledger of raw facts for VQS.

    No data is ever overwritten. Event time = reference_period; knowledge time = publication_date.
    """

    fact_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for this fact",
    )
    source = models.IntegerField(
        choices=RawFactSource.choices,
        db_index=True,
        help_text="Source of the data (USCIS, DOL, DOS)",
    )
    metric = models.CharField(
        max_length=64,
        db_index=True,
        help_text="e.g. i140_receipts, visa_limit, perm_lag_distribution",
    )
    dimensions = models.JSONField(
        default=dict,
        help_text='e.g. {"country": "India", "category": "EB2"}',
    )
    value = models.JSONField(
        help_text="Raw number or distribution object",
    )
    reference_period_start = models.DateField(
        help_text="Event time: start of the period this data describes (e.g. quarter start)",
    )
    reference_period_end = models.DateField(
        help_text="Event time: end of the period this data describes (e.g. quarter end)",
    )
    publication_date = models.DateField(
        db_index=True,
        help_text="Knowledge time: when this data became public (critical for backtesting)",
    )

    class Meta:
        db_table = "raw_facts_ledger"
        ordering = ["-publication_date", "-reference_period_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "metric", "dimensions", "reference_period_start", "reference_period_end"],
                name="raw_facts_ledger_unique_fact",
            ),
        ]
        indexes = [
            models.Index(fields=["publication_date"], name="rfl_publication_date"),
            models.Index(fields=["source", "metric"], name="rfl_source_metric"),
            models.Index(fields=["reference_period_start"], name="rfl_ref_period_start"),
        ]

    def __str__(self):
        return f"RawFactsLedger({self.metric} {self.reference_period_start} pub={self.publication_date})"

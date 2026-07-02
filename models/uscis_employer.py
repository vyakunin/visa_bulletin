"""USCIS H-1B Employer Data Hub — per-employer approval/denial counts.

Source: USCIS H-1B Employer Data Hub (uscis.gov/tools/reports-and-studies/
h-1b-employer-data-hub), FY2009 → present, updated quarterly. Government-direct,
live, no FOIA/aggregation caveat — the correct source for the APPROVAL-RATE feature
(unlike the Bloomberg I-129 snapshot, which is needed only for actual pay + demo-
graphics and carries a frozen-snapshot caveat). See
docs/department_of_labor/I129_DATA_INTEGRATION_ASSESSMENT.md § "Other government-
published sources".

One row per employer × fiscal year × NAICS × city/state/ZIP, with first-decision
counts split initial-vs-continuing. NO wages, NO beneficiary demographics, NO LCA
join key — so it joins to our employer clusters only by normalized employer name
(lib/business/i129/employer_linker.py), same as the I-129 petitions.

The Data Hub CSV files are UTF-16, TAB-separated, with a leading line-number column;
columns: Fiscal Year · Employer (Petitioner) Name · Tax ID · Industry (NAICS) Code ·
Petitioner City · State · Zip · Initial Approval · Initial Denial · Continuing
Approval · Continuing Denial.
"""

from django.db import models

from .ingest.ingest_version import IngestVersion  # noqa: F401  (FK registration)
from .salary import (
    EmployerCluster,  # noqa: F401  (FK registration for employer_cluster)
)


class UscisEmployerApproval(models.Model):
    """One USCIS Data Hub row: an employer's H-1B approvals/denials for a fiscal year.

    Aggregated per employer cluster on the employer profile page to publish the
    real H-1B petition approval rate (the LCA certification rate we already show is
    ~99% and non-differentiating; USCIS petition denials are the meaningful signal).
    """

    fiscal_year = models.IntegerField(db_index=True, help_text="USCIS fiscal year")
    employer_name = models.CharField(max_length=255, blank=True, db_index=True)
    tax_id = models.CharField(
        max_length=20, blank=True, help_text="Masked employer tax id (last 4), as shipped"
    )
    naics_code = models.CharField(
        max_length=120, blank=True, help_text="Industry (NAICS) — code or 'NN - Label'"
    )
    petitioner_city = models.CharField(max_length=100, blank=True)
    petitioner_state = models.CharField(max_length=2, blank=True, db_index=True)
    petitioner_zip = models.CharField(max_length=10, blank=True)

    initial_approval = models.IntegerField(default=0)
    initial_denial = models.IntegerField(default=0)
    continuing_approval = models.IntegerField(default=0)
    continuing_denial = models.IntegerField(default=0)

    employer_cluster = models.ForeignKey(
        "models.EmployerCluster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name="uscis_approvals",
        help_text="Resolved LCA employer cluster (employer_linker.py). NULL when no "
        "LCA cluster matched the name.",
    )
    ingest_version = models.ForeignKey(
        "models.IngestVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uscis_employer_approvals",
        help_text="Ingest version this record belongs to (for rollback)",
    )
    source_file = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "uscis_employer_approval"
        ordering = ["-fiscal_year", "employer_name"]
        indexes = [
            models.Index(fields=["employer_name", "fiscal_year"]),
            models.Index(fields=["employer_cluster", "fiscal_year"]),
        ]

    def __str__(self):
        return f"{self.employer_name} FY{self.fiscal_year}"

    @property
    def total_approvals(self) -> int:
        return (self.initial_approval or 0) + (self.continuing_approval or 0)

    @property
    def total_denials(self) -> int:
        return (self.initial_denial or 0) + (self.continuing_denial or 0)

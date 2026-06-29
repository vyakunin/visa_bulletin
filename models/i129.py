"""I-129 H-1B petition models (USCIS, obtained by Bloomberg via FOIA).

Source: github.com/BloombergGraphics/2024-h1b-immigration-data (Apache-2.0).
Cite as "sourced from USCIS, obtained by Bloomberg." Coverage is FY2021-FY2024,
cap-subject lottery petitions only, a frozen one-time FOIA snapshot — NOT a live
feed. Beneficiary linking keys (bcn, full DOB, receipt number) are FOIA-redacted,
so this is individual-level only at the level of country + birth-year + gender;
publish AGGREGATES with small-n suppression, never row-level beneficiary records.

The unique value vs every free competitor: the I-129 petition carries the
beneficiary's ACTUAL pay (`comp_paid_annual`) and demographics, which join to our
LCA `worksite_record` on the (normalized) DOL ETA case number — letting us surface
actual pay vs the LCA-posted wage vs the prevailing-wage floor.
"""

import re

from django.db import models

from .enums.visa_program import WageUnit
from .ingest.ingest_version import IngestVersion  # noqa: F401  (FK registration)

# I-129 BASIS_FOR_CLASSIFICATION codes (Part 2, Q2 of Form I-129). Stored raw (one
# char) on the row; this map is for display. See the dataset data dictionary.
BASIS_FOR_CLASSIFICATION_DESCRIPTIONS = {
    "A": "New employment",
    "B": "Continuation of previously approved employment without change",
    "C": "Change in previously approved employment",
    "D": "New concurrent employment",
    "E": "Change of employer",
    "F": "Amended petition",
}

# BEN_EDUCATION_CODE → level (the dataset ships ED_LEVEL_DEFINITION alongside; this
# map lets us derive a label when the definition column is blank).
EDUCATION_CODE_DESCRIPTIONS = {
    "A": "No Diploma",
    "B": "High School Grad",
    "C": "Some college credit, less than 1 year",
    "D": "One or more years of college, no degree",
    "E": "Associate's degree",
    "F": "Bachelor's degree",
    "G": "Master's degree",
    "H": "Professional degree",
    "I": "Doctorate degree",
}

# A FOIA redaction marker that appears verbatim in protected-population rows
# (T_U_VAWA_FLAG) across many columns. Treat any cell holding it as blank.
_REDACTION_MARKER = "(B)("

_HYPHENLESS_ETA_RE = re.compile(r"^[A-Z]\d{14}$")


def normalize_dol_eta_case_number(raw: str | None) -> str:
    """Normalize a DOL ETA case number to our hyphenated, upper-cased form.

    Bloomberg ships the join key hyphen-less (``I20023263363671``); our LCA
    ``worksite_record.case_number`` is hyphenated (``I-200-23263-363671``).
    Returns "" for blanks / FOIA-redaction markers so callers can drop the row.
    """
    if not raw:
        return ""
    value = str(raw).strip().upper()
    if not value or _REDACTION_MARKER in value:
        return ""
    if "-" in value:
        return value  # already hyphenated
    if _HYPHENLESS_ETA_RE.match(value):
        # letter + 3 + 5 + 6 → X-NNN-NNNNN-NNNNNN
        return f"{value[0]}-{value[1:4]}-{value[4:9]}-{value[9:]}"
    return value


class FirstDecision(models.IntegerChoices):
    """USCIS first decision on an I-129 petition (FIRST_DECISION column)."""

    INVALID = 0, "Unknown"
    APPROVED = 1, "Approved"
    DENIED = 2, "Denied"

    @classmethod
    def from_str(cls, value: str | None) -> "FirstDecision":
        if not value:
            return cls.INVALID
        return {"APPROVED": cls.APPROVED, "DENIED": cls.DENIED}.get(
            str(value).strip().upper(), cls.INVALID
        )


class RegistrationStatus(models.IntegerChoices):
    """Lottery registration status (status_type column)."""

    INVALID = 0, "Unknown"
    SELECTED = 1, "Selected"
    ELIGIBLE = 2, "Eligible (not selected)"
    CREATED = 3, "Created (not selected)"

    @classmethod
    def from_str(cls, value: str | None) -> "RegistrationStatus":
        if not value:
            return cls.INVALID
        return {
            "SELECTED": cls.SELECTED,
            "ELIGIBLE": cls.ELIGIBLE,
            "CREATED": cls.CREATED,
        }.get(str(value).strip().upper(), cls.INVALID)


class I129Petition(models.Model):
    """A selected-and-filed H-1B I-129 petition with actual pay + demographics.

    One row per beneficiary petition that carries a DOL ETA case number (the
    joinable petition universe). NOT unique on `dol_eta_case_number`: a single LCA
    can cover multiple beneficiaries (co-beneficiaries), so the join key legitimately
    repeats across rows — uniqueness would silently drop co-beneficiaries.
    """

    # --- Join key + provenance ---------------------------------------------------
    dol_eta_case_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Normalized DOL ETA case number; joins to worksite_record.case_number. "
        "NOT unique — one LCA can cover multiple beneficiaries.",
    )
    fiscal_year = models.IntegerField(
        db_index=True, help_text="Lottery fiscal year (FY2021-FY2024)"
    )
    lottery_year = models.IntegerField(
        null=True, blank=True, help_text="Lottery year as recorded in the source row"
    )

    # --- Lottery / registration --------------------------------------------------
    status_type = models.IntegerField(
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.INVALID,
        db_index=True,
        help_text="Lottery registration status",
    )
    ben_multi_reg_ind = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Beneficiary had multiple registrations by different employers (gaming signal)",
    )

    # --- Petition lifecycle ------------------------------------------------------
    first_decision = models.IntegerField(
        choices=FirstDecision.choices,
        default=FirstDecision.INVALID,
        db_index=True,
        help_text="USCIS first decision on the petition",
    )
    first_decision_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    basis_for_classification = models.CharField(
        max_length=1,
        blank=True,
        help_text="I-129 Part 2 Q2 basis code (A=new, E=change of employer, F=amended, ...)",
    )
    requested_action = models.CharField(max_length=1, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    # --- Employer ----------------------------------------------------------------
    employer_name = models.CharField(max_length=255, blank=True, db_index=True)
    i129_employer_name = models.CharField(max_length=255, blank=True)
    fein = models.CharField(
        max_length=20, blank=True, db_index=True, help_text="Employer tax id (FEIN)"
    )
    naics_code = models.CharField(max_length=20, blank=True)
    num_emp_in_us = models.IntegerField(null=True, blank=True)
    h1b_dependent = models.BooleanField(
        null=True, blank=True, help_text="S1Q1A: petitioner is an H-1B dependent employer"
    )
    willful_violator = models.BooleanField(
        null=True, blank=True, help_text="S1Q1B: petitioner ever found a willful violator"
    )

    # --- Job + worksite ----------------------------------------------------------
    job_title = models.CharField(max_length=255, blank=True, db_index=True)
    worksite_city = models.CharField(max_length=100, blank=True)
    worksite_state = models.CharField(max_length=2, blank=True, db_index=True)
    worksite_zip = models.CharField(max_length=10, blank=True)
    full_time = models.BooleanField(null=True, blank=True)

    # --- Wage (the headline: ACTUAL pay) -----------------------------------------
    wage_amt = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Raw WAGE_AMT in the stated wage_unit",
    )
    wage_unit = models.CharField(max_length=20, choices=WageUnit.choices, blank=True)
    comp_paid_annual = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="BEN_COMP_PAID — beneficiary rate of pay per year (as filed)",
    )
    pay_annual = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, db_index=True,
        help_text="Canonical annualized actual pay: comp_paid_annual, else WAGE_AMT "
        "annualized by wage_unit. Compare to worksite_record.wage_annual (LCA-posted).",
    )

    # --- Beneficiary demographics (country + birth-year + gender only) -----------
    country_of_birth = models.CharField(
        max_length=80, blank=True, db_index=True,
        help_text="Beneficiary country of birth (ISO3 as shipped)",
    )
    ben_year_of_birth = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True, db_index=True)
    education_code = models.CharField(max_length=1, blank=True)
    ed_level = models.CharField(max_length=120, blank=True)
    field_of_study = models.CharField(max_length=255, blank=True)

    # --- Metadata ----------------------------------------------------------------
    source_file = models.CharField(max_length=255, blank=True)
    ingest_version = models.ForeignKey(
        "models.IngestVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="i129_petitions",
        help_text="Ingest version this record belongs to (for rollback)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "i129_petition"
        ordering = ["-fiscal_year", "dol_eta_case_number"]
        indexes = [
            models.Index(fields=["fiscal_year", "first_decision"]),
            models.Index(fields=["worksite_state", "fiscal_year"]),
            models.Index(fields=["country_of_birth", "fiscal_year"]),
            models.Index(fields=["job_title", "worksite_state"]),
            models.Index(fields=["employer_name", "fiscal_year"]),
            models.Index(fields=["pay_annual"]),
        ]

    def __str__(self):
        return f"{self.dol_eta_case_number} FY{self.fiscal_year} {self.job_title}"

    @property
    def basis_description(self) -> str:
        return BASIS_FOR_CLASSIFICATION_DESCRIPTIONS.get(
            self.basis_for_classification, ""
        )

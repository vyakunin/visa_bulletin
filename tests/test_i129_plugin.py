"""Unit tests for the USCIS I-129 H-1B petition ingest plugin.

Records below are real (lightly trimmed) rows from the Bloomberg FY2024 single_reg
file, so the transform is exercised against the actual on-disk shape — including the
hyphen-less DOL ETA case number and the FOIA ``(b)(6)`` redaction markers.
"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import pytest

from lib.ingest.plugins.uscis_i129 import I129PetitionPlugin, _canonical_url
from models.enums.visa_program import WageUnit
from models.i129 import (
    FirstDecision,
    I129Petition,
    RegistrationStatus,
    normalize_dol_eta_case_number,
)
from models.ingest.enums import DataDomain, FormatVersion, SourceType


def _selected_filed_row() -> dict:
    """A real SELECTED + filed petition row (HTN Wireless, approved, YEAR wage)."""
    return {
        "bcn": "(b)(6)",
        "country_of_birth": "PAK",
        "ben_year_of_birth": "1986",
        "gender": "male",
        "employer_name": "HTN Wireless, Inc.",
        "FEIN": "454501525",
        "lottery_year": "2024",
        "status_type": "SELECTED",
        "ben_multi_reg_ind": "0",
        "RECEIPT_NUMBER": "(b)(6)",
        "rec_date": "10/6/2023",
        "FIRST_DECISION": "Approved",
        "first_decision_date": "11/22/2023",
        "i129_employer_name": "HTN WIRELESS INC",
        "BASIS_FOR_CLASSIFICATION": "A",
        "REQUESTED_ACTION": "A",
        "BEN_SEX": "M",
        "BEN_COUNTRY_OF_BIRTH": "PAKIS",
        "JOB_TITLE": "RF ENGINEER",
        "DOL_ETA_CASE_NUMBER": "I20023264366927",
        "WORKSITE_CITY": "LAGUNA HILLS",
        "WORKSITE_STATE": "CA",
        "WORKSITE_ZIP": "92653",
        "FULL_TIME_IND": "Y",
        "WAGE_AMT": "79934",
        "WAGE_UNIT": "YEAR",
        "valid_from": "11/22/2023",
        "valid_to": "9/30/2026",
        "NUM_OF_EMP_IN_US": "6",
        "S1Q1A": "N",
        "S1Q1B": "N",
        "BEN_EDUCATION_CODE": "F",
        "ED_LEVEL_DEFINITION": "BACHELOR'S DEGREE",
        "BEN_PFIELD_OF_STUDY": "ELECTRICAL ENGINEERING TELECOM",
        "BEN_COMP_PAID": "79934",
        "NAICS_CODE": "541511",
        "_fiscal_year": 2024,
        "_source_file": "TRK_13139_FY2024_single_reg.csv",
        "_row_num": 2,
    }


class TestCaseNumberNormalization:
    def test_hyphenless_to_hyphenated(self):
        assert (
            normalize_dol_eta_case_number("I20023264366927") == "I-200-23264-366927"
        )

    def test_already_hyphenated_passthrough(self):
        assert (
            normalize_dol_eta_case_number("I-200-23264-366927")
            == "I-200-23264-366927"
        )

    def test_lowercases_to_upper(self):
        assert normalize_dol_eta_case_number("i20023264366927").startswith("I-200-")

    def test_blank_and_redaction_become_empty(self):
        assert normalize_dol_eta_case_number("") == ""
        assert normalize_dol_eta_case_number(None) == ""
        assert normalize_dol_eta_case_number("(b)(3) (b)(6) (b)(7)(c)") == ""


class TestEnumsFromStr:
    def test_first_decision(self):
        assert FirstDecision.from_str("Approved") == FirstDecision.APPROVED
        assert FirstDecision.from_str("Denied") == FirstDecision.DENIED
        assert FirstDecision.from_str("") == FirstDecision.INVALID
        assert FirstDecision.from_str("(b)(3)") == FirstDecision.INVALID

    def test_registration_status(self):
        assert RegistrationStatus.from_str("SELECTED") == RegistrationStatus.SELECTED
        assert RegistrationStatus.from_str("ELIGIBLE") == RegistrationStatus.ELIGIBLE
        assert RegistrationStatus.from_str("") == RegistrationStatus.INVALID


class TestPluginAttributes:
    def test_domain_and_source_type(self):
        plugin = I129PetitionPlugin()
        assert plugin.domain == DataDomain.USCIS
        assert plugin.source_type == SourceType.I129

    def test_format_version_is_modern(self):
        from pathlib import Path

        assert (
            I129PetitionPlugin().get_format_version(Path("TRK_13139_FY2024.csv"))
            == FormatVersion.MODERN
        )

    def test_discover_sources_covers_all_fiscal_years(self):
        sources = I129PetitionPlugin().discover_sources()
        urls = [s.url for s in sources]
        # FY2021, FY2022, FY2023 (.001 only), FY2024 single + multi = 5 files
        assert len(sources) == 5
        assert any("FY2021.zip" in u for u in urls)
        assert any("FY2023.zip.001" in u for u in urls)
        assert sum("FY2024" in u for u in urls) == 2
        # split .002/.003 parts are derived in download(), not discovered
        assert not any(u.endswith(".zip.002") for u in urls)


class TestTransform:
    def test_selected_filed_row_maps_all_fields(self):
        result = I129PetitionPlugin().transform(_selected_filed_row())

        assert isinstance(result, I129Petition)
        assert result.dol_eta_case_number == "I-200-23264-366927"
        assert result.fiscal_year == 2024
        assert result.status_type == RegistrationStatus.SELECTED
        assert result.ben_multi_reg_ind is False
        assert result.first_decision == FirstDecision.APPROVED
        assert result.basis_for_classification == "A"
        assert result.employer_name == "HTN Wireless, Inc."
        assert result.fein == "454501525"
        assert result.job_title == "RF ENGINEER"
        assert result.worksite_state == "CA"
        assert result.full_time is True
        assert result.h1b_dependent is False
        assert result.willful_violator is False
        # wage: BEN_COMP_PAID present → pay_annual uses it directly
        assert result.comp_paid_annual == 79934
        assert result.wage_unit == WageUnit.YEAR
        assert result.pay_annual == 79934
        # demographics
        assert result.country_of_birth == "PAK"
        assert result.ben_year_of_birth == 1986
        assert result.gender == "male"
        assert result.education_code == "F"
        assert result.field_of_study == "ELECTRICAL ENGINEERING TELECOM"

    def test_hourly_wage_is_annualized_when_no_comp_paid(self):
        row = _selected_filed_row()
        row["BEN_COMP_PAID"] = ""  # denied/blank comp → fall back to WAGE_AMT
        row["WAGE_AMT"] = "50"
        row["WAGE_UNIT"] = "HOUR"
        result = I129PetitionPlugin().transform(row)
        assert result.comp_paid_annual is None
        assert result.wage_unit == WageUnit.HOUR
        assert result.pay_annual == 50 * 2080  # 104,000

    def test_registration_only_row_dropped(self):
        """An ELIGIBLE (not selected) row has no DOL ETA case number → dropped."""
        row = _selected_filed_row()
        row["status_type"] = "ELIGIBLE"
        row["DOL_ETA_CASE_NUMBER"] = ""
        assert I129PetitionPlugin().transform(row) is None

    def test_redacted_case_number_dropped(self):
        row = _selected_filed_row()
        row["DOL_ETA_CASE_NUMBER"] = "(b)(3) (b)(6) (b)(7)(c)"
        assert I129PetitionPlugin().transform(row) is None

    def test_multi_reg_flag_true(self):
        row = _selected_filed_row()
        row["ben_multi_reg_ind"] = "1"
        result = I129PetitionPlugin().transform(row)
        assert result.ben_multi_reg_ind is True


class TestCanonicalUrl:
    """DataSource URLs are lowercased on registration, but GitHub raw paths are
    case-sensitive (regression: lowercased path 404s on every FY file)."""

    def test_lowercased_url_rebuilt_to_case_sensitive_github_path(self):
        stored = (
            "https://github.com/bloomberggraphics/2024-h1b-immigration-data/"
            "raw/main/trk_13139_fy2021.zip"
        )
        assert _canonical_url(stored) == (
            "https://github.com/BloombergGraphics/2024-h1b-immigration-data/"
            "raw/main/TRK_13139_FY2021.zip"
        )

    def test_lowercased_multipart_first_part_rebuilt(self):
        stored = (
            "https://github.com/bloomberggraphics/2024-h1b-immigration-data/"
            "raw/main/trk_13139_fy2023.zip.001"
        )
        assert _canonical_url(stored).endswith("TRK_13139_FY2023.zip.001")

    def test_unknown_url_passed_through(self):
        other = "https://example.com/some_other_file.zip"
        assert _canonical_url(other) == other


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

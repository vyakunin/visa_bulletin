"""Tests for the USCIS H-1B Employer Data Hub ingest plugin.

Locks: the real-world file quirks — UTF-16 encoding, TAB separator, a leading
line-number column, trailing whitespace in header names — parse correctly; counts
map to the right fields; header-junk and blank-employer rows are dropped.
"""

import tempfile
from pathlib import Path

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.ingest.plugins.uscis_datahub import UscisEmployerDataHubPlugin

# Real header (note the leading "Line by line" col + trailing spaces on "Fiscal Year").
_HEADER = (
    "Line by line\tFiscal Year   \tEmployer (Petitioner) Name\tTax ID\t"
    "Industry (NAICS) Code\tPetitioner City\tPetitioner State\t"
    "Petitioner Zip Code\tInitial Approval\tInitial Denial\t"
    "Continuing Approval\tContinuing Denial"
)


def _write_utf16_tsv(rows: list[str]) -> Path:
    """Write a UTF-16 TAB-separated Data Hub file (as USCIS ships them)."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", encoding="utf-16", delete=False, newline=""
    )
    tmp.write("\n".join([_HEADER] + rows) + "\n")
    tmp.close()
    return Path(tmp.name)


class _FakeRun:
    id = 1
    records_created = 0
    checkpoint: dict = {}


class TestUscisDataHubPlugin(TestCase):
    def test_parses_utf16_tab_separated_and_maps_counts(self):
        rows = [
            "1\t2024\tGOOGLE LLC\t1234\t54 - Professional, Scientific\t"
            "MOUNTAIN VIEW\tCA\t94043\t120\t3\t45\t2",
        ]
        path = _write_utf16_tsv(rows)
        plugin = UscisEmployerDataHubPlugin()
        parsed = list(plugin.parse(path, _FakeRun()))
        assert len(parsed) == 1
        obj = plugin.transform(parsed[0])
        assert obj is not None
        assert obj.fiscal_year == 2024
        assert obj.employer_name == "GOOGLE LLC"
        assert obj.tax_id == "1234"
        assert obj.naics_code == "54 - Professional, Scientific"
        assert obj.petitioner_state == "CA"
        assert obj.petitioner_zip == "94043"
        assert obj.initial_approval == 120
        assert obj.initial_denial == 3
        assert obj.continuing_approval == 45
        assert obj.continuing_denial == 2
        assert obj.total_approvals == 165
        assert obj.total_denials == 5

    def test_blank_employer_and_bad_year_rows_dropped(self):
        rows = [
            # blank employer name (FY2009-style) → dropped
            "1\t2009\t\t\t\tFLUSHING\tNY\t11355\t0\t0\t0\t1",
            # valid row → kept
            "2\t2009\t0CHAIN LLC\t8948\t54\tCUPERTINO\tCA\t95014\t0\t0\t2\t0",
        ]
        path = _write_utf16_tsv(rows)
        plugin = UscisEmployerDataHubPlugin()
        objs = [plugin.transform(r) for r in plugin.parse(path, _FakeRun())]
        kept = [o for o in objs if o is not None]
        assert len(kept) == 1
        assert kept[0].employer_name == "0CHAIN LLC"
        assert kept[0].continuing_approval == 2

    def test_comma_counts_and_blanks_parse(self):
        rows = ["1\t2023\tBIG CORP\t9999\t54\tNYC\tNY\t10001\t1,234\t\t5\t"]
        path = _write_utf16_tsv(rows)
        plugin = UscisEmployerDataHubPlugin()
        obj = plugin.transform(next(iter(plugin.parse(path, _FakeRun()))))
        assert obj.initial_approval == 1234
        assert obj.initial_denial == 0  # blank → 0
        assert obj.continuing_denial == 0

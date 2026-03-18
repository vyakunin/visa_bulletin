"""
Test that exercises the legacy bulletin parser path that uses FamilyPreference.

This test uses the same dependency graph as the refresh_bulletin binary (parser
via visa_bulletin plugin, no webapp views). The parser BUILD must declare
//models/enums:family_preference so refresh_bulletin runfiles include it;
otherwise prod fails with ModuleNotFoundError. This test asserts the normalization
behavior (legacy "1st" -> "F1"); the BUILD dep is required for that code path to work
when the binary runs from runfiles (no workspace).
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from lib.parsing.bulletin.parser import extract_tables_legacy


def test_legacy_parser_requires_family_preference_dep():
    """
    Regression: extract_table_legacy() uses FamilyPreference.normalize_legacy_name()
    for family-sponsored tables. Parser must declare //models/enums:family_preference
    so refresh_bulletin runfiles include it (ModuleNotFoundError on prod otherwise).
    Uses inline HTML so the test never skips.
    """
    html = """
    <table>
    <tr><td>Family-Sponsored</td><td>All Chargeability Areas</td></tr>
    <tr><td>1st</td><td>01JAN00</td></tr>
    </table>
    """
    tables = extract_tables_legacy(html)
    assert len(tables) == 1, "Should extract one legacy table"
    table = tables[0]
    assert table.title == "family_sponsored_final_actions"
    assert len(table.rows) >= 1, "Should have at least one data row"
    assert table.rows[0][0] == "F1", (
        "Legacy '1st' should be normalized to 'F1' "
        "(parser must depend on models/enums:family_preference)"
    )

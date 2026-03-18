"""
Behavioral tests for BulletinExtractor

These tests verify actual behavior: parsing tables, handling dates,
mapping strings to enums, handling special cases like "C" and "U".
"""

# Django setup (shared utility for both Bazel and pytest)
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from datetime import date, datetime

from lib.parsing.bulletin.bulletin_table import BulletinTable
from lib.parsing.bulletin.parser import extract_tables_legacy
from lib.parsing.bulletin.publication_data import PublicationData
from lib.parsing.bulletin.table_to_cutoff_data import TableToCutoffData
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_category import VisaCategory
from models.visa_cutoff_date import VisaCutoffDate


def test_extract_family_sponsored_final_action_table():
    """Test extracting F1 data from real table structure"""
    # Create sample table matching actual bulletin format
    headers = (
        "Family- Sponsored",
        "All Chargeability Areas Except Those Listed",
        "CHINA-mainland born",
        "INDIA",
        "MEXICO",
        "PHILIPPINES",
    )
    rows = [
        (
            "F1",
            date(2016, 11, 8),
            date(2016, 11, 8),
            date(2016, 11, 8),
            date(2006, 3, 1),
            date(2013, 1, 22),
        ),
        ("F2A", "C", "C", "C", "C", "C"),
    ]
    table = BulletinTable("family_sponsored_final_actions", headers, rows)

    pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))
    extractor = TableToCutoffData(pub_data)
    results = extractor.extract_from_table(table)

    # Verify F1 extraction (using enum values, not hardcoded strings)
    f1_all = next(
        r
        for r in results
        if r["visa_class"] == "F1" and r["country"] == Country.ALL.value
    )
    assert f1_all["cutoff_date"] == date(2016, 11, 8)
    assert f1_all["is_current"] is False
    assert f1_all["action_type"] == ActionType.FINAL_ACTION.value
    assert f1_all["visa_category"] == VisaCategory.FAMILY_SPONSORED.value

    f1_mexico = next(
        r
        for r in results
        if r["visa_class"] == "F1" and r["country"] == Country.MEXICO.value
    )
    assert f1_mexico["cutoff_date"] == date(2006, 3, 1)


def test_handle_current_status():
    """Test that 'C' (Current) is handled correctly - sets cutoff to bulletin date"""
    headers = ("Family- Sponsored", "All Chargeability Areas Except Those Listed")
    rows = [("F2A", "C")]
    table = BulletinTable("family_sponsored_final_actions", headers, rows)

    pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))
    extractor = TableToCutoffData(pub_data)
    results = extractor.extract_from_table(table)

    f2a = results[0]
    assert f2a["cutoff_value"] == "C"
    assert f2a["is_current"] is True
    # 'C' means Current - cutoff date should be the bulletin's publication date
    assert f2a["cutoff_date"] == date(2025, 12, 1)
    assert f2a["is_unavailable"] is False


def test_handle_unavailable_status():
    """Test that 'U' (Unavailable) is handled correctly"""
    headers = ("Employment- based", "All Chargeability Areas Except Those Listed")
    rows = [("Certain Religious Workers", "U")]
    table = BulletinTable("employment_based_final_action", headers, rows)

    pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))
    extractor = TableToCutoffData(pub_data)
    results = extractor.extract_from_table(table)

    religious = results[0]
    assert religious["cutoff_value"] == "U"
    assert religious["is_unavailable"] is True
    assert religious["cutoff_date"] is None
    assert religious["is_current"] is False


def test_map_table_title_to_category_and_action():
    """Test mapping table titles to enums"""
    # Use enum values, not hardcoded strings
    test_cases = [
        (
            "family_sponsored_final_actions",
            VisaCategory.FAMILY_SPONSORED.value,
            ActionType.FINAL_ACTION.value,
        ),
        (
            "family_sponsored_dates_for_filing",
            VisaCategory.FAMILY_SPONSORED.value,
            ActionType.FILING.value,
        ),
        (
            "employment_based_final_action",
            VisaCategory.EMPLOYMENT_BASED.value,
            ActionType.FINAL_ACTION.value,
        ),
        (
            "employment_based_dates_for_filing",
            VisaCategory.EMPLOYMENT_BASED.value,
            ActionType.FILING.value,
        ),
    ]

    pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))

    for title, expected_category, expected_action in test_cases:
        headers = ("Test", "All Chargeability Areas Except Those Listed")
        rows = [("F1", date(2020, 1, 1))]
        table = BulletinTable(title, headers, rows)

        extractor = TableToCutoffData(pub_data)
        results = extractor.extract_from_table(table)

        assert results[0]["visa_category"] == expected_category, f"Failed for {title}"
        assert results[0]["action_type"] == expected_action, f"Failed for {title}"


def test_map_header_to_country_enum():
    """Test mapping table headers to country strings"""
    headers = (
        "Class",
        "All Chargeability Areas Except Those Listed",
        "CHINA-mainland born",
        "INDIA",
        "MEXICO",
        "PHILIPPINES",
    )
    rows = [
        (
            "F1",
            date(2020, 1, 1),
            date(2020, 1, 1),
            date(2020, 1, 1),
            date(2020, 1, 1),
            date(2020, 1, 1),
        )
    ]
    table = BulletinTable("family_sponsored_final_actions", headers, rows)

    pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))
    extractor = TableToCutoffData(pub_data)
    results = extractor.extract_from_table(table)

    countries = {r["country"] for r in results}
    # Use enum values, not hardcoded strings
    assert Country.ALL.value in countries
    assert Country.CHINA.value in countries
    assert Country.INDIA.value in countries
    assert Country.MEXICO.value in countries
    assert Country.PHILIPPINES.value in countries


def test_save_to_database(sample_bulletin):
    """Test saving extracted data to database"""
    bulletin = sample_bulletin

    headers = ("Family- Sponsored", "All Chargeability Areas Except Those Listed")
    rows = [("F1", date(2016, 11, 8))]
    table = BulletinTable("family_sponsored_final_actions", headers, rows)

    pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))
    extractor = TableToCutoffData(pub_data)
    results = extractor.extract_from_table(table)

    # Save to DB
    for data in results:
        VisaCutoffDate.objects.create(bulletin=bulletin, **data)

    # Query back (using enum values, not hardcoded strings)
    saved = VisaCutoffDate.objects.filter(
        bulletin=bulletin, visa_class="F1", country=Country.ALL.value
    ).first()

    assert saved is not None
    assert saved.cutoff_date == date(2016, 11, 8)
    assert saved.visa_category == VisaCategory.FAMILY_SPONSORED.value
    assert saved.action_type == ActionType.FINAL_ACTION.value


def test_idempotent_save(sample_bulletin):
    """Test that saving same bulletin twice doesn't duplicate"""
    bulletin = sample_bulletin

    headers = ("Family- Sponsored", "All Chargeability Areas Except Those Listed")
    rows = [("F1", date(2016, 11, 8))]
    table = BulletinTable("family_sponsored_final_actions", headers, rows)

    pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))
    extractor = TableToCutoffData(pub_data)
    results = extractor.extract_from_table(table)

    # Save once
    for data in results:
        VisaCutoffDate.objects.update_or_create(
            bulletin=bulletin,
            visa_class=data["visa_class"],
            country=data["country"],
            action_type=data["action_type"],
            visa_category=data["visa_category"],
            defaults=data,
        )

    count_first = VisaCutoffDate.objects.count()

    # Save again
    for data in results:
        VisaCutoffDate.objects.update_or_create(
            bulletin=bulletin,
            visa_class=data["visa_class"],
            country=data["country"],
            action_type=data["action_type"],
            visa_category=data["visa_category"],
            defaults=data,
        )

    count_second = VisaCutoffDate.objects.count()

    # Should not duplicate
    assert count_first == count_second


def test_legacy_parser_2001_2003_format():
    """Regression: 2001-2003 bulletins have table type in row 1, not row 0."""
    from pathlib import Path

    path = Path("data/bulletin/saved_pages/visa-bulletin-for-january-2002.html")
    if not path.exists():
        return  # skip if file not in runfiles
    html = path.read_text(encoding="utf-8", errors="ignore")
    tables = extract_tables_legacy(html)
    assert len(tables) == 2, f"Expected 2 tables (family + employment), got {len(tables)}"
    titles = {t.title for t in tables}
    assert titles == {"family_sponsored_final_actions", "employment_based_final_action"}
    for t in tables:
        assert len(t.rows) >= 1, f"Table {t.title} should have at least 1 data row"
        assert len(t.headers) >= 1, f"Table {t.title} should have headers"


def test_legacy_parser_family_preference_dependency():
    """
    Regression: extract_table_legacy() uses FamilyPreference.normalize_legacy_name()
    for family-sponsored tables. Ensures parser BUILD declares models/enums:family_preference
    so refresh_bulletin runfiles include it (ModuleNotFoundError on prod otherwise).
    Uses inline HTML so this test never skips and would fail if the dep is removed.
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
    # Legacy "1st" must be normalized to "F1" via FamilyPreference.normalize_legacy_name
    assert table.rows[0][0] == "F1", (
        "Legacy visa class '1st' should be normalized to 'F1' "
        "(parser must depend on models/enums:family_preference)"
    )

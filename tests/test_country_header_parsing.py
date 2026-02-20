"""
Unit tests for country header parsing and extraction

Tests that verify:
1. Headers are extracted correctly from HTML tables
2. Country.from_header() matches various header formats
3. "All Chargeability Areas" headers are parsed correctly
4. Multi-line HTML headers are handled properly
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from lib.parsing.bulletin.parser import extract_tables, normalize
from lib.parsing.bulletin.publication_data import PublicationData
from lib.parsing.bulletin.table_to_cutoff_data import TableToCutoffData
from models.enums.country import Country


class TestCountryHeaderParsing(unittest.TestCase):
    """Test country header parsing from various formats"""

    def setUp(self):
        """Set up test data"""
        # In Bazel, data files are in the runfiles directory
        # Use the workspace root or relative paths that work in both Bazel and direct execution
        import os

        workspace_dir = Path(
            os.environ.get("BUILD_WORKSPACE_DIRECTORY", Path(__file__).parent.parent)
        )

        self.bulletin_files = [
            workspace_dir
            / "data"
            / "bulletin"
            / "saved_pages"
            / "visa-bulletin-for-march-2023.html",
            workspace_dir
            / "data"
            / "bulletin"
            / "saved_pages"
            / "visa-bulletin-for-february-2017.html",
            workspace_dir
            / "data"
            / "bulletin"
            / "saved_pages"
            / "visa-bulletin-for-october-2021.html",
        ]

    def test_country_from_header_all_chargeability_variations(self):
        """Test Country.from_header() matches various 'All Chargeability' header formats"""
        test_cases = [
            ("All Chargeability Areas Except Those Listed", Country.ALL),
            ("ALL CHARGEABILITY AREAS EXCEPT THOSE LISTED", Country.ALL),
            ("All Chargeability\nAreas Except\nThose Listed", Country.ALL),
            ("All Chargeability&nbsp;\n Areas Except\n Those Listed", Country.ALL),
            ("All Chargeability Areas Except", Country.ALL),  # Partial match
            ("ALL CHARGEABILITY EXCEPT", Country.ALL),  # Partial match
        ]

        for header, expected_country in test_cases:
            with self.subTest(header=header[:50]):
                result = Country.from_header(header)
                self.assertEqual(
                    result,
                    expected_country,
                    f"Header '{header[:50]}...' should match {expected_country.label}",
                )

    def test_country_from_header_does_not_match_other_countries(self):
        """Test that 'All Chargeability' pattern doesn't match country-specific headers"""
        test_cases = [
            "CHINA-mainland born",
            "INDIA",
            "MEXICO",
            "PHILIPPINES",
            "El Salvador/Guatemala/Honduras",
        ]

        for header in test_cases:
            with self.subTest(header=header):
                result = Country.from_header(header)
                self.assertNotEqual(
                    result,
                    Country.ALL,
                    f"Header '{header}' should NOT match Country.ALL",
                )

    def test_extract_headers_from_real_bulletin_html(self):
        """Test that headers are extracted correctly from real bulletin HTML files"""
        for file_path in self.bulletin_files:
            if not file_path.exists():
                continue

            with self.subTest(file=file_path.name):
                with open(file_path, encoding="utf-8") as f:
                    html = f.read()

                tables = extract_tables(html)
                self.assertGreater(
                    len(tables), 0, f"Should find tables in {file_path.name}"
                )

                # Find Family-Sponsored Final Action table
                family_table = None
                for table in tables:
                    if table.title == "family_sponsored_final_actions":
                        family_table = table
                        break

                if family_table:
                    # Check that headers exist
                    self.assertGreater(
                        len(family_table.headers), 0, "Table should have headers"
                    )

                    # Check that first header is visa class column (skip it)
                    country_headers = family_table.headers[1:]

                    # At least one country header should exist
                    self.assertGreater(
                        len(country_headers), 0, "Should have country headers"
                    )

                    # Check if "All Chargeability" header exists and can be matched
                    all_country_found = False
                    for header in country_headers:
                        normalized = normalize(header)
                        country = Country.from_header(normalized)
                        if country == Country.ALL:
                            all_country_found = True
                            break

                    self.assertTrue(
                        all_country_found,
                        f"'All Chargeability Areas' header not found or not matched in {file_path.name}. "
                        f"Headers: {country_headers[:3]}...",
                    )

    def test_extract_country_0_data_from_real_bulletin(self):
        """Test that Country.ALL (value 0) data is extracted from real bulletins"""
        for file_path in self.bulletin_files:
            if not file_path.exists():
                continue

            with self.subTest(file=file_path.name):
                with open(file_path, encoding="utf-8") as f:
                    html = f.read()

                tables = extract_tables(html)

                # Find Family-Sponsored Final Action table
                family_table = None
                for table in tables:
                    if table.title == "family_sponsored_final_actions":
                        family_table = table
                        break

                if not family_table:
                    continue

                # Extract data from table
                pub_data = PublicationData(
                    url=f"/test-{file_path.name}",
                    content=html,
                    publication_date=datetime(2025, 1, 1),
                )
                extractor = TableToCutoffData(pub_data)
                results = extractor.extract_from_table(family_table)

                # Check if Country.ALL data exists in results
                countries_in_data = {r["country"] for r in results}

                self.assertIn(
                    Country.ALL.value,
                    countries_in_data,
                    f"Country.ALL (value={Country.ALL.value}) should be in extracted data from {file_path.name}. "
                    f"Countries found: {countries_in_data}",
                )

    def test_parse_multi_line_html_header(self):
        """Test parsing headers that span multiple lines in HTML"""
        # Simulate the HTML structure from real bulletins
        html_with_multiline_header = """
        <table>
            <tr>
                <td><b>Family-<br>Sponsored&nbsp;</b></td>
                <td><b>All Chargeability&nbsp;<br>Areas Except<br>Those Listed</b></td>
                <td><b>CHINA-mainland&nbsp;<br>born</b></td>
                <td><b>INDIA</b></td>
            </tr>
            <tr>
                <td>F1</td>
                <td>22NOV15</td>
                <td>22NOV15</td>
                <td>22NOV15</td>
            </tr>
        </table>
        """

        soup = BeautifulSoup(html_with_multiline_header, "html.parser")
        header_row = soup.find("tr")

        # Extract headers using same method as parser
        headers = []
        for td in header_row.find_all("td"):
            header_text = td.get_text(separator=" ", strip=True)
            normalized = normalize(header_text)
            headers.append(normalized)

        # Check that "All Chargeability Areas" header is extracted correctly
        all_chargeability_header = headers[1]  # Second column
        self.assertIn("All Chargeability", all_chargeability_header)

        # Verify Country.from_header() can match it
        country = Country.from_header(all_chargeability_header)
        self.assertEqual(country, Country.ALL)

    def test_header_normalization_handles_special_chars(self):
        """Test that normalize() handles special HTML characters correctly"""
        test_cases = [
            ("All Chargeability&nbsp;Areas", "All Chargeability Areas"),
            ("All Chargeability\nAreas", "All Chargeability Areas"),
            ("All Chargeability  Areas", "All Chargeability Areas"),  # Multiple spaces
            ("All Chargeability\tAreas", "All Chargeability Areas"),  # Tabs
        ]

        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = normalize(input_text)
                # Should normalize to single spaces
                self.assertEqual(result, expected)

    def test_all_countries_extracted_from_headers(self):
        """Test that all expected countries are extracted from table headers"""
        expected_countries = [
            Country.ALL,
            Country.CHINA,
            Country.INDIA,
            Country.MEXICO,
            Country.PHILIPPINES,
        ]

        # Test with a real bulletin file
        file_path = self.bulletin_files[0]
        if not file_path.exists():
            self.skipTest(f"Bulletin file not found: {file_path}")

        with open(file_path, encoding="utf-8") as f:
            html = f.read()

        tables = extract_tables(html)

        # Find Family-Sponsored Final Action table
        family_table = None
        for table in tables:
            if table.title == "family_sponsored_final_actions":
                family_table = table
                break

        if not family_table:
            self.skipTest("Family table not found in bulletin")

        # Extract headers (skip first column which is visa class)
        country_headers = family_table.headers[1:]

        # Extract countries from headers
        extracted_countries = set()
        for header in country_headers:
            country = Country.from_header(header)
            if country:
                extracted_countries.add(country)

        # Check that all expected countries are present
        for expected_country in expected_countries:
            self.assertIn(
                expected_country,
                extracted_countries,
                f"{expected_country.label} not found in extracted countries. "
                f"Found: {[c.label for c in extracted_countries]}, "
                f"Headers: {country_headers[:5]}...",
            )


class TestCountryHeaderExtractionIntegration(unittest.TestCase):
    """Integration tests for end-to-end header extraction and country matching"""

    def setUp(self):
        """Set up test data"""
        import os

        workspace_dir = Path(
            os.environ.get("BUILD_WORKSPACE_DIRECTORY", Path(__file__).parent.parent)
        )
        self.bulletin_file = (
            workspace_dir
            / "data"
            / "bulletin"
            / "saved_pages"
            / "visa-bulletin-for-february-2017.html"
        )

    def test_extract_and_match_country_0_from_full_pipeline(self):
        """Test full pipeline: HTML → table → extract → country matching → data"""
        if not self.bulletin_file.exists():
            self.skipTest(f"Bulletin file not found: {self.bulletin_file}")

        with open(self.bulletin_file, encoding="utf-8") as f:
            html = f.read()

        # Step 1: Extract tables
        tables = extract_tables(html)
        self.assertGreater(len(tables), 0)

        # Step 2: Find Family-Sponsored Final Action table
        family_table = None
        for table in tables:
            if table.title == "family_sponsored_final_actions":
                family_table = table
                break

        self.assertIsNotNone(family_table, "Family table should be found")

        # Step 3: Extract data (use appropriate date based on file name)
        pub_date = datetime(2017, 2, 1)  # February 2017
        if "march-2023" in str(self.bulletin_file):
            pub_date = datetime(2023, 3, 1)
        elif "february-2017" in str(self.bulletin_file):
            pub_date = datetime(2017, 2, 1)

        pub_data = PublicationData(
            url="/test-url", content=html, publication_date=pub_date
        )
        extractor = TableToCutoffData(pub_data)
        results = extractor.extract_from_table(family_table)

        # Step 4: Verify Country.ALL data exists
        country_0_results = [r for r in results if r["country"] == Country.ALL.value]

        self.assertGreater(
            len(country_0_results),
            0,
            f"No Country.ALL (value={Country.ALL.value}) records found. "
            f"Total results: {len(results)}, "
            f"Countries in results: {set(r['country'] for r in results)}",
        )

        # Step 5: Verify at least one visa class has Country.ALL data
        visa_classes_with_all = {r["visa_class"] for r in country_0_results}
        self.assertGreater(len(visa_classes_with_all), 0)

    def test_country_all_is_not_treated_as_none(self):
        """
        Test that Country.ALL is correctly extracted and has value 1 (not 0).

        With 0 reserved for INVALID, Country.ALL is now 1, which means:
        - Truthiness checks work correctly: `if country:` filters out invalid (0) but keeps ALL (1)
        - No need for explicit None checks to avoid falsy bugs
        - This test verifies Country.ALL extraction still works correctly
        """
        from datetime import date

        from lib.parsing.bulletin.bulletin_table import BulletinTable

        # Create table with Country.ALL header (first country column)
        headers = (
            "Family- Sponsored",
            "All Chargeability Areas Except Those Listed",
            "CHINA-mainland born",
            "INDIA",
        )
        rows = [
            ("F1", date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 1)),
        ]
        table = BulletinTable("family_sponsored_final_actions", headers, rows)

        pub_data = PublicationData("/test-url", "<html></html>", datetime(2025, 12, 1))
        extractor = TableToCutoffData(pub_data)
        results = extractor.extract_from_table(table)

        # Verify Country.ALL records are extracted (not skipped)
        country_all_results = [r for r in results if r["country"] == Country.ALL.value]

        self.assertGreater(
            len(country_all_results),
            0,
            f"Country.ALL (value={Country.ALL.value}) records must be extracted.",
        )

        # Verify Country.ALL value is 1 (0 is reserved for INVALID)
        self.assertEqual(
            Country.ALL.value, 1, "Country.ALL.value is 1 (0 is reserved for INVALID)"
        )

        # Verify the extracted record has the correct country value
        f1_all = country_all_results[0]
        self.assertEqual(f1_all["country"], 1)
        self.assertEqual(f1_all["visa_class"], "F1")

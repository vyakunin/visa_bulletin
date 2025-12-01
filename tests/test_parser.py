import unittest
from datetime import date
from lib.bulletint_parser import extract_tables, extract_table, normalize
from bs4 import BeautifulSoup


class TestBulletinParser(unittest.TestCase):
    """
    Test suite for visa bulletin parser methods.
    Tests against 3 random saved pages to ensure parsing works correctly.
    """

    def setUp(self):
        """Load 3 random test HTML files"""
        self.test_files = [
            'saved_pages/visa-bulletin-for-february-2017.html',
            'saved_pages/visa-bulletin-for-march-2023.html',
            'saved_pages/visa-bulletin-for-october-2021.html'
        ]
        
        self.test_htmls = []
        for file_path in self.test_files:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.test_htmls.append(f.read())

    def test_normalize_whitespace(self):
        """Test normalize function handles various whitespace correctly"""
        # Fixed to match actual correct behavior
        self.assertEqual(normalize("  multiple   spaces  "), "multiple spaces")
        self.assertEqual(normalize("line\nbreak\nhere"), "line break here")
        self.assertEqual(normalize("tab\ttab\ttab"), "tab tab tab")
        
    def test_extract_tables_returns_list(self):
        """Test that extract_tables returns a list for all test files"""
        for i, html in enumerate(self.test_htmls):
            with self.subTest(file=self.test_files[i]):
                tables = extract_tables(html)
                # Fixed to expect list
                self.assertIsInstance(tables, list, f"Should return list for {self.test_files[i]}")

    def test_extract_tables_finds_four_tables(self):
        """Test that we extract exactly 4 tables from each bulletin"""
        for i, html in enumerate(self.test_htmls):
            with self.subTest(file=self.test_files[i]):
                tables = extract_tables(html)
                # Fixed to expect 4 tables
                self.assertEqual(len(tables), 4, 
                               f"Expected 4 tables in {self.test_files[i]}, got {len(tables)}")

    def test_table_titles_are_correct(self):
        """Test that extracted tables have correct standardized titles"""
        expected_titles = {
            'family_sponsored_final_actions',
            'family_sponsored_dates_for_filing',
            'employment_based_final_action',
            'employment_based_dates_for_filing'
        }
        
        for i, html in enumerate(self.test_htmls):
            with self.subTest(file=self.test_files[i]):
                tables = extract_tables(html)
                table_titles = {table.title for table in tables}
                # Fixed to expect correct titles
                self.assertEqual(table_titles, expected_titles, 
                               f"Unexpected table titles in {self.test_files[i]}: {table_titles}")

    def test_tables_have_headers(self):
        """Test that each table has headers"""
        for i, html in enumerate(self.test_htmls):
            with self.subTest(file=self.test_files[i]):
                tables = extract_tables(html)
                for table in tables:
                    # Fixed to expect headers
                    self.assertGreater(len(table.headers), 0, 
                                   f"Table {table.title} should have headers")

    def test_tables_have_rows(self):
        """Test that each table has data rows"""
        for i, html in enumerate(self.test_htmls):
            with self.subTest(file=self.test_files[i]):
                tables = extract_tables(html)
                for table in tables:
                    # Fixed to expect reasonable number of rows (typically 5-10)
                    self.assertGreater(len(table.rows), 0, 
                                     f"Table {table.title} should have at least 1 row in {self.test_files[i]}")

    def test_date_conversion(self):
        """Test that dates are properly converted to date objects"""
        # Test specific known data from march 2023
        html = self.test_htmls[1]  # march-2023
        tables = extract_tables(html)
        
        # Find the family sponsored final actions table
        family_final = None
        for table in tables:
            if table.title == 'family_sponsored_final_actions':
                family_final = table
                break
        
        self.assertIsNotNone(family_final, "Should find family_sponsored_final_actions table")
        
        # Check that F1 row exists and first date cell is converted correctly
        # From the HTML: F1 row has "01DEC14" which should be date(2014, 12, 1)
        f1_row = None
        for row in family_final.rows:
            if row[0] == 'F1':
                f1_row = row
                break
        
        self.assertIsNotNone(f1_row, "Should find F1 row")
        # Fixed to expect date object
        self.assertIsInstance(f1_row[1], date, "Date should be converted to date object")
        self.assertEqual(f1_row[1], date(2014, 12, 1), "F1 All Areas should be Dec 1, 2014")
        
    def test_current_status_preserved(self):
        """Test that 'C' (Current) status is preserved as string, not converted to date"""
        html = self.test_htmls[1]  # march-2023
        tables = extract_tables(html)
        
        family_final = None
        for table in tables:
            if table.title == 'family_sponsored_final_actions':
                family_final = table
                break
        
        # F2A row should have all 'C' values
        f2a_row = None
        for row in family_final.rows:
            if row[0] == 'F2A':
                f2a_row = row
                break
        
        self.assertIsNotNone(f2a_row, "Should find F2A row")
        # This should actually pass - 'C' should remain string
        self.assertEqual(f2a_row[1], 'C', "'C' should be preserved as string")

    def test_march_2023_specific_data(self):
        """Test specific known values from March 2023 bulletin"""
        html = self.test_htmls[1]  # march-2023
        tables = extract_tables(html)
        
        family_final = None
        for table in tables:
            if table.title == 'family_sponsored_final_actions':
                family_final = table
                break
        
        # Check F1 Mexico should be "01APR01" = date(2001, 4, 1)
        f1_row = None
        for row in family_final.rows:
            if row[0] == 'F1':
                f1_row = row
                break
        
        # Mexico should be in position 4 (0=category, 1=All, 2=China, 3=India, 4=Mexico)
        # Fixed to expect correct date
        self.assertEqual(f1_row[4], date(2001, 4, 1), 
                        f"F1 Mexico should be April 1, 2001, got {f1_row[4]}")


if __name__ == '__main__':
    unittest.main()


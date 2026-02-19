"""
Tests for wage unit parsing from DOL data files.

Tests the WageUnit.from_dol_value() method to ensure it correctly handles
all wage unit abbreviations found in DOL files.
"""

import unittest

from models.enums.visa_program import WageUnit


class TestWageUnitParsing(unittest.TestCase):
    """Test WageUnit.from_dol_value() parsing"""

    def test_parse_hour_variants(self):
        """Test parsing of hourly wage unit variants"""
        # Standard forms
        self.assertEqual(WageUnit.from_dol_value('HOUR'), WageUnit.HOUR)
        self.assertEqual(WageUnit.from_dol_value('HOURLY'), WageUnit.HOUR)

        # Abbreviation (found in PERM_FY2008.xlsx)
        self.assertEqual(WageUnit.from_dol_value('HR'), WageUnit.HOUR)

        # Case variations
        self.assertEqual(WageUnit.from_dol_value('hr'), WageUnit.HOUR)
        self.assertEqual(WageUnit.from_dol_value('Hr'), WageUnit.HOUR)
        self.assertEqual(WageUnit.from_dol_value('hour'), WageUnit.HOUR)
        self.assertEqual(WageUnit.from_dol_value('Hourly'), WageUnit.HOUR)

    def test_parse_year_variants(self):
        """Test parsing of annual wage unit variants"""
        self.assertEqual(WageUnit.from_dol_value('YEAR'), WageUnit.YEAR)
        self.assertEqual(WageUnit.from_dol_value('YEARLY'), WageUnit.YEAR)
        self.assertEqual(WageUnit.from_dol_value('YR'), WageUnit.YEAR)
        self.assertEqual(WageUnit.from_dol_value('year'), WageUnit.YEAR)

    def test_parse_month_variants(self):
        """Test parsing of monthly wage unit variants"""
        self.assertEqual(WageUnit.from_dol_value('MONTH'), WageUnit.MONTH)
        self.assertEqual(WageUnit.from_dol_value('MONTHLY'), WageUnit.MONTH)
        self.assertEqual(WageUnit.from_dol_value('MTH'), WageUnit.MONTH)
        self.assertEqual(WageUnit.from_dol_value('month'), WageUnit.MONTH)

    def test_parse_week_variants(self):
        """Test parsing of weekly wage unit variants"""
        self.assertEqual(WageUnit.from_dol_value('WEEK'), WageUnit.WEEK)
        self.assertEqual(WageUnit.from_dol_value('WEEKLY'), WageUnit.WEEK)
        self.assertEqual(WageUnit.from_dol_value('WK'), WageUnit.WEEK)
        self.assertEqual(WageUnit.from_dol_value('week'), WageUnit.WEEK)

    def test_parse_biweekly_variants(self):
        """Test parsing of bi-weekly wage unit variants"""
        self.assertEqual(WageUnit.from_dol_value('BI-WEEKLY'), WageUnit.BI_WEEKLY)
        self.assertEqual(WageUnit.from_dol_value('BIWEEKLY'), WageUnit.BI_WEEKLY)
        self.assertEqual(WageUnit.from_dol_value('BW'), WageUnit.BI_WEEKLY)
        self.assertEqual(WageUnit.from_dol_value('bi-weekly'), WageUnit.BI_WEEKLY)

    def test_parse_empty_or_none(self):
        """Test parsing of empty or None values"""
        self.assertIsNone(WageUnit.from_dol_value(None))
        self.assertIsNone(WageUnit.from_dol_value(''))
        self.assertIsNone(WageUnit.from_dol_value('  '))

    def test_parse_unknown_value(self):
        """Test parsing of unknown wage unit values"""
        self.assertIsNone(WageUnit.from_dol_value('UNKNOWN'))
        self.assertIsNone(WageUnit.from_dol_value('DAILY'))
        self.assertIsNone(WageUnit.from_dol_value('XYZ'))

    def test_whitespace_handling(self):
        """Test that whitespace is properly stripped"""
        self.assertEqual(WageUnit.from_dol_value('  HR  '), WageUnit.HOUR)
        self.assertEqual(WageUnit.from_dol_value(' YEAR '), WageUnit.YEAR)
        self.assertEqual(WageUnit.from_dol_value('\tMONTH\n'), WageUnit.MONTH)


class TestLowHourlyWageScenario(unittest.TestCase):
    """Test the specific scenario from ABBCO ROOFING case"""

    def test_abbco_roofing_scenario(self):
        """
        Test the ABBCO ROOFING scenario:
        - Source file has: WAGE_OFFER_UNIT_OF_PAY_9089 = 'HR'
        - wage_from = 8.26
        - Should be parsed as HOUR, not YEAR
        - Annual wage should be 8.26 * 2080 = $17,180.80
        """
        from decimal import Decimal

        from lib.parsing.salary.wage_unit_correction import calculate_annual_wage

        # Parse wage unit from source file
        wage_unit_raw = 'HR'
        wage_unit = WageUnit.from_dol_value(wage_unit_raw)

        # Should parse as HOUR
        self.assertEqual(wage_unit, WageUnit.HOUR)

        # Calculate annual wage
        wage_from = Decimal('8.26')
        wage_annual = calculate_annual_wage(wage_from, wage_unit)

        # Should be $17,180.80 (8.26 * 2080)
        expected_annual = Decimal('8.26') * 2080
        self.assertEqual(wage_annual, expected_annual)
        self.assertAlmostEqual(float(wage_annual), 17180.80, places=2)


if __name__ == '__main__':
    unittest.main()


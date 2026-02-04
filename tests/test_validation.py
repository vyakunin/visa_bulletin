"""Tests for data validation logic and fix scripts"""

from tests.django_setup import setup_django_for_tests
setup_django_for_tests()

from decimal import Decimal
from django.test import TestCase
from django.db import transaction

from models.salary import Employer, SalaryRecord
from models.enums.visa_program import VisaProgram, WageUnit, CaseStatus
from lib.utils.location_utils import VALID_STATES, is_valid_state
from lib.parsing.salary.wage_unit_correction import (
    should_correct_wage_unit,
    correct_wage_unit,
    should_flag_for_review,
    calculate_annual_wage,
    MIN_ANNUAL,
    MAX_ANNUAL,
    HOURS_PER_YEAR,
)
# Import from scripts - these will set up Django, but that's OK since we're in a test
# Note: Django setup in these modules is idempotent
try:
    from scripts.salary.fix_state_codes import (
        normalize_state_code,
        suggest_fix,
    )
    from scripts.salary.cleanup_orphaned_employers import (
        find_orphaned_employers,
    )
except ImportError:
    # Fallback for direct execution (not via Bazel)
    import sys
    from pathlib import Path
    scripts_path = Path(__file__).parent.parent / 'scripts' / 'salary'
    sys.path.insert(0, str(scripts_path.parent.parent))
    from scripts.salary.fix_state_codes import (
        normalize_state_code,
        suggest_fix,
    )
    from scripts.salary.cleanup_orphaned_employers import (
        find_orphaned_employers,
    )


class TestStateCodeValidation(TestCase):
    """Test state code validation and fixing logic"""
    
    def test_valid_state_codes(self):
        """Test that valid state codes pass validation"""
        for state in ['CA', 'NY', 'TX', 'FL', 'DC']:
            self.assertTrue(is_valid_state(state), f"{state} should be valid")
            self.assertTrue(is_valid_state(state.lower()), f"{state.lower()} should be valid (case-insensitive)")
    
    def test_invalid_state_codes(self):
        """Test that invalid state codes fail validation"""
        invalid_states = ['XX', 'ZZ', 'AB', 'XY', 'INVALID']
        for state in invalid_states:
            self.assertFalse(is_valid_state(state), f"{state} should be invalid")
    
    def test_normalize_state_code(self):
        """Test state code normalization"""
        from scripts.salary.fix_state_codes import normalize_state_code
        
        self.assertEqual(normalize_state_code('ca'), 'CA')
        self.assertEqual(normalize_state_code('CA'), 'CA')
        self.assertEqual(normalize_state_code('  ca  '), 'CA')
        self.assertIsNone(normalize_state_code(None))
        self.assertIsNone(normalize_state_code(''))
    
    def test_suggest_fix_common_typos(self):
        """Test that common typos are fixed correctly"""
        # Common typos
        self.assertEqual(suggest_fix('Califonia'), 'CA')
        self.assertEqual(suggest_fix('Californa'), 'CA')
        self.assertEqual(suggest_fix('Massachusets'), 'MA')
        self.assertEqual(suggest_fix('New York'), 'NY')
        self.assertEqual(suggest_fix('New Jersey'), 'NJ')
    
    def test_suggest_fix_abbreviations(self):
        """Test that abbreviations are fixed correctly"""
        self.assertEqual(suggest_fix('Calif'), 'CA')
        self.assertEqual(suggest_fix('Fla'), 'FL')
        self.assertEqual(suggest_fix('Tex'), 'TX')
        self.assertEqual(suggest_fix('Penn'), 'PA')
    
    def test_suggest_fix_state_names(self):
        """Test that full state names are converted to codes"""
        self.assertEqual(suggest_fix('California'), 'CA')
        self.assertEqual(suggest_fix('New York'), 'NY')
        self.assertEqual(suggest_fix('Texas'), 'TX')
        self.assertEqual(suggest_fix('Florida'), 'FL')
    
    def test_suggest_fix_case_insensitive(self):
        """Test that fixes work case-insensitively"""
        self.assertEqual(suggest_fix('california'), 'CA')
        self.assertEqual(suggest_fix('CALIFORNIA'), 'CA')
        self.assertEqual(suggest_fix('CaLiFoRnIa'), 'CA')
    
    def test_suggest_fix_already_valid(self):
        """Test that already valid codes return as-is"""
        self.assertEqual(suggest_fix('CA'), 'CA')
        self.assertEqual(suggest_fix('NY'), 'NY')
        self.assertEqual(suggest_fix('TX'), 'TX')
    
    def test_suggest_fix_no_fix_available(self):
        """Test that invalid codes with no fix return None"""
        self.assertIsNone(suggest_fix('XX'))
        self.assertIsNone(suggest_fix('INVALID'))
        self.assertIsNone(suggest_fix('123'))


class TestOrphanedEmployerDetection(TestCase):
    """Test orphaned employer detection logic"""
    
    def setUp(self):
        """Set up test data"""
        # Create employers
        self.employer_with_records = Employer.objects.create(
            name='Company With Records',
            city='San Francisco',
            state='CA'
        )
        self.orphaned_employer = Employer.objects.create(
            name='Orphaned Company',
            city='New York',
            state='NY'
        )
        
        # Create salary record for one employer
        SalaryRecord.objects.create(
            case_number='TEST-001',
            employer=self.employer_with_records,
            employer_name='Company With Records',
            job_title='Software Engineer',
            wage_from=Decimal('150000'),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal('150000'),
            worksite_state='CA',
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )
    
    def test_find_orphaned_employers(self):
        """Test that orphaned employers are correctly identified"""
        orphaned = find_orphaned_employers()
        orphaned_ids = set(orphaned.values_list('id', flat=True))
        
        self.assertIn(self.orphaned_employer.id, orphaned_ids)
        self.assertNotIn(self.employer_with_records.id, orphaned_ids)
    
    def test_no_orphaned_employers_when_all_have_records(self):
        """Test that no orphaned employers are found when all have records"""
        # Create record for orphaned employer
        SalaryRecord.objects.create(
            case_number='TEST-002',
            employer=self.orphaned_employer,
            employer_name='Orphaned Company',
            job_title='Engineer',
            wage_from=Decimal('100000'),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal('100000'),
            worksite_state='NY',
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )
        
        orphaned = find_orphaned_employers()
        self.assertEqual(orphaned.count(), 0)


class TestWageUnitCorrectionEdgeCases(TestCase):
    """Test edge cases for wage unit correction"""
    
    def test_high_hourly_rate_detection(self):
        """Test that unrealistic hourly rates are detected"""
        # $600/hour should trigger correction (threshold is $500)
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('600'),
            wage_unit=WageUnit.HOUR,
            wage_annual=Decimal('1248000')  # $600 * 2080 hours
        )
        self.assertTrue(should_correct, "Hourly rate > $500 should trigger correction")
    
    def test_high_monthly_rate_detection(self):
        """Test that unrealistic monthly rates are detected"""
        # $60K/month should trigger correction (threshold is $50K)
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('60000'),
            wage_unit=WageUnit.MONTH,
            wage_annual=Decimal('720000')
        )
        self.assertTrue(should_correct, "Monthly rate > $50K should trigger correction")
    
    def test_high_weekly_rate_detection(self):
        """Test that unrealistic weekly rates are detected"""
        # $25K/week should trigger correction (threshold is $20K)
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('25000'),
            wage_unit=WageUnit.WEEK,
            wage_annual=Decimal('1300000')
        )
        self.assertTrue(should_correct, "Weekly rate > $20K should trigger correction")
    
    def test_implied_hourly_rate_check(self):
        """Test that implied hourly rate is checked even if wage_from is reasonable"""
        # wage_from is $100/hour (reasonable), but wage_annual implies $600/hour
        # This catches cases where wage_from and wage_annual don't match
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('100'),
            wage_unit=WageUnit.HOUR,
            wage_annual=Decimal('1248000')  # Implies $600/hour
        )
        self.assertTrue(should_correct, "Implied hourly rate > $500 should trigger correction")
    
    def test_legitimate_high_salary_not_corrected(self):
        """Test that legitimate high salaries are not incorrectly corrected"""
        # $500K/year is high but legitimate
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('500000'),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal('500000')
        )
        self.assertFalse(should_correct, "Legitimate high annual salary should not be corrected")
    
    def test_legitimate_hourly_rate_not_corrected(self):
        """Test that legitimate hourly rates are not incorrectly corrected"""
        # $200/hour is high but legitimate for some roles
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('200'),
            wage_unit=WageUnit.HOUR,
            wage_annual=Decimal('416000')  # $200 * 2080 hours
        )
        self.assertFalse(should_correct, "Legitimate hourly rate < $500 should not be corrected")
    
    def test_boundary_case_at_threshold(self):
        """Test behavior at threshold boundaries"""
        # Exactly at threshold ($500/hour) - should trigger (>= threshold)
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('500'),
            wage_unit=WageUnit.HOUR,
            wage_annual=Decimal('1040000')
        )
        self.assertTrue(should_correct, "Exactly at threshold should trigger correction")
        
        # Just below threshold ($499/hour) - should not trigger
        should_correct = should_correct_wage_unit(
            wage_from=Decimal('499'),
            wage_unit=WageUnit.HOUR,
            wage_annual=Decimal('1037920')
        )
        self.assertFalse(should_correct, "Just below threshold should not trigger correction")
    
    def test_should_flag_for_review_high_wage(self):
        """Test that extremely high wages are flagged for review"""
        flagged, reason = should_flag_for_review(
            wage_annual=Decimal('2000000'),  # $2M
            wage_unit=WageUnit.YEAR
        )
        self.assertTrue(flagged, "Wage > $1M should be flagged")
        self.assertIn('exceeds', reason.lower() if reason else '')
    
    def test_low_annual_treated_as_hourly(self):
        """Test that very low annual (e.g. $29/year) is auto-corrected to HOUR so row is kept"""
        unit = correct_wage_unit(
            wage_from=Decimal('29'),
            wage_unit=WageUnit.YEAR,
            row_num=0,
        )
        self.assertEqual(unit, WageUnit.HOUR, "29 with unit YEAR should be corrected to HOUR")
        wage_annual = calculate_annual_wage(Decimal('29'), WageUnit.HOUR)
        self.assertEqual(float(wage_annual), 29 * HOURS_PER_YEAR)
        self.assertGreaterEqual(float(wage_annual), MIN_ANNUAL)
        self.assertLessEqual(float(wage_annual), MAX_ANNUAL)

    def test_low_annual_treated_as_weekly_when_hourly_exceeds_max(self):
        """Test that when HOUR would exceed MAX_ANNUAL, next unit (WEEK) is used"""
        # 1000/year invalid; 1000/hour = 2.08M > MAX_ANNUAL; 1000/week = 52k in range
        unit = correct_wage_unit(
            wage_from=Decimal('1000'),
            wage_unit=WageUnit.YEAR,
            row_num=0,
        )
        self.assertEqual(unit, WageUnit.WEEK, "1000 with unit YEAR should be corrected to WEEK (HOUR would exceed max)")
        wage_annual = calculate_annual_wage(Decimal('1000'), WageUnit.WEEK)
        self.assertGreaterEqual(float(wage_annual), MIN_ANNUAL)
        self.assertLessEqual(float(wage_annual), MAX_ANNUAL)

    def test_should_flag_for_review_low_wage(self):
        """Test that extremely low wages are flagged for review"""
        flagged, reason = should_flag_for_review(
            wage_annual=Decimal('15000'),  # $15K
            wage_unit=WageUnit.YEAR
        )
        self.assertTrue(flagged, "Wage < $20K should be flagged")
        self.assertIn('below', reason.lower() if reason else '')
    
    def test_should_flag_for_review_legitimate_wage(self):
        """Test that legitimate wages are not flagged"""
        flagged, reason = should_flag_for_review(
            wage_annual=Decimal('100000'),  # $100K
            wage_unit=WageUnit.YEAR
        )
        self.assertFalse(flagged, "Legitimate wage should not be flagged")
    
    def test_should_flag_for_review_hourly_unit(self):
        """Test that hourly wages are handled correctly"""
        # $50/hour * 2080 = $104K annual - legitimate
        flagged, reason = should_flag_for_review(
            wage_annual=Decimal('104000'),
            wage_unit=WageUnit.HOUR
        )
        self.assertFalse(flagged, "Legitimate hourly wage should not be flagged")


class TestValidationIntegration(TestCase):
    """Integration tests for validation logic"""
    
    def setUp(self):
        """Set up test data with various issues"""
        self.employer = Employer.objects.create(
            name='Test Employer',
            city='San Francisco',
            state='CA'
        )
    
    def test_high_wage_record_validation(self):
        """Test that high wage records are detected"""
        record = SalaryRecord.objects.create(
            case_number='HIGH-001',
            employer=self.employer,
            employer_name='Test Employer',
            job_title='Engineer',
            wage_from=Decimal('2000000'),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal('2000000'),
            worksite_state='CA',
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )
        
        # Should be flagged for review
        flagged, reason = should_flag_for_review(record.wage_annual, record.wage_unit)
        self.assertTrue(flagged, "High wage record should be flagged")
    
    def test_low_wage_record_validation(self):
        """Test that low wage records are detected"""
        record = SalaryRecord.objects.create(
            case_number='LOW-001',
            employer=self.employer,
            employer_name='Test Employer',
            job_title='Engineer',
            wage_from=Decimal('15000'),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal('15000'),
            worksite_state='CA',
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )
        
        # Should be flagged for review
        flagged, reason = should_flag_for_review(record.wage_annual, record.wage_unit)
        self.assertTrue(flagged, "Low wage record should be flagged")
    
    def test_invalid_state_code_validation(self):
        """Test that invalid state codes are detected"""
        record = SalaryRecord.objects.create(
            case_number='STATE-001',
            employer=self.employer,
            employer_name='Test Employer',
            job_title='Engineer',
            wage_from=Decimal('100000'),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal('100000'),
            worksite_state='XX',  # Invalid state
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )
        
        # Should be invalid
        self.assertFalse(is_valid_state(record.worksite_state), "Invalid state should be detected")
        
        # Should suggest a fix if available
        fix = suggest_fix(record.worksite_state)
        # 'XX' has no fix, so should return None
        self.assertIsNone(fix, "Invalid state with no fix should return None")
    
    def test_orphaned_employer_validation(self):
        """Test that orphaned employers are detected"""
        orphaned = Employer.objects.create(
            name='Orphaned Employer',
            city='New York',
            state='NY'
        )
        
        # Should be found as orphaned
        orphaned_list = find_orphaned_employers()
        orphaned_ids = set(orphaned_list.values_list('id', flat=True))
        self.assertIn(orphaned.id, orphaned_ids, "Orphaned employer should be detected")








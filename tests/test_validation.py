"""Tests for data validation logic and fix scripts"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from decimal import Decimal

from django.test import TestCase

from lib.parsing.salary.wage_unit_correction import (
    HOURS_PER_YEAR,
    MAX_ANNUAL,
    MIN_ANNUAL,
    calculate_annual_wage,
    correct_wage_unit,
    should_correct_wage_unit,
    validate_wage_annual,
)
from lib.utils.location_utils import is_valid_state
from models.enums.visa_program import CaseStatus, VisaProgram, WageUnit
from models.salary import Employer, SalaryRecord

# Import from scripts - these will set up Django, but that's OK since we're in a test
# Note: Django setup in these modules is idempotent
try:
    from scripts.salary.cleanup_orphaned_employers import (
        find_orphaned_employers,
    )
    from scripts.salary.fix_state_codes import (
        suggest_fix,
    )
except ImportError:
    # Fallback for direct execution (not via Bazel)
    import sys
    from pathlib import Path

    scripts_path = Path(__file__).parent.parent / "scripts" / "salary"
    sys.path.insert(0, str(scripts_path.parent.parent))
    from scripts.salary.cleanup_orphaned_employers import (
        find_orphaned_employers,
    )
    from scripts.salary.fix_state_codes import (
        suggest_fix,
    )


class TestStateCodeValidation(TestCase):
    """Test state code validation and fixing logic"""

    def test_valid_state_codes(self):
        """Test that valid state codes pass validation"""
        for state in ["CA", "NY", "TX", "FL", "DC"]:
            self.assertTrue(is_valid_state(state), f"{state} should be valid")
            self.assertTrue(
                is_valid_state(state.lower()),
                f"{state.lower()} should be valid (case-insensitive)",
            )

    def test_invalid_state_codes(self):
        """Test that invalid state codes fail validation"""
        invalid_states = ["XX", "ZZ", "AB", "XY", "INVALID"]
        for state in invalid_states:
            self.assertFalse(is_valid_state(state), f"{state} should be invalid")

    def test_normalize_state_code(self):
        """Test state code normalization"""
        from scripts.salary.fix_state_codes import normalize_state_code

        self.assertEqual(normalize_state_code("ca"), "CA")
        self.assertEqual(normalize_state_code("CA"), "CA")
        self.assertEqual(normalize_state_code("  ca  "), "CA")
        self.assertIsNone(normalize_state_code(None))
        self.assertIsNone(normalize_state_code(""))

    def test_suggest_fix_common_typos(self):
        """Test that common typos are fixed correctly"""
        # Common typos
        self.assertEqual(suggest_fix("Califonia"), "CA")
        self.assertEqual(suggest_fix("Californa"), "CA")
        self.assertEqual(suggest_fix("Massachusets"), "MA")
        self.assertEqual(suggest_fix("New York"), "NY")
        self.assertEqual(suggest_fix("New Jersey"), "NJ")

    def test_suggest_fix_abbreviations(self):
        """Test that abbreviations are fixed correctly"""
        self.assertEqual(suggest_fix("Calif"), "CA")
        self.assertEqual(suggest_fix("Fla"), "FL")
        self.assertEqual(suggest_fix("Tex"), "TX")
        self.assertEqual(suggest_fix("Penn"), "PA")

    def test_suggest_fix_state_names(self):
        """Test that full state names are converted to codes"""
        self.assertEqual(suggest_fix("California"), "CA")
        self.assertEqual(suggest_fix("New York"), "NY")
        self.assertEqual(suggest_fix("Texas"), "TX")
        self.assertEqual(suggest_fix("Florida"), "FL")

    def test_suggest_fix_case_insensitive(self):
        """Test that fixes work case-insensitively"""
        self.assertEqual(suggest_fix("california"), "CA")
        self.assertEqual(suggest_fix("CALIFORNIA"), "CA")
        self.assertEqual(suggest_fix("CaLiFoRnIa"), "CA")

    def test_suggest_fix_already_valid(self):
        """Test that already valid codes return as-is"""
        self.assertEqual(suggest_fix("CA"), "CA")
        self.assertEqual(suggest_fix("NY"), "NY")
        self.assertEqual(suggest_fix("TX"), "TX")

    def test_suggest_fix_no_fix_available(self):
        """Test that invalid codes with no fix return None"""
        self.assertIsNone(suggest_fix("XX"))
        self.assertIsNone(suggest_fix("INVALID"))
        self.assertIsNone(suggest_fix("123"))


class TestOrphanedEmployerDetection(TestCase):
    """Test orphaned employer detection logic"""

    def setUp(self):
        """Set up test data"""
        # Create employers
        self.employer_with_records = Employer.objects.create(
            name="Company With Records", city="San Francisco", state="CA"
        )
        self.orphaned_employer = Employer.objects.create(
            name="Orphaned Company", city="New York", state="NY"
        )

        # Create salary record for one employer
        SalaryRecord.objects.create(
            case_number="TEST-001",
            employer=self.employer_with_records,
            employer_name="Company With Records",
            job_title="Software Engineer",
            wage_from=Decimal("150000"),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal("150000"),
            worksite_state="CA",
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )

    def test_find_orphaned_employers(self):
        """Test that orphaned employers are correctly identified"""
        orphaned = find_orphaned_employers()
        orphaned_ids = set(orphaned.values_list("id", flat=True))

        self.assertIn(self.orphaned_employer.id, orphaned_ids)
        self.assertNotIn(self.employer_with_records.id, orphaned_ids)

    def test_no_orphaned_employers_when_all_have_records(self):
        """Test that no orphaned employers are found when all have records"""
        # Create record for orphaned employer
        SalaryRecord.objects.create(
            case_number="TEST-002",
            employer=self.orphaned_employer,
            employer_name="Orphaned Company",
            job_title="Engineer",
            wage_from=Decimal("100000"),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal("100000"),
            worksite_state="NY",
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )

        orphaned = find_orphaned_employers()
        self.assertEqual(orphaned.count(), 0)


class TestWageUnitCorrectionEdgeCases(TestCase):
    """Test edge cases for wage unit correction"""

    # NOTE (2026-06-20, ticket 38462b8d): should_correct_wage_unit was redesigned
    # to key off the single data-driven range [MIN_ANNUAL, MAX_ANNUAL] instead of
    # arbitrary per-unit magic thresholds ($500/hr, $50K/mo, $20K/wk). It now only
    # flips a sub-annual unit to YEAR when the implied annual leaves the range AND
    # wage_from is itself plausible as an annual figure. Unrealistic rates whose
    # wage_from is NOT plausible-as-annual are no longer "corrected" — instead
    # their implied annual exceeds MAX_ANNUAL and validate_wage_annual rejects the
    # row. The tests below assert that current (intended) contract.

    def test_high_hourly_rate_rejected_by_validation(self):
        """Unrealistic hourly rate is filtered by validation, not unit-correction.

        $600/hr is not plausible as an annual figure ($600 < MIN_ANNUAL), so the
        unit is NOT flipped to YEAR. Its implied annual ($1.248M) exceeds
        MAX_ANNUAL, so validate_wage_annual rejects the row.
        """
        self.assertFalse(
            should_correct_wage_unit(Decimal("600"), WageUnit.HOUR),
            "$600/hr is not plausible as annual, so unit is not flipped",
        )
        annual = calculate_annual_wage(Decimal("600"), WageUnit.HOUR)
        self.assertEqual(float(annual), 600 * HOURS_PER_YEAR)
        is_valid, reason = validate_wage_annual(annual)
        self.assertFalse(is_valid, "Implied annual above MAX should fail validation")
        self.assertIn("exceeds", (reason or "").lower())

    def test_high_monthly_within_range_is_kept(self):
        """A high-but-in-range monthly rate is kept, not clobbered.

        $60K/month = $720K/yr is within [MIN_ANNUAL, MAX_ANNUAL] — a legitimate
        executive salary. The old code force-flipped it to YEAR on a $50K/mo magic
        threshold (a false positive); the redesign correctly leaves it alone.
        """
        self.assertFalse(
            should_correct_wage_unit(Decimal("60000"), WageUnit.MONTH),
            "$720K/yr is within range and must not be corrected",
        )
        annual = calculate_annual_wage(Decimal("60000"), WageUnit.MONTH)
        is_valid, _ = validate_wage_annual(annual)
        self.assertTrue(is_valid, "$720K/yr is a valid annual wage")

    def test_high_monthly_down_corrected_when_plausible_as_annual(self):
        """Down-correction still fires when wage_from is plausible as annual.

        $90K/month implies $1.08M/yr (> MAX_ANNUAL), but $90K is itself a plausible
        annual salary, so the unit is corrected MONTH -> YEAR.
        """
        self.assertTrue(
            should_correct_wage_unit(Decimal("90000"), WageUnit.MONTH),
            "$90K/mo implies out-of-range annual but $90K is plausible as YEAR",
        )
        self.assertEqual(
            correct_wage_unit(Decimal("90000"), WageUnit.MONTH, row_num=0),
            WageUnit.YEAR,
        )

    def test_high_weekly_rate_detection(self):
        """Unrealistic weekly rate whose value is plausible as annual -> YEAR.

        $25K/week implies $1.3M/yr (> MAX_ANNUAL); $25K is plausible as an annual
        figure, so the unit is corrected WEEK -> YEAR.
        """
        self.assertTrue(
            should_correct_wage_unit(Decimal("25000"), WageUnit.WEEK),
            "$25K/wk implies out-of-range annual but $25K is plausible as YEAR",
        )

    def test_wage_annual_param_is_ignored(self):
        """The wage_annual argument is ignored; correction derives from wage_from.

        $100/hr implies a reasonable $208K/yr (in range), so the unit is not
        flipped — regardless of a bogus wage_annual passed in. (The redesign
        dropped the old wage_from/wage_annual cross-check; wage_annual is a derived
        value, not a trusted input.)
        """
        self.assertFalse(
            should_correct_wage_unit(
                Decimal("100"), WageUnit.HOUR, wage_annual=Decimal("1248000")
            ),
            "wage_annual is ignored; $100/hr implies in-range annual",
        )

    def test_legitimate_high_salary_not_corrected(self):
        """Test that legitimate high salaries are not incorrectly corrected"""
        # $500K/year is high but legitimate
        should_correct = should_correct_wage_unit(
            wage_from=Decimal("500000"),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal("500000"),
        )
        self.assertFalse(
            should_correct, "Legitimate high annual salary should not be corrected"
        )

    def test_legitimate_hourly_rate_not_corrected(self):
        """Test that legitimate hourly rates are not incorrectly corrected"""
        # $200/hour is high but legitimate for some roles
        should_correct = should_correct_wage_unit(
            wage_from=Decimal("200"),
            wage_unit=WageUnit.HOUR,
            wage_annual=Decimal("416000"),  # $200 * 2080 hours
        )
        self.assertFalse(
            should_correct, "Legitimate hourly rate < $500 should not be corrected"
        )

    def test_boundary_at_min_annual(self):
        """Boundary is the data-driven MIN_ANNUAL, not a $500/hr magic number.

        A YEAR unit with wage_from at/above MIN_ANNUAL is a valid annual and kept;
        just below MIN_ANNUAL it is re-interpreted to a sub-annual unit so the row
        is preserved rather than dropped.
        """
        self.assertEqual(
            correct_wage_unit(Decimal(str(MIN_ANNUAL)), WageUnit.YEAR, row_num=0),
            WageUnit.YEAR,
            "wage_from == MIN_ANNUAL is a valid annual; keep YEAR",
        )
        self.assertNotEqual(
            correct_wage_unit(Decimal(str(MIN_ANNUAL - 1)), WageUnit.YEAR, row_num=0),
            WageUnit.YEAR,
            "below MIN_ANNUAL, YEAR is re-interpreted to a sub-annual unit",
        )

    def test_low_annual_treated_as_hourly(self):
        """Test that very low annual (e.g. $29/year) is auto-corrected to HOUR so row is kept"""
        unit = correct_wage_unit(
            wage_from=Decimal("29"),
            wage_unit=WageUnit.YEAR,
            row_num=0,
        )
        self.assertEqual(
            unit, WageUnit.HOUR, "29 with unit YEAR should be corrected to HOUR"
        )
        wage_annual = calculate_annual_wage(Decimal("29"), WageUnit.HOUR)
        self.assertEqual(float(wage_annual), 29 * HOURS_PER_YEAR)
        self.assertGreaterEqual(float(wage_annual), MIN_ANNUAL)
        self.assertLessEqual(float(wage_annual), MAX_ANNUAL)

    def test_low_annual_treated_as_weekly_when_hourly_exceeds_max(self):
        """Test that when HOUR would exceed MAX_ANNUAL, next unit (WEEK) is used"""
        # 1000/year invalid; 1000/hour = 2.08M > MAX_ANNUAL; 1000/week = 52k in range
        unit = correct_wage_unit(
            wage_from=Decimal("1000"),
            wage_unit=WageUnit.YEAR,
            row_num=0,
        )
        self.assertEqual(
            unit,
            WageUnit.WEEK,
            "1000 with unit YEAR should be corrected to WEEK (HOUR would exceed max)",
        )
        wage_annual = calculate_annual_wage(Decimal("1000"), WageUnit.WEEK)
        self.assertGreaterEqual(float(wage_annual), MIN_ANNUAL)
        self.assertLessEqual(float(wage_annual), MAX_ANNUAL)


class TestValidationIntegration(TestCase):
    """Integration tests for validation logic"""

    def setUp(self):
        """Set up test data with various issues"""
        self.employer = Employer.objects.create(
            name="Test Employer", city="San Francisco", state="CA"
        )

    def test_high_wage_record_validation(self):
        """Test that high wage records are detected"""
        record = SalaryRecord.objects.create(
            case_number="HIGH-001",
            employer=self.employer,
            employer_name="Test Employer",
            job_title="Engineer",
            wage_from=Decimal("2000000"),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal("2000000"),
            worksite_state="CA",
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )

        # Should fail validation (rejected at import)
        is_valid, reason = validate_wage_annual(record.wage_annual)
        self.assertFalse(is_valid, "High wage record should fail validation")
        self.assertIn("exceeds", reason.lower() if reason else "")

    def test_low_but_above_min_wage_passes_validation(self):
        """A low-but-above-MIN annual wage is valid (real part-time / low-COL wage).

        $15K/yr is above the data-driven MIN_ANNUAL ($5000). The old code rejected
        it on a higher arbitrary minimum (a false positive that dropped legitimate
        low wages); the redesigned validation correctly accepts it.
        """
        record = SalaryRecord.objects.create(
            case_number="LOW-001",
            employer=self.employer,
            employer_name="Test Employer",
            job_title="Engineer",
            wage_from=Decimal("15000"),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal("15000"),
            worksite_state="CA",
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )
        is_valid, _ = validate_wage_annual(record.wage_annual)
        self.assertTrue(is_valid, "$15K/yr is above MIN_ANNUAL and should be valid")

    def test_below_min_wage_rejected(self):
        """An annual wage below MIN_ANNUAL is rejected as a likely data error."""
        is_valid, reason = validate_wage_annual(Decimal(str(MIN_ANNUAL - 1)))
        self.assertFalse(is_valid, "Wage below MIN_ANNUAL should fail validation")
        self.assertIn("below", (reason or "").lower())

    def test_invalid_state_code_validation(self):
        """Test that invalid state codes are detected"""
        record = SalaryRecord.objects.create(
            case_number="STATE-001",
            employer=self.employer,
            employer_name="Test Employer",
            job_title="Engineer",
            wage_from=Decimal("100000"),
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal("100000"),
            worksite_state="XX",  # Invalid state
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
        )

        # Should be invalid
        self.assertFalse(
            is_valid_state(record.worksite_state), "Invalid state should be detected"
        )

        # Should suggest a fix if available
        fix = suggest_fix(record.worksite_state)
        # 'XX' has no fix, so should return None
        self.assertIsNone(fix, "Invalid state with no fix should return None")

    def test_orphaned_employer_validation(self):
        """Test that orphaned employers are detected"""
        orphaned = Employer.objects.create(
            name="Orphaned Employer", city="New York", state="NY"
        )

        # Should be found as orphaned
        orphaned_list = find_orphaned_employers()
        orphaned_ids = set(orphaned_list.values_list("id", flat=True))
        self.assertIn(orphaned.id, orphaned_ids, "Orphaned employer should be detected")

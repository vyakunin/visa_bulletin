"""Tests for EmploymentPreference enum normalization"""

import unittest
from models.enums.employment_preference import EmploymentPreference


class TestEmploymentPreferenceNormalization(unittest.TestCase):
    """Test visa class normalization for display"""
    
    def test_exact_enum_match(self):
        """Test that exact enum values return their labels"""
        self.assertEqual(
            EmploymentPreference.normalize_for_display("1st"),
            "EB-1: Priority Workers"
        )
        self.assertEqual(
            EmploymentPreference.normalize_for_display("2nd"),
            "EB-2: Professionals with Advanced Degrees"
        )
        self.assertEqual(
            EmploymentPreference.normalize_for_display("Other Workers"),
            "EB-3: Other Workers"
        )
    
    def test_historical_eb5_variations(self):
        """Test normalization of historical EB-5 variations"""
        # Rural variations
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Set Aside: (Rural - 20%)"),
            "EB-5: Rural (20%)"
        )
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Set Aside: (Rural: NR, RR - 20%)"),
            "EB-5: Rural (20%)"
        )
        
        # High Unemployment variations
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Set Aside: (High Unemployment - 10%)"),
            "EB-5: High Unemployment (10%)"
        )
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Set Aside: High Unemployment (10%, including NH, RH)"),
            "EB-5: High Unemployment (10%)"
        )
        
        # Infrastructure variations
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Set Aside: (Infrastructure - 2%)"),
            "EB-5: Infrastructure (2%)"
        )
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Set Aside: Infrastructure (2%, including RI)"),
            "EB-5: Infrastructure (2%)"
        )
        
        # Unreserved variations
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Unreserved (C5, T5, and all others)"),
            "EB-5: Unreserved"
        )
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Non-Regional Center (C5 and T5)"),
            "EB-5: Unreserved"
        )
    
    def test_case_insensitive_matching(self):
        """Test that matching works regardless of case"""
        self.assertEqual(
            EmploymentPreference.normalize_for_display("5th Set Aside: RURAL (20%)"),
            "EB-5: Rural (20%)"
        )
        self.assertEqual(
            EmploymentPreference.normalize_for_display("Certain RELIGIOUS Workers"),
            "EB-4: Religious Workers"
        )
    
    def test_religious_workers(self):
        """Test religious workers subcategory"""
        self.assertEqual(
            EmploymentPreference.normalize_for_display("Certain Religious Workers"),
            "EB-4: Religious Workers"
        )
    
    def test_unknown_visa_class_returns_as_is(self):
        """Test that unknown visa classes are returned unchanged"""
        unknown = "Unknown Visa Class XYZ"
        self.assertEqual(
            EmploymentPreference.normalize_for_display(unknown),
            unknown
        )
    
    def test_all_enum_members_have_labels(self):
        """Test that all enum members have proper labels"""
        for member in EmploymentPreference:
            self.assertIsInstance(member.value, str)
            self.assertIsInstance(member.label, str)
            self.assertTrue(member.label.startswith("EB-"))


if __name__ == '__main__':
    unittest.main()


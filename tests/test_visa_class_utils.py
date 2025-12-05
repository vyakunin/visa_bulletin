"""Tests for visa class utility functions"""

import unittest

# Django setup (shared utility for both Bazel and pytest)
from tests.django_setup import setup_django_for_tests
setup_django_for_tests()
from lib.visa_class_utils import get_deduplicated_employment_classes


class TestVisaClassUtils(unittest.TestCase):
    """Test visa class utility functions"""
    
    def test_deduplicated_employment_classes_no_duplicates(self):
        """Test that deduplicated list has no duplicate display names"""
        classes = get_deduplicated_employment_classes()
        
        # Extract display names
        display_names = [display for raw, display in classes]
        
        # Check no duplicates in display names
        self.assertEqual(len(display_names), len(set(display_names)),
                        f"Found duplicate display names: {display_names}")
    
    def test_deduplicated_employment_classes_format(self):
        """Test that result has correct format"""
        classes = get_deduplicated_employment_classes()
        
        # Should be list of tuples
        self.assertIsInstance(classes, list)
        
        for item in classes:
            # Each item should be (raw_value, display_name) tuple
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)
            raw, display = item
            self.assertIsInstance(raw, str)
            self.assertIsInstance(display, str)
    
    def test_deduplicated_employment_classes_sorted(self):
        """Test that results are sorted by display name"""
        classes = get_deduplicated_employment_classes()
        display_names = [display for raw, display in classes]
        
        # Should be sorted
        self.assertEqual(display_names, sorted(display_names),
                        "Display names should be sorted alphabetically")
    
    def test_deduplicated_employment_classes_has_common_categories(self):
        """Test that common EB categories are present"""
        classes = get_deduplicated_employment_classes()
        display_names = [display for raw, display in classes]
        
        # Should contain common EB categories (if data exists)
        if len(display_names) > 0:
            # Check if any EB-1 through EB-5 categories exist
            eb_categories = [name for name in display_names if name.startswith('EB-')]
            self.assertGreater(len(eb_categories), 0,
                             "Should have at least one EB category")
    
    def test_deduplicated_eb5_variations(self):
        """Test that multiple EB-5 variations are deduplicated"""
        classes = get_deduplicated_employment_classes()
        display_names = [display for raw, display in classes]
        
        # Count how many times each EB-5 category appears
        eb5_unreserved_count = display_names.count("EB-5: Unreserved")
        eb5_rural_count = display_names.count("EB-5: Rural (20%)")
        eb5_high_unemployment_count = display_names.count("EB-5: High Unemployment (10%)")
        eb5_infrastructure_count = display_names.count("EB-5: Infrastructure (2%)")
        
        # Each should appear at most once
        self.assertLessEqual(eb5_unreserved_count, 1,
                           f"EB-5: Unreserved appears {eb5_unreserved_count} times")
        self.assertLessEqual(eb5_rural_count, 1,
                           f"EB-5: Rural appears {eb5_rural_count} times")
        self.assertLessEqual(eb5_high_unemployment_count, 1,
                           f"EB-5: High Unemployment appears {eb5_high_unemployment_count} times")
        self.assertLessEqual(eb5_infrastructure_count, 1,
                           f"EB-5: Infrastructure appears {eb5_infrastructure_count} times")


if __name__ == '__main__':
    unittest.main()


import unittest
from enum import Enum


class TestVisaCategoryEnum(unittest.TestCase):
    """Test VisaCategory enum (TDD - will fail initially)"""
    
    def test_visa_category_exists(self):
        """Test that VisaCategory enum exists"""
        from models.enums.visa_category import VisaCategory
        self.assertTrue(issubclass(VisaCategory, Enum))
    
    def test_visa_category_has_family_sponsored(self):
        """Test FAMILY_SPONSORED value"""
        from models.enums.visa_category import VisaCategory
        self.assertEqual(VisaCategory.FAMILY_SPONSORED.value, "family_sponsored")
    
    def test_visa_category_has_employment_based(self):
        """Test EMPLOYMENT_BASED value"""
        from models.enums.visa_category import VisaCategory
        self.assertEqual(VisaCategory.EMPLOYMENT_BASED.value, "employment_based")
    
    def test_visa_category_only_two_values(self):
        """Test that there are exactly 2 categories"""
        from models.enums.visa_category import VisaCategory
        self.assertEqual(len(VisaCategory), 2)


class TestActionTypeEnum(unittest.TestCase):
    """Test ActionType enum (TDD - will fail initially)"""
    
    def test_action_type_exists(self):
        """Test that ActionType enum exists"""
        from models.enums.action_type import ActionType
        self.assertTrue(issubclass(ActionType, Enum))
    
    def test_action_type_has_final_action(self):
        """Test FINAL_ACTION value"""
        from models.enums.action_type import ActionType
        self.assertEqual(ActionType.FINAL_ACTION.value, "final_action")
    
    def test_action_type_has_filing(self):
        """Test FILING value"""
        from models.enums.action_type import ActionType
        self.assertEqual(ActionType.FILING.value, "filing")
    
    def test_action_type_only_two_values(self):
        """Test that there are exactly 2 action types"""
        from models.enums.action_type import ActionType
        self.assertEqual(len(ActionType), 2)


class TestCountryEnum(unittest.TestCase):
    """Test Country enum (TDD - will fail initially)"""
    
    def test_country_exists(self):
        """Test that Country enum exists"""
        from models.enums.country import Country
        self.assertTrue(issubclass(Country, Enum))
    
    def test_country_has_all(self):
        """Test ALL CHARGEABILITY AREAS value"""
        from models.enums.country import Country
        self.assertEqual(Country.ALL.value, "all")
    
    def test_country_has_china(self):
        """Test CHINA value"""
        from models.enums.country import Country
        self.assertEqual(Country.CHINA.value, "china")
    
    def test_country_has_india(self):
        """Test INDIA value"""
        from models.enums.country import Country
        self.assertEqual(Country.INDIA.value, "india")
    
    def test_country_has_mexico(self):
        """Test MEXICO value"""
        from models.enums.country import Country
        self.assertEqual(Country.MEXICO.value, "mexico")
    
    def test_country_has_philippines(self):
        """Test PHILIPPINES value"""
        from models.enums.country import Country
        self.assertEqual(Country.PHILIPPINES.value, "philippines")
    
    def test_country_has_central_america(self):
        """Test EL_SALVADOR_GUATEMALA_HONDURAS value"""
        from models.enums.country import Country
        self.assertEqual(Country.EL_SALVADOR_GUATEMALA_HONDURAS.value, "el_salvador_guatemala_honduras")


class TestFamilyPreferenceEnum(unittest.TestCase):
    """Test FamilyPreference enum (TDD - will fail initially)"""
    
    def test_family_preference_exists(self):
        """Test that FamilyPreference enum exists"""
        from models.enums.family_preference import FamilyPreference
        self.assertTrue(issubclass(FamilyPreference, Enum))
    
    def test_has_f1(self):
        """Test F1 value"""
        from models.enums.family_preference import FamilyPreference
        self.assertEqual(FamilyPreference.F1.value, "F1")
    
    def test_has_f2a(self):
        """Test F2A value"""
        from models.enums.family_preference import FamilyPreference
        self.assertEqual(FamilyPreference.F2A.value, "F2A")
    
    def test_has_f2b(self):
        """Test F2B value"""
        from models.enums.family_preference import FamilyPreference
        self.assertEqual(FamilyPreference.F2B.value, "F2B")
    
    def test_has_f3(self):
        """Test F3 value"""
        from models.enums.family_preference import FamilyPreference
        self.assertEqual(FamilyPreference.F3.value, "F3")
    
    def test_has_f4(self):
        """Test F4 value"""
        from models.enums.family_preference import FamilyPreference
        self.assertEqual(FamilyPreference.F4.value, "F4")


class TestEmploymentPreferenceEnum(unittest.TestCase):
    """Test EmploymentPreference enum (TDD - will fail initially)"""
    
    def test_employment_preference_exists(self):
        """Test that EmploymentPreference enum exists"""
        from models.enums.employment_preference import EmploymentPreference
        self.assertTrue(issubclass(EmploymentPreference, Enum))
    
    def test_has_eb1(self):
        """Test EB1 value"""
        from models.enums.employment_preference import EmploymentPreference
        self.assertEqual(EmploymentPreference.EB1.value, "1st")
    
    def test_has_eb2(self):
        """Test EB2 value"""
        from models.enums.employment_preference import EmploymentPreference
        self.assertEqual(EmploymentPreference.EB2.value, "2nd")
    
    def test_has_eb3(self):
        """Test EB3 value"""
        from models.enums.employment_preference import EmploymentPreference
        self.assertEqual(EmploymentPreference.EB3.value, "3rd")
    
    def test_has_other_workers(self):
        """Test OTHER_WORKERS value"""
        from models.enums.employment_preference import EmploymentPreference
        self.assertEqual(EmploymentPreference.OTHER_WORKERS.value, "Other Workers")
    
    def test_has_eb4(self):
        """Test EB4 value"""
        from models.enums.employment_preference import EmploymentPreference
        self.assertEqual(EmploymentPreference.EB4.value, "4th")
    
    def test_has_religious_workers(self):
        """Test RELIGIOUS_WORKERS value"""
        from models.enums.employment_preference import EmploymentPreference
        self.assertEqual(EmploymentPreference.RELIGIOUS_WORKERS.value, "Certain Religious Workers")


if __name__ == '__main__':
    unittest.main()


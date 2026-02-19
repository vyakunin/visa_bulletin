"""
Tests for job title normalization and experience level extraction.

This test file includes a golden test set based on real-world examples
to ensure normalization quality.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import sys
import unittest

from models.job_title import JobTitle


class TestJobTitleNormalization(unittest.TestCase):
    """Test job title normalization logic."""
    
    def test_no_duplicate_words_in_normalized_title(self):
        """Normalized titles should never contain duplicate words."""
        test_cases = [
            'Chief Executive Officer / Executive Director',
            'COMPUTER SOFTWARE ENG., SYSTEMS SOFTWARE',
            'Product Management Product Manager II',
            'Security Engineer, Security Response',
            'Staff Software Engineer, Software Testing',
            'Senior Data Solutions Engineer - Big Data',
            'Shoes and Clothing Sorter and Grader',
            'Manufacturing Engineer - Powder Metal Engineer',
        ]
        
        for title in test_cases:
            normalized = JobTitle.normalize_title(title)
            words = normalized.split()
            unique_words = set(words)
            
            self.assertEqual(
                len(words), len(unique_words),
                f"Title '{title}' has duplicate words in normalized form: '{normalized}'"
            )
    
    def test_experience_level_extraction(self):
        """Test extraction of experience levels from job titles."""
        test_cases = [
            ('Senior Software Engineer', 'senior'),
            ('Junior Developer', 'junior'),
            ('Lead Data Scientist', 'lead'),
            ('Staff Engineer', 'staff'),
            ('Principal Architect', 'principal'),
            ('Engineering Manager', 'manager'),
            ('Director of Technology', 'director'),
            # Roman numerals kept verbatim (company-specific)
            ('Software Engineer II', 'ii'),
            ('Software Engineer III', 'iii'),
            ('Software Engineer IV', 'iv'),
            ('Software Engineer V', 'v'),
            ('Manager II, Supply Chain', 'ii'),
            ('Manager 2, Supply Chain', 'ii'),
            ('Director 3, Engineering', 'iii'),
            ('Lead IV, Product', 'iv'),
            ('Manager I, Supply Chain', 'i'),
            ('Manager 1, Supply Chain', 'i'),
            ('Entry Level Analyst', 'entry'),
            ('Software Engineer', ''),  # No level
        ]
        
        for title, expected_level in test_cases:
            level = JobTitle.extract_experience_level(title)
            self.assertEqual(
                level, expected_level,
                f"Title '{title}' should extract level '{expected_level}', got '{level}'"
            )
    
    def test_normalization_removes_seniority(self):
        """Normalization should remove seniority indicators and level markers."""
        test_cases = [
            ('Senior Software Engineer', 'software engineer'),
            ('Junior Developer', 'developer'),
            ('Lead Data Scientist', 'data scientist'),
            ('Staff Engineer', 'engineer'),
            ('Principal Architect', 'architect'),
            # Level markers (roman numerals and digits) stripped for job-family clustering
            ('Software Engineer II', 'software engineer'),
            ('Software Engineer III', 'software engineer'),
        ]
        
        for title, expected_normalized in test_cases:
            normalized = JobTitle.normalize_title(title)
            self.assertEqual(
                normalized, expected_normalized,
                f"Title '{title}' should normalize to '{expected_normalized}', got '{normalized}'"
            )
    
    def test_golden_set_normalizations(self):
        """Golden test set from real-world examples."""
        golden_set = [
            # (original, expected_normalized, expected_level)
            ('Chief Executive Officer / Executive Director', 'chief executive officer', 'director'),
            ('COMPUTER SOFTWARE ENG., SYSTEMS SOFTWARE', 'computer software eng systems', ''),
            ('Security Engineer, Security Response', 'security engineer response', ''),
            ('Senior Software Engineer', 'software engineer', 'senior'),
            ('Software Engineer II', 'software engineer', 'ii'),  # Level marker stripped; level in experience_level
            ('Software Engineer III', 'software engineer', 'iii'),  # Level marker stripped; level in experience_level
            ('Manager II, Supply Chain', 'manager supply chain', 'ii'),
            ('Manager 2, Supply Chain', 'manager supply chain', 'ii'),  # Level marker detected before digit removal
            ('Director 3, Engineering', 'director engineering', 'iii'),  # Level marker detected before digit removal
            ('Lead IV, Product', 'lead product', 'iv'),
            ('Manager I, Supply Chain', 'manager supply chain', 'i'),
            ('Manager 1, Supply Chain', 'manager supply chain', 'i'),  # Level marker detected before digit removal
            ('Database Administrator', 'database administrator', ''),
            ('Principal Data Scientist', 'data scientist', 'principal'),
            ('Engineering Manager', 'engineering', 'manager'),
            ('Director of Technology', 'of technology', 'director'),
            ('Staff ML Engineer', 'machine learning engineer', 'staff'),  # ml → machine learning
            ('Lead Product Designer', 'product designer', 'lead'),
            ('Junior Data Analyst', 'data scientist', 'junior'),  # data analyst → data scientist
            ('Entry Level Developer', 'developer', 'entry'),
            ('Senior Project Manager', 'project', 'manager'),
            ('VP of Engineering', 'vp of engineering', ''),
            ('Head of Data Science', 'head of data science', ''),
            ('Software Developer', 'software engineer', ''),  # developer → engineer
            ('Programmer Analyst', 'programmer analyst', ''),  # programmer NOT converted (only as complete title)
            ('Registered Nurse', 'nurse', ''),  # RN → nurse
            ('Physician Assistant', 'physician assistant', ''),  # physician NOT converted (only as complete title)
        ]
        
        for original, expected_norm, expected_level in golden_set:
            with self.subTest(title=original):
                normalized = JobTitle.normalize_title(original)
                level = JobTitle.extract_experience_level(original)
                
                self.assertEqual(
                    normalized, expected_norm,
                    f"Normalization failed for '{original}'"
                )
                self.assertEqual(
                    level, expected_level,
                    f"Level extraction failed for '{original}'"
                )
    
    def test_no_trailing_or_leading_spaces(self):
        """Normalized titles should not have leading/trailing spaces."""
        test_cases = [
            '  Senior Software Engineer  ',
            'Data Scientist   ',
            '   Product Manager',
            ' Lead Designer ',
        ]
        
        for title in test_cases:
            normalized = JobTitle.normalize_title(title)
            self.assertEqual(
                normalized, normalized.strip(),
                f"Title '{title}' has leading/trailing spaces after normalization"
            )
    
    def test_multiple_spaces_collapsed(self):
        """Multiple spaces should be collapsed to single space."""
        test_cases = [
            'Senior   Software    Engineer',
            'Data     Scientist',
            'Product  Manager  II',
        ]
        
        for title in test_cases:
            normalized = JobTitle.normalize_title(title)
            self.assertNotIn(
                '  ', normalized,
                f"Title '{title}' has multiple consecutive spaces: '{normalized}'"
            )
    
    def test_special_characters_removed(self):
        """Special characters should be removed or normalized."""
        test_cases = [
            ('Software Engineer (Full Stack)', 'software engineer full stack'),  # Meaningful parentheticals kept
            ('Data Scientist - ML', 'data scientist ml'),  # ml NOT expanded (only as complete title)
            ('Product Manager, Growth', 'product growth'),  # manager → level
            ('Senior Engineer & Architect', 'engineer and architect'),
        ]
        
        for title, expected in test_cases:
            normalized = JobTitle.normalize_title(title)
            self.assertEqual(
                normalized, expected,
                f"Title '{title}' should normalize to '{expected}', got '{normalized}'"
            )


if __name__ == '__main__':
    unittest.main()


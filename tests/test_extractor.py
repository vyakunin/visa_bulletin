"""
Behavioral tests for BulletinExtractor

These tests verify actual behavior: parsing tables, handling dates,
mapping strings to enums, handling special cases like "C" and "U".
"""

import unittest
import os
import django
from datetime import date

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from lib.table import Table
from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate
from extractors.bulletin_extractor import BulletinExtractor
from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country


class TestBulletinExtractor(unittest.TestCase):
    """Test BulletinExtractor behavior (not trivial existence tests)"""
    
    @classmethod
    def setUpClass(cls):
        """Setup test database tables once"""
        super().setUpClass()
        # Create tables directly from models (no migrations needed)
        from django.core.management import call_command
        from django.db import connection
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(Bulletin)
            schema_editor.create_model(VisaCutoffDate)
    
    def tearDown(self):
        """Clean up test data after each test"""
        # Safe deletion - only if tables exist
        try:
            VisaCutoffDate.objects.all().delete()
            Bulletin.objects.all().delete()
        except Exception:
            pass  # Tables don't exist yet, that's ok
    
    def test_extract_family_sponsored_final_action_table(self):
        """Test extracting F1 data from real table structure"""
        # Create sample table matching actual bulletin format
        headers = ('Family- Sponsored', 'All Chargeability Areas Except Those Listed',
                  'CHINA-mainland born', 'INDIA', 'MEXICO', 'PHILIPPINES')
        rows = [
            ('F1', date(2016, 11, 8), date(2016, 11, 8), date(2016, 11, 8), 
             date(2006, 3, 1), date(2013, 1, 22)),
            ('F2A', 'C', 'C', 'C', 'C', 'C'),
        ]
        table = Table('family_sponsored_final_actions', headers, rows)
        
        extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
        results = extractor.extract_from_table(table)
        
        # Verify F1 extraction
        f1_all = next(r for r in results if r['visa_class'] == 'F1' and r['country'] == 'ALL')
        self.assertEqual(f1_all['cutoff_date'], date(2016, 11, 8))
        self.assertFalse(f1_all['is_current'])
        self.assertEqual(f1_all['action_type'], 'FINAL_ACTION')
        
        f1_mexico = next(r for r in results if r['visa_class'] == 'F1' and r['country'] == 'MEXICO')
        self.assertEqual(f1_mexico['cutoff_date'], date(2006, 3, 1))
    
    def test_handle_current_status(self):
        """Test that 'C' (Current) is handled correctly"""
        headers = ('Family- Sponsored', 'All Chargeability Areas Except Those Listed')
        rows = [('F2A', 'C')]
        table = Table('family_sponsored_final_actions', headers, rows)
        
        extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
        results = extractor.extract_from_table(table)
        
        f2a = results[0]
        self.assertEqual(f2a['cutoff_value'], 'C')
        self.assertTrue(f2a['is_current'])
        self.assertIsNone(f2a['cutoff_date'])
        self.assertFalse(f2a['is_unavailable'])
    
    def test_handle_unavailable_status(self):
        """Test that 'U' (Unavailable) is handled correctly"""
        headers = ('Employment- based', 'All Chargeability Areas Except Those Listed')
        rows = [('Certain Religious Workers', 'U')]
        table = Table('employment_based_final_action', headers, rows)
        
        extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
        results = extractor.extract_from_table(table)
        
        religious = results[0]
        self.assertEqual(religious['cutoff_value'], 'U')
        self.assertTrue(religious['is_unavailable'])
        self.assertIsNone(religious['cutoff_date'])
        self.assertFalse(religious['is_current'])
    
    def test_map_table_title_to_category_and_action(self):
        """Test mapping table titles to enums"""
        test_cases = [
            ('family_sponsored_final_actions', 'FAMILY_SPONSORED', 'FINAL_ACTION'),
            ('family_sponsored_dates_for_filing', 'FAMILY_SPONSORED', 'FILING'),
            ('employment_based_final_action', 'EMPLOYMENT_BASED', 'FINAL_ACTION'),
            ('employment_based_dates_for_filing', 'EMPLOYMENT_BASED', 'FILING'),
        ]
        
        for title, expected_category, expected_action in test_cases:
            headers = ('Test', 'All Chargeability Areas Except Those Listed')
            rows = [('F1', date(2020, 1, 1))]
            table = Table(title, headers, rows)
            
            extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
            results = extractor.extract_from_table(table)
            
            self.assertEqual(results[0]['visa_category'], expected_category,
                           f"Failed for {title}")
            self.assertEqual(results[0]['action_type'], expected_action,
                           f"Failed for {title}")
    
    def test_map_header_to_country_enum(self):
        """Test mapping table headers to country strings"""
        headers = ('Class', 'All Chargeability Areas Except Those Listed',
                  'CHINA-mainland born', 'INDIA', 'MEXICO', 'PHILIPPINES')
        rows = [('F1', date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 1),
                date(2020, 1, 1), date(2020, 1, 1))]
        table = Table('family_sponsored_final_actions', headers, rows)
        
        extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
        results = extractor.extract_from_table(table)
        
        countries = {r['country'] for r in results}
        self.assertIn('ALL', countries)
        self.assertIn('CHINA', countries)
        self.assertIn('INDIA', countries)
        self.assertIn('MEXICO', countries)
        self.assertIn('PHILIPPINES', countries)
    
    def test_save_to_database(self):
        """Test saving extracted data to database"""
        bulletin = Bulletin.objects.create(publication_date=date(2025, 12, 1))
        
        headers = ('Family- Sponsored', 'All Chargeability Areas Except Those Listed')
        rows = [('F1', date(2016, 11, 8))]
        table = Table('family_sponsored_final_actions', headers, rows)
        
        extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
        results = extractor.extract_from_table(table)
        
        # Save to DB
        for data in results:
            VisaCutoffDate.objects.create(bulletin=bulletin, **data)
        
        # Query back
        saved = VisaCutoffDate.objects.filter(
            bulletin=bulletin,
            visa_class='F1',
            country='ALL'
        ).first()
        
        self.assertIsNotNone(saved)
        self.assertEqual(saved.cutoff_date, date(2016, 11, 8))
        self.assertEqual(saved.visa_category, 'FAMILY_SPONSORED')
    
    def test_idempotent_save(self):
        """Test that saving same bulletin twice doesn't duplicate"""
        bulletin = Bulletin.objects.create(publication_date=date(2025, 12, 1))
        
        headers = ('Family- Sponsored', 'All Chargeability Areas Except Those Listed')
        rows = [('F1', date(2016, 11, 8))]
        table = Table('family_sponsored_final_actions', headers, rows)
        
        extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
        results = extractor.extract_from_table(table)
        
        # Save once
        for data in results:
            VisaCutoffDate.objects.update_or_create(
                bulletin=bulletin,
                visa_class=data['visa_class'],
                country=data['country'],
                action_type=data['action_type'],
                visa_category=data['visa_category'],
                defaults=data
            )
        
        count_first = VisaCutoffDate.objects.count()
        
        # Save again (idempotent)
        for data in results:
            VisaCutoffDate.objects.update_or_create(
                bulletin=bulletin,
                visa_class=data['visa_class'],
                country=data['country'],
                action_type=data['action_type'],
                visa_category=data['visa_category'],
                defaults=data
            )
        
        count_second = VisaCutoffDate.objects.count()
        self.assertEqual(count_first, count_second, "Should not create duplicates")


if __name__ == '__main__':
    unittest.main()


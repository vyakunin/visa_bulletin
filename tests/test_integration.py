"""
Integration tests for end-to-end bulletin processing

Tests the complete pipeline: parse HTML → extract tables → save to DB
"""

import unittest
import os
from datetime import date
from django.conf import settings

# Setup Django with in-memory database for tests
if not settings.configured:
    settings.configure(
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'models',
        ],
        SECRET_KEY='test-secret-key',
        USE_TZ=True,
        DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
    )
    import django
    django.setup()

from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate
from lib.bulletint_parser import extract_tables

# Import handler after models are imported to avoid conflicts
from extractors import bulletin_handler


class TestBulletinIntegration(unittest.TestCase):
    """Test end-to-end bulletin processing"""
    
    @classmethod
    def setUpClass(cls):
        """Setup test database tables once"""
        super().setUpClass()
        from django.db import connection
        
        # Mark tables as created to prevent handler from trying again
        bulletin_handler._TABLES_CREATED = True
        
        with connection.schema_editor() as schema_editor:
            try:
                schema_editor.create_model(Bulletin)
            except Exception:
                pass
            try:
                schema_editor.create_model(VisaCutoffDate)
            except Exception:
                pass
    
    def tearDown(self):
        """Clean up test data after each test"""
        try:
            VisaCutoffDate.objects.all().delete()
            Bulletin.objects.all().delete()
        except Exception:
            pass
    
    def test_save_bulletin_from_html(self):
        """Test saving a real bulletin HTML to database"""
        # Load a real saved bulletin
        with open('saved_pages/visa-bulletin-for-march-2023.html', 'r', encoding='utf-8') as f:
            html = f.read()
        
        # Extract tables
        tables = extract_tables(html)
        self.assertEqual(len(tables), 4, "Should extract 4 tables")
        
        # Save to database
        bulletin = bulletin_handler.save_bulletin_to_db(
            publication_date=date(2023, 3, 1),
            tables=tables
        )
        
        # Verify bulletin created
        self.assertIsNotNone(bulletin)
        self.assertEqual(bulletin.publication_date, date(2023, 3, 1))
        
        # Verify cutoff dates created
        cutoff_count = VisaCutoffDate.objects.filter(bulletin=bulletin).count()
        self.assertGreater(cutoff_count, 0, "Should create cutoff date records")
        
        # Verify specific data point (F1 Mexico Final Action)
        f1_mexico = VisaCutoffDate.objects.filter(
            bulletin=bulletin,
            visa_class='F1',
            country='mexico',
            action_type='final_action',
            visa_category='family_sponsored'
        ).first()
        
        self.assertIsNotNone(f1_mexico)
        self.assertEqual(f1_mexico.cutoff_date, date(2001, 4, 1))
    
    def test_idempotent_bulletin_save(self):
        """Test that saving same bulletin twice is idempotent"""
        with open('saved_pages/visa-bulletin-for-march-2023.html', 'r', encoding='utf-8') as f:
            html = f.read()
        
        tables = extract_tables(html)
        
        # Save once
        bulletin1 = bulletin_handler.save_bulletin_to_db(date(2023, 3, 1), tables)
        count1 = VisaCutoffDate.objects.count()
        
        # Save again
        bulletin2 = bulletin_handler.save_bulletin_to_db(date(2023, 3, 1), tables)
        count2 = VisaCutoffDate.objects.count()
        
        # Should be same bulletin
        self.assertEqual(bulletin1.id, bulletin2.id)
        # Should not duplicate data
        self.assertEqual(count1, count2)
    
    def test_query_time_series_data(self):
        """Test querying time series data for specific visa class"""
        # Save multiple bulletins
        test_cases = [
            ('saved_pages/visa-bulletin-for-february-2017.html', date(2017, 2, 1)),
            ('saved_pages/visa-bulletin-for-march-2023.html', date(2023, 3, 1)),
            ('saved_pages/visa-bulletin-for-october-2021.html', date(2021, 10, 1)),
        ]
        
        for filepath, pub_date in test_cases:
            with open(filepath, 'r', encoding='utf-8') as f:
                html = f.read()
            tables = extract_tables(html)
            bulletin_handler.save_bulletin_to_db(pub_date, tables)
        
        # Query F1 China Final Action across all bulletins
        f1_china_series = VisaCutoffDate.objects.filter(
            visa_class='F1',
            country='china',
            action_type='final_action',
            visa_category='family_sponsored'
        ).order_by('bulletin__publication_date')
        
        self.assertEqual(f1_china_series.count(), 3)
        
        # Verify dates are in chronological order
        dates = [record.bulletin.publication_date for record in f1_china_series]
        self.assertEqual(dates, sorted(dates))
        
        # Verify all are F1 China
        for record in f1_china_series:
            self.assertEqual(record.visa_class, 'F1')
            self.assertEqual(record.country, 'china')


if __name__ == '__main__':
    unittest.main()


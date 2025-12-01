"""
Behavioral tests for BulletinExtractor

These tests verify actual behavior: parsing tables, handling dates,
mapping strings to enums, handling special cases like "C" and "U".

NOTE: These tests use pytest format but can also run directly via Python/Bazel.
Django setup happens in conftest.py (pytest) or below (direct run).
"""

# Django setup for direct execution (when not using pytest)
import os
import django
from django.conf import settings

if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
    settings.configure(
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        INSTALLED_APPS=['django.contrib.contenttypes', 'models'],
        SECRET_KEY='test-secret-key',
        USE_TZ=True,
        DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
    )
    django.setup()

from datetime import date
from lib.table import Table
from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate
from extractors.bulletin_extractor import BulletinExtractor
from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country


def test_extract_family_sponsored_final_action_table():
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
    
    # Verify F1 extraction (using enum values, not hardcoded strings)
    f1_all = next(r for r in results if r['visa_class'] == 'F1' and r['country'] == Country.ALL.value)
    assert f1_all['cutoff_date'] == date(2016, 11, 8)
    assert f1_all['is_current'] is False
    assert f1_all['action_type'] == ActionType.FINAL_ACTION.value
    assert f1_all['visa_category'] == VisaCategory.FAMILY_SPONSORED.value
    
    f1_mexico = next(r for r in results if r['visa_class'] == 'F1' and r['country'] == Country.MEXICO.value)
    assert f1_mexico['cutoff_date'] == date(2006, 3, 1)


def test_handle_current_status():
    """Test that 'C' (Current) is handled correctly - sets cutoff to bulletin date"""
    headers = ('Family- Sponsored', 'All Chargeability Areas Except Those Listed')
    rows = [('F2A', 'C')]
    table = Table('family_sponsored_final_actions', headers, rows)
    
    extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
    results = extractor.extract_from_table(table)
    
    f2a = results[0]
    assert f2a['cutoff_value'] == 'C'
    assert f2a['is_current'] is True
    # 'C' means Current - cutoff date should be the bulletin's publication date
    assert f2a['cutoff_date'] == date(2025, 12, 1)
    assert f2a['is_unavailable'] is False


def test_handle_unavailable_status():
    """Test that 'U' (Unavailable) is handled correctly"""
    headers = ('Employment- based', 'All Chargeability Areas Except Those Listed')
    rows = [('Certain Religious Workers', 'U')]
    table = Table('employment_based_final_action', headers, rows)
    
    extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
    results = extractor.extract_from_table(table)
    
    religious = results[0]
    assert religious['cutoff_value'] == 'U'
    assert religious['is_unavailable'] is True
    assert religious['cutoff_date'] is None
    assert religious['is_current'] is False


def test_map_table_title_to_category_and_action():
    """Test mapping table titles to enums"""
    # Use enum values, not hardcoded strings
    test_cases = [
        ('family_sponsored_final_actions', VisaCategory.FAMILY_SPONSORED.value, ActionType.FINAL_ACTION.value),
        ('family_sponsored_dates_for_filing', VisaCategory.FAMILY_SPONSORED.value, ActionType.FILING.value),
        ('employment_based_final_action', VisaCategory.EMPLOYMENT_BASED.value, ActionType.FINAL_ACTION.value),
        ('employment_based_dates_for_filing', VisaCategory.EMPLOYMENT_BASED.value, ActionType.FILING.value),
    ]
    
    for title, expected_category, expected_action in test_cases:
        headers = ('Test', 'All Chargeability Areas Except Those Listed')
        rows = [('F1', date(2020, 1, 1))]
        table = Table(title, headers, rows)
        
        extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
        results = extractor.extract_from_table(table)
        
        assert results[0]['visa_category'] == expected_category, f"Failed for {title}"
        assert results[0]['action_type'] == expected_action, f"Failed for {title}"


def test_map_header_to_country_enum():
    """Test mapping table headers to country strings"""
    headers = ('Class', 'All Chargeability Areas Except Those Listed',
              'CHINA-mainland born', 'INDIA', 'MEXICO', 'PHILIPPINES')
    rows = [('F1', date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 1),
            date(2020, 1, 1), date(2020, 1, 1))]
    table = Table('family_sponsored_final_actions', headers, rows)
    
    extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
    results = extractor.extract_from_table(table)
    
    countries = {r['country'] for r in results}
    # Use enum values, not hardcoded strings
    assert Country.ALL.value in countries
    assert Country.CHINA.value in countries
    assert Country.INDIA.value in countries
    assert Country.MEXICO.value in countries
    assert Country.PHILIPPINES.value in countries


def test_save_to_database(sample_bulletin):
    """Test saving extracted data to database"""
    bulletin = sample_bulletin
    
    headers = ('Family- Sponsored', 'All Chargeability Areas Except Those Listed')
    rows = [('F1', date(2016, 11, 8))]
    table = Table('family_sponsored_final_actions', headers, rows)
    
    extractor = BulletinExtractor(publication_date=date(2025, 12, 1))
    results = extractor.extract_from_table(table)
    
    # Save to DB
    for data in results:
        VisaCutoffDate.objects.create(bulletin=bulletin, **data)
    
    # Query back (using enum values, not hardcoded strings)
    saved = VisaCutoffDate.objects.filter(
        bulletin=bulletin,
        visa_class='F1',
        country=Country.ALL.value
    ).first()
    
    assert saved is not None
    assert saved.cutoff_date == date(2016, 11, 8)
    assert saved.visa_category == VisaCategory.FAMILY_SPONSORED.value
    assert saved.action_type == ActionType.FINAL_ACTION.value


def test_idempotent_save(sample_bulletin):
    """Test that saving same bulletin twice doesn't duplicate"""
    bulletin = sample_bulletin
    
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
    
    # Save again
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
    
    # Should not duplicate
    assert count_first == count_second

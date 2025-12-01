"""
Integration tests for end-to-end bulletin processing

Tests the complete pipeline: parse HTML → extract tables → save to DB
"""

# Django setup (for Bazel py_test; pytest uses conftest.py)
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
from django.apps import apps
if not apps.ready:
    django.setup()

from datetime import date, datetime
from lib.publication_data import PublicationData
from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate
from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from lib.bulletint_parser import extract_tables
from extractors import bulletin_handler


def test_save_bulletin_from_html():
    """Test saving a real bulletin HTML to database"""
    # Load a real saved bulletin
    with open('saved_pages/visa-bulletin-for-march-2023.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    # Create PublicationData
    pub_data = PublicationData(
        url='/test-march-2023',
        content=html,
        publication_date=datetime(2023, 3, 1)
    )
    
    # Save to database
    bulletin = bulletin_handler.save_bulletin_to_db(pub_data)
    
    # Verify bulletin created
    assert bulletin is not None
    assert bulletin.publication_date == date(2023, 3, 1)
    
    # Verify cutoff dates created
    cutoff_count = VisaCutoffDate.objects.filter(bulletin=bulletin).count()
    assert cutoff_count > 0, "Should create cutoff date records"
    
    # Verify specific data point (F1 Mexico Final Action) using enum values
    f1_mexico = VisaCutoffDate.objects.filter(
        bulletin=bulletin,
        visa_class='F1',
        country=Country.MEXICO.value,
        action_type=ActionType.FINAL_ACTION.value,
        visa_category=VisaCategory.FAMILY_SPONSORED.value
    ).first()
    
    assert f1_mexico is not None
    assert f1_mexico.cutoff_date == date(2001, 4, 1)


def test_idempotent_bulletin_save():
    """Test that saving same bulletin twice is idempotent"""
    with open('saved_pages/visa-bulletin-for-march-2023.html', 'r', encoding='utf-8') as f:
        html = f.read()
    
    pub_data = PublicationData('/test-march-2023', html, datetime(2023, 3, 1))
    
    # Save once
    bulletin1 = bulletin_handler.save_bulletin_to_db(pub_data)
    count1 = VisaCutoffDate.objects.count()
    
    # Save again
    bulletin2 = bulletin_handler.save_bulletin_to_db(pub_data)
    count2 = VisaCutoffDate.objects.count()
    
    # Should be same bulletin
    assert bulletin1.id == bulletin2.id
    # Should not duplicate data
    assert count1 == count2


def test_query_time_series_data():
    """Test querying time series data for specific visa class"""
    # Save multiple bulletins
    test_cases = [
        ('saved_pages/visa-bulletin-for-february-2017.html', datetime(2017, 2, 1)),
        ('saved_pages/visa-bulletin-for-march-2023.html', datetime(2023, 3, 1)),
        ('saved_pages/visa-bulletin-for-october-2021.html', datetime(2021, 10, 1)),
    ]
    
    for filepath, pub_date in test_cases:
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()
        pub_data = PublicationData(filepath, html, pub_date)
        bulletin_handler.save_bulletin_to_db(pub_data)
    
    # Query F1 China Final Action across all bulletins using enum values
    f1_china_series = VisaCutoffDate.objects.filter(
        visa_class='F1',
        country=Country.CHINA.value,
        action_type=ActionType.FINAL_ACTION.value,
        visa_category=VisaCategory.FAMILY_SPONSORED.value
    ).order_by('bulletin__publication_date')
    
    assert f1_china_series.count() == 3
    
    # Verify dates are in chronological order
    dates = [record.bulletin.publication_date for record in f1_china_series]
    assert dates == sorted(dates)
    
    # Verify all are F1 China using enum values
    for record in f1_china_series:
        assert record.visa_class == 'F1'
        assert record.country == Country.CHINA.value

"""
Pytest configuration and fixtures for visa bulletin tests

This file is automatically loaded by pytest and provides:
- Django setup
- Database fixtures
- Common test utilities
"""

import pytest
import os
import django
from django.conf import settings

# Setup Django before any tests run
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

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
    django.setup()


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    """Create database tables once per test session"""
    # Mark tables as already created to prevent handler from trying
    from extractors import bulletin_handler
    bulletin_handler._TABLES_CREATED = True
    
    with django_db_blocker.unblock():
        from django.db import connection
        from models.bulletin import Bulletin
        from models.visa_cutoff_date import VisaCutoffDate
        
        with connection.schema_editor() as schema_editor:
            try:
                schema_editor.create_model(Bulletin)
            except Exception:
                pass  # Table already exists
            try:
                schema_editor.create_model(VisaCutoffDate)
            except Exception:
                pass  # Table already exists


@pytest.fixture
def clean_db(db):
    """Clean database before each test"""
    from models.bulletin import Bulletin
    from models.visa_cutoff_date import VisaCutoffDate
    
    # Setup: Clean before test
    VisaCutoffDate.objects.all().delete()
    Bulletin.objects.all().delete()
    
    yield  # Run the test
    
    # Teardown: Clean after test
    VisaCutoffDate.objects.all().delete()
    Bulletin.objects.all().delete()


@pytest.fixture
def sample_bulletin(db):
    """Create a sample bulletin for testing"""
    from datetime import date
    from models.bulletin import Bulletin
    
    return Bulletin.objects.create(publication_date=date(2025, 12, 1))


# Mark all tests to use database by default
pytest_plugins = ['pytest_django']


def pytest_collection_modifyitems(items):
    """Automatically mark all tests that need database access"""
    for item in items:
        if 'test_' in item.nodeid:
            item.add_marker(pytest.mark.django_db)


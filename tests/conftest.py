"""
Pytest configuration and fixtures for visa bulletin tests

This file is automatically loaded by pytest and provides:
- Django setup
- Database fixtures
- Common test utilities
"""

import pytest

# Use shared Django setup utility
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup):
    """Depend on pytest-django's real DB setup; set the legacy handler marker.

    The depended-on `django_db_setup` (pytest-django) runs setup_databases() =
    migrate, which creates EVERY table including Bulletin and VisaCutoffDate. The
    old override here additionally did `schema_editor.create_model(Bulletin)` by
    hand — a pre-migration leftover that now fails "relation already exists" and
    aborts the fixture's transaction, erroring every test in the target. It was
    dead weight masked for years by the false-green suite + the conftest-import
    DB-collision crash (which meant this fixture never actually ran). Removed.

    Only the `_TABLES_CREATED` marker survives: it tells the optional legacy
    `bulletin_handler` not to attempt its own table creation.
    """
    try:
        from extractors import bulletin_handler

        bulletin_handler._TABLES_CREATED = True
    except ImportError:
        pass


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
pytest_plugins = ["pytest_django"]


def pytest_collection_modifyitems(items):
    """Automatically mark all tests that need database access"""
    for item in items:
        if "test_" in item.nodeid:
            item.add_marker(pytest.mark.django_db)

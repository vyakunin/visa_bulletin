"""
Shared Django setup for tests

This module provides Django configuration for both pytest and Bazel tests.
Import this at the top of test files to ensure Django is properly configured.
"""

import os
import sys
import django
from django.apps import apps
from django.conf import settings


def setup_django_for_tests():
    """Configure Django for test environment if not already configured"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
    
    # Check if already configured (by pytest or another test)
    if not apps.ready:
        # If running Django TestCase (not pytest), configure test database
        if 'pytest' not in sys.modules and not settings.configured:
            # Override database settings for tests
            from django_config import settings as prod_settings
            
            # Use in-memory database for tests
            test_settings = {
                'DATABASES': {
                    'default': {
                        'ENGINE': 'django.db.backends.sqlite3',
                        'NAME': ':memory:',
                    }
                },
                'INSTALLED_APPS': prod_settings.INSTALLED_APPS,
                'SECRET_KEY': 'test-secret-key',
                'USE_TZ': prod_settings.USE_TZ,
                'DEFAULT_AUTO_FIELD': prod_settings.DEFAULT_AUTO_FIELD,
                'ALLOWED_HOSTS': prod_settings.ALLOWED_HOSTS,
                'TEMPLATES': prod_settings.TEMPLATES,
                'ROOT_URLCONF': prod_settings.ROOT_URLCONF,
                'CACHES': {
                    'default': {
                        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                    }
                },
            }
            
            settings.configure(**test_settings)
        
        django.setup()

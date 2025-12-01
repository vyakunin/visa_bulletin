"""
Django settings for visa_bulletin project.
Minimal configuration for using Django ORM standalone.
"""

import os
from pathlib import Path

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Workspace directory for Bazel compatibility
WORKSPACE_DIR = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', BASE_DIR))

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': WORKSPACE_DIR / 'visa_bulletin.db',
        # Enable WAL mode for concurrent reads during writes
        'OPTIONS': {
            'timeout': 20,  # Wait up to 20 seconds for locks
        },
    }
}

# Database connection initialization
def setup_sqlite_wal(sender, connection, **kwargs):
    """Enable WAL mode for SQLite to allow concurrent reads/writes"""
    if connection.vendor == 'sqlite':
        cursor = connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA synchronous=NORMAL;')  # Faster writes
        cursor.execute('PRAGMA cache_size=-64000;')   # 64MB cache

from django.db.backends.signals import connection_created
connection_created.connect(setup_sqlite_wal)

# Application definition
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'models',  # Our models app
    'webapp',  # Web dashboard
]

# Templates configuration
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'webapp' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
            ],
        },
    },
]

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    WORKSPACE_DIR / 'webapp' / 'static',
]
STATIC_ROOT = WORKSPACE_DIR / 'staticfiles'

# Required settings
SECRET_KEY = 'django-insecure-for-development-only'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DEBUG = False
ALLOWED_HOSTS = ['*', 'localhost', '127.0.0.1', '3.82.99.148']

# WSGI application
ROOT_URLCONF = 'django_config.urls'


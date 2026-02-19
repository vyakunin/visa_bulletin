"""
Production Django settings for visa_bulletin project.
Uses environment variables for sensitive data.
"""

import os
from pathlib import Path

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', BASE_DIR))

# SECURITY WARNING: Keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'change-me-in-production')

# SECURITY WARNING: Don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Database configuration - PostgreSQL is now the default
# SQLite is deprecated and disabled. Set DB_ENGINE=sqlite3 only for migration/backup purposes.
DB_ENGINE = os.environ.get('DB_ENGINE', 'postgresql').lower()

if DB_ENGINE == 'sqlite3':
    # SQLite is deprecated - use only for migration/backup purposes
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': WORKSPACE_DIR / 'visa_bulletin.db',
            'OPTIONS': {
                'timeout': 20,
            },
        }
    }

    # Database connection initialization (WAL mode for SQLite only)
    def setup_sqlite_wal(sender, connection, **kwargs):
        """Enable WAL mode for SQLite to allow concurrent reads/writes"""
        if connection.vendor == 'sqlite':
            cursor = connection.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            cursor.execute('PRAGMA cache_size=-64000;')

    from django.db.backends.signals import connection_created
    connection_created.connect(setup_sqlite_wal)
else:
    # PostgreSQL configuration (default)
    # PostgreSQL configuration
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'visa_bulletin'),
            'USER': os.environ.get('DB_USER', 'visa_bulletin_user'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'OPTIONS': {
                'connect_timeout': 120,
            },
        }
    }
    # Reuse connections briefly to avoid stale connections (SSL closed) from server idle timeout
    DATABASES['default']['CONN_MAX_AGE'] = 60  # 1 minute

# Application definition
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'models',
    'webapp',
]

# Templates
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

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [WORKSPACE_DIR / 'webapp' / 'static']
STATIC_ROOT = WORKSPACE_DIR / 'staticfiles'

# Security settings
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
ROOT_URLCONF = 'django_config.urls'

# Production security settings
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


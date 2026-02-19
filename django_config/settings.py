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

# Database configuration - PostgreSQL only
# When RUNNING_TESTS=1, use test-only defaults so Django can create ephemeral test DB
# (test_<name>). Do not read DB_NAME/DB_USER/DB_PASSWORD from env so that "source .env && bazel test"
# on staging/CI does not use app credentials by default. If TEST_DB_USER is set (e.g. on staging
# where postgres requires a password), use TEST_DB_USER and TEST_DB_PASSWORD for tests.
_running_tests = os.environ.get('RUNNING_TESTS') == '1'
if _running_tests:
    _db_name = 'postgres'
    if os.environ.get('TEST_DB_USER'):
        _db_user = os.environ.get('TEST_DB_USER')
        _db_password = os.environ.get('TEST_DB_PASSWORD', '')
    else:
        _db_user = os.environ.get('USER', 'postgres')
        _db_password = ''
else:
    _db_name = os.environ.get('DB_NAME', 'visa_bulletin_dev')
    _db_user = os.environ.get('DB_USER', 'visa_bulletin_user')
    _db_password = os.environ.get('DB_PASSWORD', 'dev_password')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _db_name,
        'USER': _db_user,
        'PASSWORD': _db_password,
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 120,
        },
    }
}
# Connection pooling for better performance (disabled in tests for isolation)
DATABASES['default']['CONN_MAX_AGE'] = 0 if os.environ.get('RUNNING_TESTS') == '1' else 600

# Application definition
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'django.contrib.humanize',  # For intcomma and other human-readable filters
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
                'django_config.context_processors.analytics',
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
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Debug mode: Enable for local development, ALWAYS False in production
# Production check: if SECRET_KEY is NOT the default, we're in production
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-for-development-only')
IS_PRODUCTION = SECRET_KEY != 'django-insecure-for-development-only'
DEBUG = not IS_PRODUCTION  # True locally, False in production (safe by default)

_default_allowed_hosts = [
    'localhost',
    '127.0.0.1',
    'testserver',  # For Django tests
    '3.227.71.176',  # AWS Lightsail static IP (old production)
    '44.209.204.255',  # AWS Lightsail static IP (new 2GB instance)
    '54.196.241.197',  # Staging
    'visa-bulletin.us',
    'www.visa-bulletin.us',
]
ALLOWED_HOSTS = (
    [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
    if os.environ.get('ALLOWED_HOSTS')
    else _default_allowed_hosts
)

# WSGI application
ROOT_URLCONF = 'django_config.urls'

# Caching configuration
# Use Redis when REDIS_URL is set (production/staging); otherwise LocMem (dev, single-worker).
# Single default timeout (24h) for all cache_page and cache.set; no per-call overrides.
CACHE_TIMEOUT = 60 * 60 * 24  # 24 hours
REDIS_URL = os.environ.get('REDIS_URL', '')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'KEY_PREFIX': 'visa_bulletin',
            'TIMEOUT': CACHE_TIMEOUT,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
            'TIMEOUT': CACHE_TIMEOUT,
        }
    }

# Analytics Configuration
# Flexible analytics support (GoatCounter, Umami, Plausible, etc.)
# Set ANALYTICS_SCRIPT via environment variable with your tracking code
ANALYTICS_SCRIPT = os.environ.get('ANALYTICS_SCRIPT', '')

# Logging Configuration
from django_config.logging_config import setup_logging

setup_logging(debug=DEBUG)

# HTTPS/Security settings (enable in production)
# Uncomment these when deploying with HTTPS:
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
# SECURE_BROWSER_XSS_FILTER = True
# SECURE_CONTENT_TYPE_NOSNIFF = True
# X_FRAME_OPTIONS = 'DENY'
# SECURE_HSTS_SECONDS = 31536000  # 1 year
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True


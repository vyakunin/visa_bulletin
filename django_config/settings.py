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
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'visa_bulletin_dev'),
        'USER': os.environ.get('DB_USER', 'visa_bulletin_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'dev_password'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}
# Connection pooling for better performance
DATABASES['default']['CONN_MAX_AGE'] = 600  # 10 minutes

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

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'testserver',  # For Django tests
    '3.227.71.176',  # AWS Lightsail static IP (old production)
    '44.209.204.255',  # AWS Lightsail static IP (new 2GB instance)
    'visa-bulletin.us',
    'www.visa-bulletin.us',
]

# WSGI application
ROOT_URLCONF = 'django_config.urls'

# Caching configuration
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
        'TIMEOUT': 60 * 60 * 3,  # Cache for 3 hours
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


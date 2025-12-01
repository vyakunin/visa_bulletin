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
    }
}

# Application definition
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'models',  # Our models app
]

# Required settings
SECRET_KEY = 'django-insecure-for-development-only'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


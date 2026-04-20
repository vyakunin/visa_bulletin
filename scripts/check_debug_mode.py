#!/usr/bin/env python3
"""
Check if DEBUG mode is properly configured for local vs production.
"""

import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django.conf import settings

print("=" * 70)
print("🔍 DEBUG MODE CHECK")
print("=" * 70)
print()
print(f"DEBUG: {settings.DEBUG}")
print(f"IS_PRODUCTION (SECRET_KEY is non-default): {settings.IS_PRODUCTION}")
print(f"SECRET_KEY: {settings.SECRET_KEY[:30]}...")
print(f"ALLOWED_HOSTS: {settings.ALLOWED_HOSTS}")
print()

if settings.DEBUG:
    print("⚠️  DEBUG is True — tracebacks, URL conf, and settings will be exposed on errors.")
    print("   Only acceptable for local development.")
else:
    print("✅ DEBUG is False — safe for production.")

print()
print("=" * 70)
print("DEBUG is controlled by the DEBUG env var (default False).")
print("Set DEBUG=True in your local .env for development; never in prod.")
print("settings.py hard-fails at boot if DEBUG=True and ALLOWED_HOSTS contains a")
print("production hostname (visa-bulletin.us).")
print("=" * 70)

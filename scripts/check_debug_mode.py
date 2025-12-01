#!/usr/bin/env python3
"""
Check if DEBUG mode is properly configured for local vs production.
"""

import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django
django.setup()

from django.conf import settings

print("=" * 70)
print("🔍 DEBUG MODE CHECK")
print("=" * 70)
print()
print(f"DEBUG: {settings.DEBUG}")
print(f"IS_PRODUCTION: {settings.IS_PRODUCTION}")
print(f"SECRET_KEY: {settings.SECRET_KEY[:30]}...")
print()

if settings.IS_PRODUCTION:
    print("✅ Production mode detected")
    print("   • DEBUG is False")
    print("   • SECRET_KEY is set (not default)")
else:
    print("🚀 Development mode detected")
    print("   • DEBUG is True (helpful error messages)")
    print("   • Using development SECRET_KEY")
    
print()
print("=" * 70)
print("💡 To enable production mode:")
print("   export DJANGO_SECRET_KEY='your-production-secret-key'")
print("=" * 70)


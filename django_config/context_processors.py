"""
Django context processors for adding variables to all templates.
"""

from django.conf import settings


def analytics(request):
    """
    Add analytics configuration to all template contexts.
    Supports any analytics provider via ANALYTICS_SCRIPT environment variable.
    """
    return {
        'analytics_script': settings.ANALYTICS_SCRIPT,
    }


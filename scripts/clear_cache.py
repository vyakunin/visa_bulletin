#!/usr/bin/env python3
"""Clear Django cache"""

import os
import sys
import logging

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)

def main():
    """Clear all Django cache"""
    # Log script execution
    script_logger.log_call(
        args={},
        context='Clearing Django cache'
    )
    
    cache.clear()
    logger.info("✓ Django cache cleared")
    logger.info("Note: Restart the server to ensure @cache_page decorator cache is cleared")
    logger.info("      Run: ./scripts/restart_server.sh --background")

if __name__ == '__main__':
    main()

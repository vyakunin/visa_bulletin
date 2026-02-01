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
    logger.info(
        "With Redis: cache is shared; no restart needed. "
        "After data refresh or deploy that changes cached payloads, run this script (or see docs for cache cleansing)."
    )
    logger.info(
        "On memory-constrained instances (e.g. 2GB): run 'bazel shutdown' after this to free ~400-500MB."
    )

if __name__ == '__main__':
    main()

"""
Bulletin Database Importer - saves parsed bulletins to database

Handles the complete pipeline:
1. Create or get Bulletin record
2. Extract data from all tables
3. Save VisaCutoffDate records (idempotent)
"""

import logging
import os

import django

# Setup Django if not already configured
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

# Only call django.setup() if not already set up
from django.apps import apps as django_apps

if not django_apps.ready:
    django.setup()

from lib.parsing.bulletin.parser import extract_tables
from lib.parsing.bulletin.publication_data import PublicationData
from lib.parsing.bulletin.table_to_cutoff_data import TableToCutoffData

logger = logging.getLogger(__name__)

# Track whether tables have been created
_TABLES_CREATED = False


def save_bulletin_to_db(publication_data: PublicationData):
    """
    Save a bulletin and all its tables to the database (idempotent)
    
    Args:
        publication_data: PublicationData object with URL, content, and date
        
    Returns:
        Bulletin instance (created or retrieved)
        
    Example:
        save_bulletin_to_db(publication_data)
    """
    # Extract date and tables from PublicationData
    publication_date = publication_data.publication_date.date()
    tables = extract_tables(publication_data.content)

    # Import models here to ensure Django is fully set up
    from models.bulletin import Bulletin
    from models.visa_cutoff_date import VisaCutoffDate

    # Get or create bulletin with URL
    bulletin, created = Bulletin.objects.get_or_create(
        publication_date=publication_date,
        defaults={'url': publication_data.url}
    )

    # Update URL if bulletin exists but URL is missing
    if not created and not bulletin.url and publication_data.url:
        bulletin.url = publication_data.url
        bulletin.save()

    if created:
        logger.info(f"Created new bulletin: {publication_date}")
    else:
        logger.info(f"Bulletin already exists: {publication_date}")

    # Create extractor from PublicationData (accepts PublicationData object directly)
    extractor = TableToCutoffData(publication_data)

    # Process each table
    for table in tables:
        cutoff_data_list = extractor.extract_from_table(table)

        # Save each cutoff date (update_or_create for idempotency)
        for cutoff_data in cutoff_data_list:
            VisaCutoffDate.objects.update_or_create(
                bulletin=bulletin,
                visa_category=cutoff_data['visa_category'],
                visa_class=cutoff_data['visa_class'],
                action_type=cutoff_data['action_type'],
                country=cutoff_data['country'],
                defaults={
                    'cutoff_value': cutoff_data['cutoff_value'],
                    'cutoff_date': cutoff_data['cutoff_date'],
                    'is_current': cutoff_data['is_current'],
                    'is_unavailable': cutoff_data['is_unavailable'],
                }
            )

    # Log summary
    cutoff_count = VisaCutoffDate.objects.filter(bulletin=bulletin).count()
    logger.info(f"  Saved {cutoff_count} cutoff date records")

    return bulletin

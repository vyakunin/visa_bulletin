"""
Bulletin Handler - saves parsed bulletins to database

Handles the complete pipeline:
1. Create or get Bulletin record
2. Extract data from all tables
3. Save VisaCutoffDate records (idempotent)
"""

import os
import django
from datetime import date
from typing import List

# Setup Django if not already configured
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

# Only call django.setup() if not already set up
from django.apps import apps as django_apps
if not django_apps.ready:
    django.setup()

from extractors.bulletin_extractor import BulletinExtractor

# Track whether tables have been created
_TABLES_CREATED = False


def save_bulletin_to_db(publication_date: date, tables: List):
    """
    Save a bulletin and all its tables to the database (idempotent)
    
    Args:
        publication_date: Date of the bulletin publication
        tables: List of Table objects from extract_tables()
        
    Returns:
        Bulletin instance (created or retrieved)
    """
    global _TABLES_CREATED
    
    # Import models here to ensure Django is fully set up
    from models.bulletin import Bulletin
    from models.visa_cutoff_date import VisaCutoffDate
    from django.db import connection
    
    # Create tables if they don't exist (only once per session)
    if not _TABLES_CREATED:
        with connection.schema_editor() as schema_editor:
            try:
                schema_editor.create_model(Bulletin)
                print("Created Bulletin table")
            except Exception:
                pass  # Table already exists
            try:
                schema_editor.create_model(VisaCutoffDate)
                print("Created VisaCutoffDate table")
            except Exception:
                pass  # Table already exists
        _TABLES_CREATED = True
    
    # Get or create bulletin
    bulletin, created = Bulletin.objects.get_or_create(
        publication_date=publication_date
    )
    
    if created:
        print(f"Created new bulletin: {publication_date}")
    else:
        print(f"Bulletin already exists: {publication_date}")
    
    # Create extractor for this bulletin
    extractor = BulletinExtractor(publication_date=publication_date)
    
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
    
    # Print summary
    cutoff_count = VisaCutoffDate.objects.filter(bulletin=bulletin).count()
    print(f"  Saved {cutoff_count} cutoff date records")
    
    return bulletin


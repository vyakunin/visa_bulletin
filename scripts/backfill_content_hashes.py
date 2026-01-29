#!/usr/bin/env python3
"""
Backfill content_hash for existing DataSource records.

Computes SHA256 hash of each downloaded file and updates the DataSource record.
This enables duplicate detection even when DOL changes URL structures.
"""

import os
import sys
import logging
import django
from pathlib import Path

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.ingest.data_source import DataSource
from lib.utils.http_utils import compute_file_hash, get_workspace_dir

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)


def main():
    logger.info("="*80)
    logger.info("Backfilling content_hash for DataSource records")
    logger.info("="*80)
    
    # Find sources with local files but no hash
    sources_needing_hash = DataSource.objects.filter(
        local_file_path__isnull=False
    ).exclude(
        local_file_path=''
    ).filter(
        content_hash=''
    )
    
    total_count = sources_needing_hash.count()
    logger.info(f"Found {total_count} sources needing hash computation")
    
    if total_count == 0:
        logger.info("✅ All sources with local files already have content_hash")
        return
    
    workspace_dir = get_workspace_dir()
    updated_count = 0
    missing_files = []
    
    for source in sources_needing_hash:
        filepath = Path(source.local_file_path)
        
        # Handle different path formats:
        # 1. Absolute paths: /opt/visa_bulletin/data/...
        # 2. Relative to workspace: data/salary/dol_data/file.xlsx
        # 3. Bazel runfiles paths: bazel-bin/.../runfiles/_main/lib/data/...
        
        if not filepath.is_absolute():
            # Try relative to workspace first
            filepath = workspace_dir / filepath
        
        if not filepath.exists():
            # Try extracting just the data path for Bazel runfiles
            # Path like: bazel-bin/.../runfiles/_main/lib/data/salary/dol_data/file.xlsx
            # Should become: data/salary/dol_data/file.xlsx
            path_str = str(source.local_file_path)
            if '/data/' in path_str:
                data_path = path_str[path_str.index('/data/')+1:]  # Keep 'data/...'
                filepath = workspace_dir / data_path
        
        if not filepath.exists():
            missing_files.append(str(source.local_file_path))
            logger.warning(f"File not found: {filepath}")
            logger.warning(f"  Source: {source.url}")
            continue
        
        # Compute hash
        try:
            content_hash = compute_file_hash(filepath)
            source.content_hash = content_hash
            source.save(update_fields=['content_hash'])
            updated_count += 1
            
            if updated_count % 10 == 0:
                logger.info(f"Progress: {updated_count}/{total_count} hashes computed")
            
        except Exception as e:
            logger.error(f"Error computing hash for {filepath}: {e}")
    
    logger.info("")
    logger.info("="*80)
    logger.info("BACKFILL COMPLETE")
    logger.info("="*80)
    logger.info(f"✅ Updated {updated_count}/{total_count} sources with content_hash")
    
    if missing_files:
        logger.warning(f"⚠️  {len(missing_files)} files not found:")
        for filepath in missing_files[:10]:
            logger.warning(f"  - {filepath}")
        if len(missing_files) > 10:
            logger.warning(f"  ... and {len(missing_files) - 10} more")


if __name__ == '__main__':
    main()

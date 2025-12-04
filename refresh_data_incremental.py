"""
Incremental data refresh script for production use with concurrent web server.

This script:
- Only fetches bulletins not already in the database
- Uses WAL mode for concurrent access
- Implements retry logic for transient database locks
- Safe to run as a cron job while web server is running

Usage:
    bazel run //:refresh_data_incremental
"""

import os
import sys
import time
import logging
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

import requests
from django.db import transaction, OperationalError

# Configure logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
    import django
    django.setup()

from lib.bulletint_parser import parse_publication_links, extract_tables
from lib.publication_data import PublicationData
from extractors.bulletin_handler import save_bulletin_to_db
from models.bulletin import Bulletin

# Get workspace directory
WORKSPACE_DIR = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', Path(__file__).parent))
SAVED_PAGES_DIR = WORKSPACE_DIR / 'saved_pages'


def fetch_main_page(url):
    """Fetch the main visa bulletin page"""
    response = requests.get(url)
    response.raise_for_status()
    return response.text


def get_existing_bulletin_dates():
    """Get set of publication dates already in database"""
    return set(
        Bulletin.objects.values_list('publication_date', flat=True)
    )


def is_saved(pub_url):
    """Check if bulletin HTML is cached locally"""
    filename = os.path.basename(urlparse(pub_url).path)
    return (SAVED_PAGES_DIR / filename).exists()


def save_page_content(url, content):
    """Save bulletin HTML to cache directory"""
    SAVED_PAGES_DIR.mkdir(exist_ok=True)
    filename = os.path.basename(urlparse(url).path)
    filepath = SAVED_PAGES_DIR / filename
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def fetch_publication(pub_url):
    """Fetch or load cached publication HTML"""
    if is_saved(pub_url):
        filename = os.path.basename(urlparse(pub_url).path)
        with open(SAVED_PAGES_DIR / filename, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        response = requests.get(pub_url)
        response.raise_for_status()
        content = response.text
        save_page_content(pub_url, content)
        return content


def save_with_retry(publication_data, max_retries=3, base_delay=1.0):
    """
    Save bulletin to database with exponential backoff retry.
    
    Args:
        publication_data: PublicationData object
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)
    
    Returns:
        Bulletin object if successful, None if all retries failed
    """
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                bulletin = save_bulletin_to_db(publication_data)
                return bulletin
        except OperationalError as e:
            if 'database is locked' in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(f"  ⚠️  Database locked, retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise
    return None


def main():
    """Fetch only new bulletins not already in database"""
    start_time = datetime.now()
    logger.info("="*80)
    logger.info("🔄 INCREMENTAL DATA REFRESH - STARTED")
    logger.info("="*80)
    
    # Get existing bulletins from database
    logger.info("")
    logger.info("📊 Checking existing data...")
    existing_dates = get_existing_bulletin_dates()
    logger.info(f"  • Bulletins in database: {len(existing_dates)}")
    if existing_dates:
        oldest = min(existing_dates)
        newest = max(existing_dates)
        logger.info(f"  • Date range: {oldest} to {newest}")
    
    # Fetch list of available bulletins
    logger.info("")
    logger.info("🌐 Fetching bulletin list from travel.state.gov...")
    url = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
    html = fetch_main_page(url)
    publication_urls = parse_publication_links(html)
    logger.info(f"  • Available bulletins: {len(publication_urls)}")
    
    # Filter to only new bulletins
    new_bulletins = []
    for pub_url in publication_urls:
        # Extract date from URL
        filename = os.path.basename(urlparse(pub_url).path)
        date_str = filename.replace('visa-bulletin-for-', '').replace('.html', '')
        try:
            publication_date = datetime.strptime(date_str, '%B-%Y').date()
            if publication_date not in existing_dates:
                new_bulletins.append((pub_url, publication_date))
        except ValueError:
            logger.warning(f"  ⚠️  Skipping invalid date format: {date_str}")
            continue
    
    if not new_bulletins:
        logger.info("")
        logger.info("✅ No new bulletins to fetch. Database is up to date!")
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info("="*80)
        logger.info(f"✅ CRON_SUCCESS: Refresh completed successfully in {duration:.1f}s (no new data)")
        logger.info("="*80)
        return 0
    
    logger.info("")
    logger.info(f"📥 Found {len(new_bulletins)} new bulletin(s) to fetch:")
    for url, date in new_bulletins[:5]:
        logger.info(f"  • {date.strftime('%B %Y')}")
    if len(new_bulletins) > 5:
        logger.info(f"  ... and {len(new_bulletins) - 5} more")
    
    # Fetch and save new bulletins
    logger.info("")
    logger.info("💾 Fetching and saving new bulletins...")
    success_count = 0
    error_count = 0
    
    for pub_url, publication_date in new_bulletins:
        try:
            logger.info("")
            logger.info(f"  📄 {publication_date.strftime('%B %Y')}...", extra={'no_timestamp': True})
            
            # Fetch HTML
            content = fetch_publication(pub_url)
            
            # Create PublicationData
            pub_data = PublicationData(
                url=pub_url,
                content=content,
                publication_date=datetime.combine(publication_date, datetime.min.time())
            )
            
            # Save to database with retry
            bulletin = save_with_retry(pub_data)
            
            if bulletin:
                # Count saved records
                tables = extract_tables(content)
                total_records = sum(len(t.rows) for t in tables)
                logger.info(f"✓ Saved ({total_records} records)")
                success_count += 1
            else:
                logger.error("✗ Failed after retries")
                error_count += 1
                
        except Exception as e:
            logger.error(f"✗ Error: {e}")
            error_count += 1
    
    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.info("")
    logger.info("="*80)
    logger.info("📊 REFRESH SUMMARY")
    logger.info("="*80)
    logger.info(f"  • Successfully saved: {success_count}")
    logger.info(f"  • Errors: {error_count}")
    logger.info(f"  • Total bulletins now in DB: {len(existing_dates) + success_count}")
    logger.info(f"  • Duration: {duration:.1f}s")
    
    # Determine exit status
    if error_count > 0:
        logger.warning("")
        logger.warning("⚠️  Some errors occurred. Check logs above.")
        logger.error("="*80)
        logger.error(f"❌ CRON_FAILURE: Refresh completed with {error_count} error(s) in {duration:.1f}s")
        logger.error("="*80)
        return 1
    elif success_count > 0:
        logger.info("")
        logger.info("✅ Database updated successfully!")
        logger.info("="*80)
        logger.info(f"✅ CRON_SUCCESS: Refresh completed successfully in {duration:.1f}s ({success_count} new bulletin(s))")
        logger.info("="*80)
        return 0
    else:
        # No new bulletins case already handled above, but just in case
        logger.info("="*80)
        logger.info(f"✅ CRON_SUCCESS: Refresh completed successfully in {duration:.1f}s (no new data)")
        logger.info("="*80)
        return 0


if __name__ == "__main__":
    start_time = None
    try:
        exit_code = main()
        sys.exit(exit_code if exit_code is not None else 0)
    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("⚠️  Refresh interrupted by user")
        logger.error("❌ CRON_FAILURE: Refresh interrupted")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        end_time = datetime.now()
        duration = 0.0
        if start_time:
            duration = (end_time - start_time).total_seconds()
        logger.error("")
        logger.error(f"❌ CRITICAL ERROR: {type(e).__name__}: {e}")
        logger.error("="*80)
        logger.error(f"❌ CRON_FAILURE: Refresh failed with exception in {duration:.1f}s")
        logger.error("="*80)
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


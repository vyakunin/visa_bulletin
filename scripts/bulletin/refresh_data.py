import os
import sys
import sqlite3
import logging
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

import requests

# Setup Django early (before imports that use models)
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
    import django
    django.setup()

from lib.parsing.bulletin.parser import parse_publication_links, extract_tables
from lib.parsing.bulletin.publication_data import PublicationData
from lib.parsing.bulletin.db_importer import save_bulletin_to_db
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

script_logger = ScriptLogger(__file__)
setup_logging(debug=False)
logger = logging.getLogger(__name__)

# Get workspace directory from Bazel (set when using 'bazel run')
# Falls back to script directory if not running under Bazel
WORKSPACE_DIR = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', Path(__file__).parent))
SAVED_PAGES_DIR = WORKSPACE_DIR / 'data' / 'bulletin' / 'saved_pages'


def fetch_main_page(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.text


def is_saved(pub_url):
    filename = os.path.basename(urlparse(pub_url).path)
    return (SAVED_PAGES_DIR / filename).exists()


def fetch_publication_data(publication_urls):
    data = []
    for pub_url in publication_urls:  # Process all bulletins, not just first 100
        content = maybe_fetch_publication(pub_url)

        # Extract publication date from URL
        filename = os.path.basename(urlparse(pub_url).path)
        date_str = filename.replace('visa-bulletin-for-', '').replace('.html', '')
        publication_date = datetime.strptime(date_str, '%B-%Y')

        data.append(PublicationData(pub_url, content, publication_date))
    return data


def maybe_fetch_publication(pub_url):
    if is_saved(pub_url):
        filename = os.path.basename(urlparse(pub_url).path)
        with open(SAVED_PAGES_DIR / filename, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        # pub_url is now absolute from parse_publication_links()
        pub_response = requests.get(pub_url)
        pub_response.raise_for_status()
        content = pub_response.text
        save_page_content(pub_url, content)
    return content


def print_all_tables(tables):
    for i, table in enumerate(tables, 1):
        pretty_print_table(table.headers, i, table.rows, table.title)


def pretty_print_table(headers, i, rows, title):
    # Print table title
    print(f"\nTable {i}: {title}")
    # Combine headers and rows
    all_rows = [headers] + rows
    # Calculate column widths
    col_widths = [max(len(str(cell)) for cell in column) for column in zip(*all_rows)]
    # Print table header
    print('╔' + '╤'.join('═' * width for width in col_widths) + '╗')
    header_cells = [str(cell).ljust(width) for cell, width in zip(headers, col_widths)]
    print('║' + '│'.join(header_cells) + '║')
    print('╟' + '┼'.join('─' * width for width in col_widths) + '╢')
    # Print table rows
    for row in rows:
        cells = [str(cell).ljust(width) for cell, width in zip(row, col_widths)]
        print('║' + '│'.join(cells) + '║')
        print('╟' + '┼'.join('─' * width for width in col_widths) + '╢')
    # Print table footer
    print('╚' + '╧'.join('═' * width for width in col_widths) + '╝')


def save_page_content(url, content):
    # Create directory if it doesn't exist
    SAVED_PAGES_DIR.mkdir(exist_ok=True)

    # Extract filename from URL and sanitize it
    filename = os.path.basename(urlparse(url).path)
    filepath = SAVED_PAGES_DIR / filename

    # Save content
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    """Fetch bulletins and optionally save to database"""
    # Check for --save-to-db flag
    save_to_db = '--save-to-db' in sys.argv
    
    # Log script execution
    script_logger.log_call(
        args={'save_to_db': save_to_db},
        context='Fetching and optionally saving visa bulletins'
    )
    
    url = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
    html = fetch_main_page(url)
    publication_urls = parse_publication_links(html)
    data = fetch_publication_data(publication_urls)
    
    for d in data:
        logger.info(f"\n{'='*80}")
        logger.info(f"URL: {d.url}")
        logger.info(f"Date: {d.publication_date.strftime('%B %Y')}")
        
        if save_to_db:
            # Save to database - pass PublicationData directly
            bulletin = save_bulletin_to_db(d)
            logger.info(f"✓ Saved to database")
        else:
            # Just print tables
            tables = extract_tables(d.content)
            logger.info(f"Tables: {len(tables)}")
            print_all_tables(tables)
    
    if not save_to_db:
        logger.info("\n" + "="*80)
        logger.info("Tip: Use --save-to-db flag to save bulletins to database")
        logger.info("Example: bazel run //:refresh_data -- --save-to-db")


if __name__ == "__main__":
    main()
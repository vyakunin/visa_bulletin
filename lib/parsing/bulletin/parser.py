"""
Parse visa bulletin HTML pages and extract table data.

Key functions:
- parse_publication_links(html) - Extract publication URLs
- extract_tables(html) - Extract all visa cutoff tables
- extract_table(table) - Parse single table
- normalize(text) - Clean whitespace
- convert_to_date(value) - Parse date strings (DDMmmYY format)
"""

import os
import re
from datetime import datetime

from bs4 import BeautifulSoup

from lib.parsing.bulletin.bulletin_table import BulletinTable

AVAILABLE_TABLES = {'family_sponsored_final_actions': 'FINAL ACTION DATES FOR FAMILY-SPONSORED PREFERENCE CASES',
                    'family_sponsored_dates_for_filing': 'DATES FOR FILING FAMILY-SPONSORED VISA APPLICATIONS',
                    'employment_based_final_action': 'FINAL ACTION DATES FOR EMPLOYMENT-BASED PREFERENCE CASES',
                    'employment_based_dates_for_filing': 'DATES FOR FILING OF EMPLOYMENT-BASED VISA APPLICATIONS'}
AVAILABLE_TABLES = {value: key for key, value in AVAILABLE_TABLES.items()}  # Reverse the dictionary
def parse_publication_links(html):
    soup = BeautifulSoup(html, 'html.parser')
    publication_links = soup.find_all('a', href=True)
    publication_urls = {
        link['href'] for link in publication_links
        if 'visa-bulletin-for' in link['href'] and link['href'].endswith('.html')
    }
    
    # Convert relative URLs to absolute URLs
    base_url = 'https://travel.state.gov'
    absolute_urls = []
    for url in publication_urls:
        if url.startswith('/'):
            absolute_urls.append(base_url + url)
        elif url.startswith('http'):
            absolute_urls.append(url)
        else:
            absolute_urls.append(base_url + '/' + url)
    
    publication_urls = sorted(absolute_urls, key=lambda url: datetime.strptime(os.path.basename(url).replace('visa-bulletin-for-', '').replace('.html', ''), '%B-%Y'), reverse=True)
    return list(publication_urls)


def normalize(line: str):
    return re.sub(r'\s+', ' ', line.replace('\n', ' ').replace(' ', ' ').strip())

def convert_to_date(value):
    try:
        return datetime.strptime(value, '%d%b%y').date()
    except ValueError:
        return value

def extract_table(table):
    title = 'earlier than'
    underline_tag = table
    max_iterations = 20  # Prevent infinite loop
    iterations = 0
    
    while title == 'earlier than' and iterations < max_iterations:
        underline_tag = underline_tag.find_previous('u')
        if underline_tag is None:
            # No underline tag found - older bulletins may have different structure
            return None
        title = normalize(underline_tag.get_text(separator=' ', strip=True))
        iterations += 1
    
    if iterations >= max_iterations:
        return None
    
    table_rows = table.find_all('tr')
    if not table or len(table_rows) <= 0 or len(table_rows[0].find_all('td')) <= 1:
        return None
    if title not in AVAILABLE_TABLES:
        return None
    title = AVAILABLE_TABLES[title]
    
    # Extract headers from first row explicitly (critical for correct parsing)
    # Headers must be normalized so Country.from_header() can match them correctly
    first_row = table_rows[0]
    header_cells = first_row.find_all(['td', 'th'])
    if not header_cells:
        return None
    headers = [normalize(cell.get_text(separator=' ', strip=True)) for cell in header_cells]
    
    # Extract data rows (skip header row - header already extracted above)
    rows = []
    for row in table_rows[1:]:  # Explicitly skip first row (header)
        cols = [convert_to_date(td.get_text(separator=' ', strip=True)) for td in row.find_all('td')]
        if cols:  # Avoid empty rows
            rows.append(tuple(cols))
    if rows:
        return BulletinTable(title, headers, rows)
    return None

def extract_table_legacy(table):
    """
    Extract table from old bulletin format (2001-2015).
    These bulletins have simpler structure:
    - First cell identifies table: "Family-Sponsored" or "Employment-Based"
    - Only one table per category (equivalent to final_action)
    - No underlined titles before tables
    
    Note: Normalizes visa class names to match modern format for consistency.
    """
    table_rows = table.find_all('tr')
    if not table_rows or len(table_rows) <= 1:
        return None
    
    # Check first row, first cell to identify table type
    first_row = table_rows[0]
    cells = first_row.find_all(['td', 'th'])
    if not cells:
        return None
    
    first_cell_text = normalize(cells[0].get_text(separator=' ', strip=True)).lower()
    
    # Determine table type from first cell
    is_family = 'family' in first_cell_text
    is_employment = 'employment' in first_cell_text
    
    if is_family:
        title = 'family_sponsored_final_actions'
    elif is_employment:
        title = 'employment_based_final_action'
    else:
        return None
    
    # Extract rows (skip header row)
    rows = []
    for row in table_rows[1:]:  # Skip first row (header)
        cols = [convert_to_date(td.get_text(separator=' ', strip=True)) for td in row.find_all('td')]
        if cols and len(cols) > 1:  # Must have visa class + at least one country
            # Normalize visa class for family tables using enum mapping
            if is_family and cols[0]:
                from models.enums.family_preference import FamilyPreference
                raw_class = str(cols[0])
                cols[0] = FamilyPreference.normalize_legacy_name(raw_class)
            
            rows.append(tuple(cols))
    
    if rows:
        # Extract headers from first row
        headers = [normalize(th.get_text(separator=' ', strip=True)) for th in cells]
        return BulletinTable(title, headers, rows)
    
    return None


def extract_tables(html: str) -> list[BulletinTable]:
    """
    Extract all visa cutoff tables from HTML.
    
    Auto-detects format: tries modern format first (2015+), then falls back to legacy format (2001-2015).
    For explicit format selection, use extract_tables_modern() or extract_tables_legacy().
    """
    soup = BeautifulSoup(html, 'html.parser')
    tables = []
    
    # Try modern format first (2015+)
    modern_tables_found = False
    for table in soup.find_all('table'):
        extracted_table = extract_table(table)
        if extracted_table:
            tables.append(extracted_table)
            modern_tables_found = True
    
    # If no modern tables found, try legacy format (2001-2015)
    if not modern_tables_found:
        for table in soup.find_all('table'):
            extracted_table = extract_table_legacy(table)
            if extracted_table:
                tables.append(extracted_table)

    return tables


def extract_tables_modern(html: str) -> list[BulletinTable]:
    """
    Extract tables using modern format parser (2015+).
    """
    soup = BeautifulSoup(html, 'html.parser')
    tables = []
    for table in soup.find_all('table'):
        extracted_table = extract_table(table)
        if extracted_table:
            tables.append(extracted_table)
    return tables


def extract_tables_legacy(html: str) -> list[BulletinTable]:
    """
    Extract tables using legacy format parser (2001-2015).
    """
    soup = BeautifulSoup(html, 'html.parser')
    tables = []
    for table in soup.find_all('table'):
        extracted_table = extract_table_legacy(table)
        if extracted_table:
            tables.append(extracted_table)
    return tables


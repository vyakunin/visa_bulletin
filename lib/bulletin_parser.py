import os
import re
from datetime import datetime

from bs4 import BeautifulSoup

from lib.table import Table

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
    return re.sub(r'\s+', ' ', line.replace('\n', ' ').replace(' ', ' ').strip())

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
    rows = []
    for row in table_rows:  # Skip header row
        cols = [convert_to_date(td.get_text(separator=' ', strip=True)) for td in row.find_all('td')]
        if cols:  # Avoid empty rows
            rows.append(tuple(cols))
    if rows:
        return Table(title, rows[0], rows[1:])
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
        return Table(title, headers, rows)
    
    return None


def extract_tables(html: str) -> list[Table]:
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

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
    publication_urls = sorted(publication_urls, key=lambda url: datetime.strptime(os.path.basename(url).replace('visa-bulletin-for-', '').replace('.html', ''), '%B-%Y'), reverse=True)
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
    while title == 'earlier than':
        underline_tag = underline_tag.find_previous('u')
        title = normalize(underline_tag.get_text(separator=' ', strip=True))
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

def extract_tables(html: str) -> list[Table]:
    soup = BeautifulSoup(html, 'html.parser')
    tables = []
    # Locate and extract tables with titles in <u> tags
    for table in soup.find_all('table'):
        extracted_table = extract_table(table)
        if extracted_table:
            tables.append(extracted_table)

    return tables

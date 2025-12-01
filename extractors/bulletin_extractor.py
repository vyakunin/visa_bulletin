"""
Bulletin Extractor - converts parsed Table objects to structured data

Extracts time-series data from visa bulletin tables and prepares it
for database storage.
"""

from datetime import date
from typing import List, Dict, Any


class BulletinExtractor:
    """Extracts structured data from parsed bulletin tables"""
    
    # Map table titles to category/action type
    TABLE_MAPPINGS = {
        'family_sponsored_final_actions': ('FAMILY_SPONSORED', 'FINAL_ACTION'),
        'family_sponsored_dates_for_filing': ('FAMILY_SPONSORED', 'FILING'),
        'employment_based_final_action': ('EMPLOYMENT_BASED', 'FINAL_ACTION'),
        'employment_based_dates_for_filing': ('EMPLOYMENT_BASED', 'FILING'),
    }
    
    # Map table headers to country codes
    COUNTRY_MAPPINGS = {
        'All Chargeability Areas Except Those Listed': 'ALL',
        'All Chargeability\xa0Areas Except Those Listed': 'ALL',  # Non-breaking space
        'CHINA-mainland born': 'CHINA',
        'CHINA- mainland born': 'CHINA',
        'CHINA-mainland\xa0born': 'CHINA',
        'CHINA- mainland\xa0born': 'CHINA',
        'INDIA': 'INDIA',
        'MEXICO': 'MEXICO',
        'PHILIPPINES': 'PHILIPPINES',
        'EL SALVADOR GUATEMALA HONDURAS': 'EL_SALVADOR_GUATEMALA_HONDURAS',
        'EL SALVADOR\nGUATEMALA\nHONDURAS': 'EL_SALVADOR_GUATEMALA_HONDURAS',
    }
    
    def __init__(self, publication_date: date):
        """
        Initialize extractor for a specific bulletin publication date
        
        Args:
            publication_date: The date of the bulletin (first day of month)
        """
        self.publication_date = publication_date
    
    def extract_from_table(self, table) -> List[Dict[str, Any]]:
        """
        Extract structured data from a parsed Table object
        
        Args:
            table: Table object from lib.table
            
        Returns:
            List of dicts ready for VisaCutoffDate model creation
        """
        results = []
        
        # Get category and action type from table title
        visa_category, action_type = self.TABLE_MAPPINGS.get(
            table.title,
            ('UNKNOWN', 'UNKNOWN')
        )
        
        # Skip first column (it's the class name), rest are countries
        country_headers = table.headers[1:]
        
        for row in table.rows:
            visa_class = row[0]
            cutoff_values = row[1:]
            
            # Create entry for each country
            for country_header, cutoff_value in zip(country_headers, cutoff_values):
                country = self._map_country(country_header)
                
                data = {
                    'visa_category': visa_category,
                    'visa_class': visa_class,
                    'action_type': action_type,
                    'country': country,
                    **self._parse_cutoff_value(cutoff_value)
                }
                
                results.append(data)
        
        return results
    
    def _map_country(self, header: str) -> str:
        """Map table header to country code"""
        # Normalize whitespace
        normalized = ' '.join(header.split())
        return self.COUNTRY_MAPPINGS.get(normalized, normalized)
    
    def _parse_cutoff_value(self, value) -> Dict[str, Any]:
        """
        Parse a cutoff value (date, 'C', or 'U')
        
        Args:
            value: Either a date object, 'C', or 'U'
            
        Returns:
            Dict with cutoff_value, cutoff_date, is_current, is_unavailable
        """
        if isinstance(value, date):
            return {
                'cutoff_value': value.strftime('%Y-%m-%d'),
                'cutoff_date': value,
                'is_current': False,
                'is_unavailable': False,
            }
        elif value == 'C':
            return {
                'cutoff_value': 'C',
                'cutoff_date': None,
                'is_current': True,
                'is_unavailable': False,
            }
        elif value == 'U':
            return {
                'cutoff_value': 'U',
                'cutoff_date': None,
                'is_current': False,
                'is_unavailable': True,
            }
        else:
            # Fallback: treat as string
            return {
                'cutoff_value': str(value),
                'cutoff_date': None,
                'is_current': False,
                'is_unavailable': False,
            }


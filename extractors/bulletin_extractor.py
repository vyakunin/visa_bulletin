"""
Bulletin Extractor - converts parsed Table objects to structured data

Extracts time-series data from visa bulletin tables and prepares it
for database storage.
"""

from datetime import date

from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country
from lib.publication_data import PublicationData


class BulletinExtractor:
    """Extracts structured data from parsed bulletin tables"""
    
    def __init__(self, publication_data: PublicationData):
        """
        Initialize extractor for a specific bulletin
        
        Args:
            publication_data: PublicationData object with URL, content, and date
            
        Example:
            extractor = BulletinExtractor(publication_data)
        """
        self.publication_date = publication_data.publication_date.date()
        self.publication_url = publication_data.url
    
    def extract_from_table(self, table) -> list[dict[str, any]]:
        """
        Extract structured data from a parsed Table object
        
        Args:
            table: Table object from lib.table
            
        Returns:
            List of dicts ready for VisaCutoffDate model creation
        """
        results = []
        
        # Get category and action type from table title using enums
        visa_category = VisaCategory.from_table_title(table.title)
        action_type = ActionType.from_table_title(table.title)
        
        if not visa_category or not action_type:
            # Unknown table type, skip
            return results
        
        # Skip first column (it's the class name), rest are countries
        country_headers = table.headers[1:]
        
        for row in table.rows:
            visa_class = row[0]
            cutoff_values = row[1:]
            
            # Create entry for each country
            for country_header, cutoff_value in zip(country_headers, cutoff_values):
                country = Country.from_header(country_header)
                
                if not country:
                    # Unknown country, skip
                    continue
                
                data = {
                    'visa_category': visa_category.value,
                    'visa_class': visa_class,
                    'action_type': action_type.value,
                    'country': country.value,
                    **self._parse_cutoff_value(cutoff_value)
                }
                
                results.append(data)
        
        return results
    
    def _parse_cutoff_value(self, value) -> dict[str, any]:
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
            # 'C' means Current - use the bulletin's publication date
            return {
                'cutoff_value': 'C',
                'cutoff_date': self.publication_date,
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


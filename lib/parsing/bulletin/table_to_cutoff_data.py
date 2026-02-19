"""
Table to Cutoff Data - converts parsed BulletinTable objects to structured data

Extracts time-series data from visa bulletin tables and prepares it
for database storage.

IMPORTANT: When checking if enum values are None, use explicit `is None` checks,
not falsy checks (`if not value:`). IntegerChoices can have value 0, which is falsy.
For example, Country.ALL = 0, so `if not country:` would incorrectly skip it.
Always use: `if country is None:` instead of `if not country:`
"""

import logging
from datetime import date, datetime
from typing import Union

from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_category import VisaCategory

logger = logging.getLogger(__name__)


class TableToCutoffData:
    """Extracts structured data from parsed bulletin tables"""

    def __init__(self, publication_date_or_data: Union[date, datetime, 'PublicationData'], publication_url: str | None = None):
        """
        Initialize extractor for a specific bulletin
        
        Args:
            publication_date_or_data: Either PublicationData object, publication date, or datetime
            publication_url: URL to the bulletin page (required if first arg is date/datetime)
            
        Example:
            extractor = TableToCutoffData(date(2025, 1, 1), "https://...")
            extractor = TableToCutoffData(publication_data)  # PublicationData object
        """
        # Support both PublicationData object and (date, url) tuple
        from lib.parsing.bulletin.publication_data import PublicationData

        if isinstance(publication_date_or_data, PublicationData):
            pub_data = publication_date_or_data
            pub_date = pub_data.publication_date
            if isinstance(pub_date, datetime):
                self.publication_date = pub_date.date()
            else:
                self.publication_date = pub_date
            self.publication_url = pub_data.url
        else:
            if publication_url is None:
                raise ValueError("publication_url required when first argument is date/datetime")
            pub_date = publication_date_or_data
            if isinstance(pub_date, datetime):
                self.publication_date = pub_date.date()
            else:
                self.publication_date = pub_date
            self.publication_url = publication_url

    @classmethod
    def from_metadata(cls, publication_date: date | None, publication_url: str) -> 'TableToCutoffData':
        """
        Create extractor from metadata (convenience method).
        
        Args:
            publication_date: Publication date or None
            publication_url: URL to the bulletin page
            
        Returns:
            TableToCutoffData instance
        """
        # Use a default date if None (shouldn't happen in practice)
        pub_date = publication_date if publication_date else date.today()
        return cls(pub_date, publication_url)

    def extract_from_table(self, table) -> list[dict[str, any]]:
        """
        Extract structured data from a parsed BulletinTable object
        
        Args:
            table: BulletinTable object from lib.parsing.bulletin.bulletin_table
            
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

                # CRITICAL: Check for None explicitly, not just falsy!
                # Country.ALL = 0, which is falsy, so we must check `country is None`
                if country is None:
                    # Unknown country, skip
                    logger.warning(
                        f"Unknown country header in table '{table.title}': '{country_header}'. "
                        f"Full headers: {country_headers}. Skipping this column."
                    )
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


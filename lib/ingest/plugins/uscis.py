"""USCIS Inventory data source plugin"""

import logging
import re
from pathlib import Path
from typing import Iterator

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from models.ingest.enums import DataDomain, SourceType, FormatVersion
from models.ingest.ingest_run import IngestRun
from models.raw_facts import RawFactsLedger

logger = logging.getLogger(__name__)

class UscisInventoryPlugin(DataSourcePlugin):
    """Plugin for USCIS I-485 Inventory data"""
    
    domain = DataDomain.USCIS
    source_type = SourceType.I485_INVENTORY
    data_dir = 'vqs/uscis_inventory'
    
    def discover_sources(self) -> list[SourceInfo]:
        """
        Discover USCIS inventory files from local directory since scraping is hard.
        """
        sources = []
        # Check local data directory
        base_path = Path("data/sources/uscis_inventory")
        if not base_path.exists():
            return []
            
        for filepath in base_path.glob("*.csv"):
            if "sample" in filepath.name:
                continue
                
            # Create a file:// URL for local files
            url = f"file://{filepath.absolute()}"
            
            sources.append(SourceInfo(
                url=url,
                domain=self.domain.value,
                source_type=self.source_type.value,
                format_version=FormatVersion.MODERN,
                metadata={'discovered_from': 'local_filesystem'}
            ))
            
        return sources
    
    def get_format_version(self, filepath: Path) -> str:
        return FormatVersion.MODERN
        
    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """
        Parse file and aggregate counts by month/country/class/pd_month.
        """
        import csv
        from lib.business.vqs.ingest_utils import normalize_country, normalize_visa_class_inventory, parse_date_str
        
        logger.info(f"Parsing USCIS inventory with aggregation: {filepath}")
        
        agg = {}
        
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                country = normalize_country(row.get('Country', ''))
                visa_class = normalize_visa_class_inventory(row.get('Visa Class', ''))
                pd_str = row.get('Priority Date', '')
                count_str = row.get('Count', '0').replace(',', '')
                
                pd = parse_date_str(pd_str)
                if not pd: continue
                try:
                    count = int(float(count_str))
                except ValueError: continue
                if count <= 0: continue
                
                key = (country, visa_class, pd.year, pd.month)
                agg[key] = agg.get(key, 0) + count
        
        for (country, visa_class, year, month), count in agg.items():
            yield {
                'country': country,
                'visa_class': visa_class,
                'year': year,
                'month': month,
                'count': count
            }

    def transform(self, record: dict) -> RawFactsLedger | None:
        """Transform aggregated record into RawFactsLedger"""
        from models.raw_facts import RawFactsLedger, RawFactSource
        import calendar
        from datetime import date
        
        year = record['year']
        month = record['month']
        
        # Priority Date is usually represented as the 1st of the month for aggregated buckets
        pd_date = date(year, month, 1)
        
        dimensions = {
            "country": record['country'],
            "visa_class": record['visa_class'],
            "priority_date": pd_date.isoformat(),
        }
        
        ref_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        ref_end = date(year, month, last_day)
        
        pub_date = date.today()
        
        return RawFactsLedger(
            source=RawFactSource.USCIS_I485_INVENTORY,
            metric="i485_pending_inventory_monthly",
            dimensions=dimensions,
            value=record['count'],
            reference_period_start=ref_start,
            reference_period_end=ref_end,
            publication_date=pub_date
        )

    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        return ValidationResult(passed=True)

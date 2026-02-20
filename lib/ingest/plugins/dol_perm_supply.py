"""DOL PERM Supply data source plugin (RawFactsLedger)"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urljoin

from lib.business.vqs.ingest_utils import (
    normalize_country,
    normalize_visa_class_perm,
    parse_date_str,
)
from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.parsing.salary.db_importer import PERM_COLUMN_MAPPINGS, get_column_value
from lib.utils.http_utils import fetch_page
from models.ingest.enums import DataDomain, FormatVersion, SourceType
from models.ingest.ingest_run import IngestRun
from models.raw_facts import RawFactsLedger

logger = logging.getLogger(__name__)


class DolPermSupplyPlugin(DataSourcePlugin):
    """Plugin for DOL PERM Disclosure data (Supply/VQS focus)"""

    domain = DataDomain.DOL
    source_type = SourceType.PERM_DISCLOSURE
    data_dir = "vqs/dol_perm"

    # Same base URL as the Salary PERM plugin
    BASE_URL = "https://www.dol.gov/agencies/eta/foreign-labor/performance"

    def discover_sources(self) -> list[SourceInfo]:
        """Discover PERM files (reusing logic but for VQS purpose)"""
        sources = []
        try:
            html = fetch_page(self.BASE_URL)
            pattern = r'href=["\']([^"\']*PERM[^"\']*\.(?:xlsx|csv|XLSX|CSV))["\']'
            matches = re.findall(pattern, html, re.IGNORECASE)

            for match in matches:
                url = urljoin(self.BASE_URL, match)
                # Append fragment to distinguish from Salary/LCA data sources in DB
                url = f"{url}#vqs_supply"

                # We can reuse the same files, just a different source type registration
                sources.append(
                    SourceInfo(
                        url=url,
                        domain=self.domain.value,
                        source_type=self.source_type.value,
                        format_version=FormatVersion.MODERN,
                        metadata={"discovered_from": self.BASE_URL},
                    )
                )
            logger.info(f"Discovered {len(sources)} PERM supply sources")
        except Exception as e:
            logger.error(f"Failed to discover PERM sources: {e}")
        return sources

    def get_format_version(self, filepath: Path) -> str:
        return FormatVersion.MODERN

    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        import csv

        self._current_run = run
        logger.info(f"Parsing PERM supply with aggregation: {filepath}")

        # Aggregate in memory: (country, visa_class, pd_year, pd_month, status) -> count
        agg = {}

        # Local mappings setup
        EXTRA_MAPPINGS = {
            "country": [
                "COUNTRY_OF_CITIZENSHIP",
                "Country_of_Citizenship",
                "FW_INFO_CTRY_OF_CIT",
            ],
            "education": [
                "FOREIGN_WORKER_INFO_EDUCATION",
                "Foreign_Worker_Info_Education",
                "MINIMUM_EDUCATION",
            ],
            "experience_months": [
                "JOB_INFO_EXPERIENCE_NUM_MONTHS",
                "Job_Info_Experience_Num_Months",
                "REQUIRED_EXPERIENCE_MONTHS",
            ],
        }

        with open(filepath, encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = get_column_value(row, PERM_COLUMN_MAPPINGS["case_status"])
                if not status:
                    continue
                status = status.upper()

                pd_val = get_column_value(row, PERM_COLUMN_MAPPINGS["case_submitted"])
                pd = parse_date_str(str(pd_val))
                if not pd:
                    continue

                c_val = get_column_value(row, EXTRA_MAPPINGS["country"])
                country = normalize_country(str(c_val))

                visa_class = normalize_visa_class_perm(row, EXTRA_MAPPINGS)

                key = (country, visa_class, pd.year, pd.month, status)
                agg[key] = agg.get(key, 0) + 1

        # Yield aggregated records
        for (country, visa_class, year, month, status), count in agg.items():
            yield {
                "country": country,
                "visa_class": visa_class,
                "year": year,
                "month": month,
                "status": status,
                "count": count,
            }

    def transform(self, record: dict) -> RawFactsLedger | None:
        import calendar
        from datetime import date

        from models.raw_facts import RawFactsLedger, RawFactSource

        year = record["year"]
        month = record["month"]

        ref_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        ref_end = date(year, month, last_day)

        # Use publication_date from run if available, else today
        pub_date = date.today()
        # if self._current_run... logic here if needed

        dims = {
            "country": record["country"],
            "visa_class": record["visa_class"],
            "status": record["status"],
        }

        return RawFactsLedger(
            source=RawFactSource.DOL_PERM_DISCLOSURE,
            metric="perm_applications",
            dimensions=dims,
            value=record["count"],
            reference_period_start=ref_start,
            reference_period_end=ref_end,
            publication_date=pub_date,
        )

    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        return ValidationResult(passed=True)

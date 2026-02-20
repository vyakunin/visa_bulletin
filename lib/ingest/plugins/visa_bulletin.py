"""Visa Bulletin data source plugin"""

import logging
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.parsing.bulletin.parser import (
    extract_tables,
    extract_tables_legacy,
    extract_tables_modern,
)
from lib.parsing.bulletin.table_to_cutoff_data import TableToCutoffData
from lib.utils.http_utils import fetch_page
from models.bulletin import Bulletin
from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, FormatVersion, SourceType
from models.ingest.ingest_run import IngestRun
from models.visa_cutoff_date import VisaCutoffDate

logger = logging.getLogger(__name__)


class VisaBulletinPlugin(DataSourcePlugin):
    """Plugin for Visa Bulletin HTML pages"""

    domain = DataDomain.VISA_BULLETIN
    source_type = SourceType.BULLETIN
    data_dir = "bulletin/saved_pages"  # Override default data directory (matches legacy structure)
    filename_prefix = "bulletin"

    def __init__(self):
        self._current_run = None

    def discover_sources(self) -> list[SourceInfo]:
        """Discover new Visa Bulletin pages"""
        sources = []
        base_url = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"

        try:
            html = fetch_page(base_url)

            # Find all bulletin links (pattern: /visa-bulletin/YYYY/visa-bulletin-for-MMMM-YYYY.html)
            pattern = r'href=["\']([^"\']*visa-bulletin-for-[^"\']*\.html)["\']'
            matches = re.findall(pattern, html, re.IGNORECASE)

            for match in matches:
                if match.startswith("http"):
                    url = match
                else:
                    url = f"https://travel.state.gov{match}"

                # Extract date from URL
                date_match = re.search(r"(\w+)-(\d{4})", url)
                if date_match:
                    year = int(date_match.group(2))
                    # Map year to format version
                    if year < 2015:
                        format_version = FormatVersion.LEGACY
                    else:
                        format_version = FormatVersion.MODERN
                else:
                    format_version = FormatVersion.UNKNOWN

                sources.append(
                    SourceInfo(
                        url=url,
                        domain=self.domain.value,
                        source_type=self.source_type.value,
                        format_version=format_version,
                        metadata={"discovered_from": base_url},
                    )
                )

            logger.info(f"Discovered {len(sources)} Visa Bulletin sources")
        except Exception as e:
            logger.error(f"Failed to discover Visa Bulletin sources: {e}")

        return sources

    def generate_filename(self, source: DataSource, url_path: str) -> str | None:
        """
        Generate filename from Visa Bulletin URL pattern.

        Extracts date from URL pattern like: /visas/visa-bulletin/2025/visa-bulletin-for-january-2025.html
        """
        filename = Path(url_path).name
        if not filename or not filename.endswith(".html"):
            # Generate filename from URL pattern
            date_match = re.search(r"(\w+)-(\d{4})", source.url)
            if date_match:
                return f"visa-bulletin-for-{date_match.group(1)}-{date_match.group(2)}.html"
        return None  # Use base class default logic

    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Parse Visa Bulletin HTML and yield individual cutoff data records"""
        self._current_run = run

        logger.info(f"[Run {run.id}] Parsing Visa Bulletin: {filepath.name}")

        # Read HTML content
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Extract publication date from URL filename
        filename = Path(urlparse(run.source.url).path).name
        publication_date = None
        try:
            date_str = filename.replace("visa-bulletin-for-", "").replace(".html", "")
            publication_date = datetime.strptime(date_str, "%B-%Y")
        except ValueError:
            logger.warning(f"Could not parse date from filename: {filename}")

        # Extract tables and convert to cutoff data
        # Select parser based on format_version
        format_version = run.source.format_version

        if format_version == FormatVersion.LEGACY:
            tables = extract_tables_legacy(content)
        elif format_version == FormatVersion.MODERN:
            tables = extract_tables_modern(content)
        else:
            # Fallback: auto-detect (tries modern, then legacy)
            tables = extract_tables(content)
        pub_date = publication_date.date() if publication_date else None
        if not pub_date:
            logger.warning(
                f"[Run {run.id}] No publication date extracted, using today's date"
            )
            from datetime import date

            pub_date = date.today()

        extractor = TableToCutoffData(pub_date, run.source.url)

        # Yield each cutoff data record individually
        for table in tables:
            cutoff_data_list = extractor.extract_from_table(table)
            for cutoff_data in cutoff_data_list:
                yield {
                    "_cutoff_data": cutoff_data,
                    "_publication_date": publication_date.date()
                    if publication_date
                    else None,
                    "_publication_url": run.source.url,
                    "_filepath": str(filepath),
                }

    def transform(self, record: dict) -> VisaCutoffDate | None:
        """Transform cutoff data dict into VisaCutoffDate model

        Note:
            Non-plugin-specific errors (ImportError, configuration issues, etc.) should
            propagate to the framework. The orchestrator handles exceptions and decides
            whether to continue processing or abort the run.
        """
        publication_date = record.get("_publication_date")
        publication_url = record.get("_publication_url")
        cutoff_data = record["_cutoff_data"]

        if not publication_date:
            logger.warning("Cannot create cutoff date without publication date")
            return None

        bulletin, _ = Bulletin.objects.get_or_create(
            publication_date=publication_date, defaults={"url": publication_url}
        )

        # Create VisaCutoffDate
        cutoff_date = VisaCutoffDate(
            bulletin=bulletin,
            visa_category=cutoff_data["visa_category"],
            visa_class=cutoff_data["visa_class"],
            action_type=cutoff_data["action_type"],
            country=cutoff_data["country"],
            cutoff_value=cutoff_data["cutoff_value"],
            cutoff_date=cutoff_data["cutoff_date"],
            is_current=cutoff_data["is_current"],
            is_unavailable=cutoff_data["is_unavailable"],
        )

        return cutoff_date

    def get_format_version(self, filepath: Path) -> FormatVersion:
        """Detect format version from filename or content"""

        # Extract year from filename
        year_match = re.search(r"(\d{4})", filepath.name)
        if year_match:
            year = int(year_match.group(1))
            # Map year to format version
            # Visa bulletins changed format around 2015
            if year < 2015:
                return FormatVersion.LEGACY
            else:
                return FormatVersion.MODERN
        return FormatVersion.UNKNOWN

    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        """
        Validate Visa Bulletin data after ingestion.

        Checks:
        - Cutoff dates were created (abort if none)
        - Required fields present
        - Enum values valid
        - Distribution checks
        """
        errors = []
        warnings = []
        details = {}

        # Get publication date from source metadata or URL
        publication_date = run.source.metadata.get("publication_date")
        if not publication_date:
            # Try to extract from URL
            from datetime import datetime

            filename = (
                Path(run.checkpoint.get("filepath", "")).name
                if run.checkpoint.get("filepath")
                else None
            )
            if filename:
                try:
                    date_str = filename.replace("visa-bulletin-for-", "").replace(
                        ".html", ""
                    )
                    publication_date = datetime.strptime(date_str, "%B-%Y").date()
                except (ValueError, AttributeError):
                    pass

        if publication_date:
            if isinstance(publication_date, str):
                from django.utils.dateparse import parse_date

                publication_date = parse_date(publication_date)

            bulletin = Bulletin.objects.filter(
                publication_date=publication_date
            ).first()
            if bulletin:
                cutoff_dates = VisaCutoffDate.objects.filter(bulletin=bulletin)
                record_count = cutoff_dates.count()
                details["records_created"] = record_count
                details["publication_date"] = str(publication_date)

                # CRITICAL: Abort if no cutoff dates created
                if record_count == 0:
                    errors.append(
                        f"No cutoff dates created for bulletin {publication_date} - expected data but got none"
                    )

                if record_count > 0:
                    # Check for required fields
                    missing_category = cutoff_dates.filter(
                        visa_category__isnull=True
                    ).count()
                    missing_class = (
                        cutoff_dates.filter(visa_class__isnull=True)
                        .exclude(visa_class="")
                        .count()
                    )
                    missing_country = cutoff_dates.filter(country__isnull=True).count()

                    if missing_category > 0:
                        errors.append(
                            f"{missing_category} cutoff dates missing visa_category"
                        )
                    if missing_class > 0:
                        errors.append(
                            f"{missing_class} cutoff dates missing visa_class"
                        )
                    if missing_country > 0:
                        errors.append(f"{missing_country} cutoff dates missing country")

                    # Check enum values
                    from models.enums.action_type import ActionType
                    from models.enums.country import Country
                    from models.enums.visa_category import VisaCategory

                    valid_categories = [c.value for c in VisaCategory]
                    valid_actions = [a.value for a in ActionType]
                    valid_countries = [c.value for c in Country]

                    invalid_category = cutoff_dates.exclude(
                        visa_category__in=valid_categories
                    ).count()
                    invalid_action = cutoff_dates.exclude(
                        action_type__in=valid_actions
                    ).count()
                    invalid_country = cutoff_dates.exclude(
                        country__in=valid_countries
                    ).count()

                    if invalid_category > 0:
                        errors.append(
                            f"{invalid_category} cutoff dates have invalid visa_category"
                        )
                    if invalid_action > 0:
                        errors.append(
                            f"{invalid_action} cutoff dates have invalid action_type"
                        )
                    if invalid_country > 0:
                        errors.append(
                            f"{invalid_country} cutoff dates have invalid country"
                        )

                    # Distribution checks
                    categories = cutoff_dates.values_list(
                        "visa_category", flat=True
                    ).distinct()
                    classes = cutoff_dates.values_list(
                        "visa_class", flat=True
                    ).distinct()
                    countries = cutoff_dates.values_list(
                        "country", flat=True
                    ).distinct()

                    details["categories"] = list(categories)
                    details["classes"] = list(classes)[
                        :20
                    ]  # Limit to avoid huge details
                    details["countries"] = list(countries)

                    if len(categories) == 0:
                        warnings.append("No visa categories found in cutoff dates")
                    if len(classes) == 0:
                        warnings.append("No visa classes found in cutoff dates")
                    if len(countries) < 5:
                        warnings.append(
                            f"Unusually few countries ({len(countries)}) - expected more"
                        )
            else:
                errors.append(
                    f"Bulletin not found for publication date {publication_date}"
                )
        else:
            errors.append("Could not determine publication date for validation")

        return ValidationResult(
            passed=len(errors) == 0, errors=errors, warnings=warnings, details=details
        )

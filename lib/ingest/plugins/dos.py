"""DOS Issuance data source plugin"""

import calendar
import csv
import logging
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.utils.http_utils import fetch_page
from models.ingest.enums import DataDomain, FormatVersion, SourceType
from models.ingest.ingest_run import IngestRun
from models.raw_facts import RawFactsLedger, RawFactSource

logger = logging.getLogger(__name__)


class DosIssuancePlugin(DataSourcePlugin):
    """Plugin for DOS Monthly Issuance Statistics (PDFs)"""

    domain = DataDomain.DOS
    source_type = SourceType.ISSUANCE
    data_dir = "vqs/dos_issuance"

    # New URL as of 2024
    BASE_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-statistics/immigrant-visa-statistics/monthly-immigrant-visa-issuances.html"

    def discover_sources(self) -> list[SourceInfo]:
        """Scrape travel.state.gov for monthly issuance reports (PDFs)"""
        sources = []
        try:
            html = fetch_page(self.BASE_URL)
            # Find links to PDFs with "IV Issuances by FSC" or "IV Issuances by Post"
            # We prefer "by FSC" (Foreign State of Chargeability) as it maps to country caps

            # Regex to find PDF links
            # Pattern examples:
            # "March 2024 - IV Issuances by FSC and Visa Class.pdf"
            # "APRIL 2017 - IV Issuances by FSC and Visa Class.pdf"
            pattern = r'href=["\']([^"\']+\.pdf)["\']'
            matches = re.finditer(pattern, html, re.IGNORECASE)

            seen_urls = set()

            for match in matches:
                url = urljoin(self.BASE_URL, match.group(1))
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Filter for "FSC" reports (Foreign State Chargeability)
                if "fsc" in url.lower() or "place of birth" in url.lower():
                    # Try to parse date from URL for metadata
                    # ... (optional)

                    sources.append(
                        SourceInfo(
                            url=url,
                            domain=self.domain.value,
                            source_type=self.source_type.value,
                            format_version=FormatVersion.MODERN,
                            metadata={"discovered_from": self.BASE_URL},
                        )
                    )

            logger.info(f"Discovered {len(sources)} DOS issuance PDF files")

        except Exception as e:
            logger.error(f"Failed to discover DOS sources: {e}")

        return sources

    def get_format_version(self, filepath: Path) -> str:
        return FormatVersion.MODERN

    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        self._current_run = run

        if filepath.suffix.lower() == ".pdf":
            yield from self._extract_pdf_data(filepath)
        elif filepath.suffix.lower() == ".csv":
            # Fallback for old CSVs if any
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    yield row

    def _extract_pdf_data(self, filepath: Path) -> Iterator[dict]:
        """Extract table data from PDF using pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber not installed. Cannot parse DOS PDFs.")
            return

        # Attempt to parse month/year from filename
        # e.g. "APRIL 2017 - IV Issuances..." -> Month=April, Year=2017
        from urllib.parse import unquote

        filename = unquote(filepath.name).lower()

        # Simple extraction of month/year
        month_str = ""
        year_str = ""

        months = [m.lower() for m in calendar.month_name[1:]]
        for m in months:
            # Use word boundaries or space to avoid partial matches
            if re.search(rf"\b{m}\b", filename):
                month_str = m.capitalize()
                break

        # Find 4 digit year (2010-2029) with word boundaries
        year_match = re.search(r"\b20[1-2][0-9]\b", filename)
        if year_match:
            year_str = year_match.group(0)

        # Fiscal Year calculation
        fy = 0
        if month_str and year_str:
            try:
                m_idx = list(calendar.month_name).index(month_str)
                y_val = int(year_str)
                if m_idx >= 10:
                    fy = y_val + 1
                else:
                    fy = y_val
            except Exception:
                pass

        seen_facts = set()

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue

                # Iterate rows
                for row in table:
                    # Clean None values
                    row = [cell.strip() if cell else "" for cell in row]

                    if len(row) < 2:
                        continue

                    # Skip header rows
                    if (
                        "Foreign State" in row[0]
                        or "Visa Class" in row[0]
                        or "Chargeability" in row[0]
                    ):
                        continue

                    country = row[0]
                    visa_class = row[1] if len(row) > 1 else ""
                    count_str = row[-1]

                    # Validate count is a number
                    try:
                        count_val = int(count_str.replace(",", ""))
                    except ValueError:
                        continue

                    if (
                        not country
                        or country == "Grand Total"
                        or "TOTAL" in country.upper()
                    ):
                        continue

                    # Internal deduplication using normalized values
                    from lib.business.vqs.ingest_utils import normalize_country

                    n_country = normalize_country(country)
                    # Get integer value if it's an enum
                    n_country_val = (
                        int(n_country) if hasattr(n_country, "value") else n_country
                    )

                    fact_key = (
                        month_str,
                        year_str,
                        n_country_val,
                        visa_class.upper().strip(),
                    )
                    if fact_key in seen_facts:
                        continue
                    seen_facts.add(fact_key)

                    yield {
                        "Fiscal Year": str(fy),
                        "Month": month_str,
                        "Visa Class": visa_class,
                        "Chargeability Area": country,
                        "Issuance Count": str(count_val),
                    }

    def transform(self, record: dict) -> RawFactsLedger | None:
        from lib.business.vqs.ingest_utils import normalize_country, normalize_month

        # Reuse logic from shared utils
        fy_str = record.get("Fiscal Year", "")
        month_str = record.get("Month", "")
        visa_code = record.get("Visa Class", "").strip()
        country_str = record.get("Chargeability Area", "")
        count_str = record.get("Issuance Count", "0").replace(",", "")

        try:
            fy = int(fy_str) if fy_str else 0
            count = int(float(count_str))
            month = normalize_month(month_str)
        except ValueError:
            return None

        if month == 0 or count <= 0:
            return None

        country = normalize_country(country_str)

        # VQS Class mapping
        # DOS codes: E1, E2, E3, EW, S (4th), C5/T5 (5th)
        v_cat = "Unknown"
        v_upper = visa_code.upper()

        # Post-2021 mapping (Simple codes)
        if v_upper in ["E1", "E11", "E12", "E13"]:
            v_cat = "1st"
        elif v_upper in ["E2", "E21", "E22", "E23"]:
            v_cat = "2nd"
        elif v_upper in ["E3", "E31", "E32", "E34", "E35"]:
            v_cat = "3rd"
        elif v_upper in ["EW", "EW3", "EW4", "EW5"]:
            v_cat = "3rd"  # Other Workers -> 3rd
        elif v_upper.startswith("S") or v_upper.startswith("R") or v_upper == "E4":
            v_cat = "4th"
        elif (
            v_upper.startswith("C5")
            or v_upper.startswith("T5")
            or v_upper.startswith("I5")
            or v_upper.startswith("R5")
            or v_upper == "E5"
        ):
            v_cat = "5th"

        # If unknown, try simplified defaults
        if v_cat == "Unknown":
            if "1" in v_upper:
                v_cat = "1st"
            elif "2" in v_upper:
                v_cat = "2nd"
            elif "3" in v_upper:
                v_cat = "3rd"
            elif "4" in v_upper:
                v_cat = "4th"
            elif "5" in v_upper:
                v_cat = "5th"

        if month >= 10:
            cal_year = fy - 1
        else:
            cal_year = fy

        # Handle 0 year if extraction failed
        if cal_year == 0:
            # Fallback: assume running year
            cal_year = date.today().year

        last_day = calendar.monthrange(cal_year, month)[1]
        ref_start = date(cal_year, month, 1)
        ref_end = date(cal_year, month, last_day)

        # Pub date is roughly end of month
        pub_date = ref_end

        # Prepare dimensions with primitives for JSON serialization
        dims = {
            "country": int(country) if hasattr(country, "value") else country,
            "visa_class": v_cat,
            "raw_code": visa_code,
        }

        return RawFactsLedger(
            source=RawFactSource.DOS_ISSUANCE,
            metric="visa_issuance_monthly",
            dimensions=dims,
            value=count,
            reference_period_start=ref_start,
            reference_period_end=ref_end,
            publication_date=pub_date,
        )

    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        return ValidationResult(passed=True)

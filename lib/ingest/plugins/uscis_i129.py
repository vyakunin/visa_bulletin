"""USCIS I-129 H-1B petition data source plugin (Bloomberg FOIA snapshot).

Reads the zipped CSVs Bloomberg published from its USCIS FOIA litigation
(github.com/BloombergGraphics/2024-h1b-immigration-data, Apache-2.0), one file per
fiscal year FY2021-FY2024. Each row is a lottery registration; only the
selected-and-filed registrations carry a petition (a DOL ETA case number, wage,
worksite, demographics). We ingest exactly those joinable petition rows into
``I129Petition`` — they join to our LCA ``worksite_record`` on the normalized case
number, unlocking actual-pay vs LCA-posted vs prevailing comparisons.

Coverage caveat (surface everywhere downstream): FY2021-FY2024, cap-subject lottery
only, a FROZEN one-time FOIA snapshot — not a live feed. Aggregates only; the
beneficiary survives the FOIA redaction solely as country + birth-year + gender.
Cite as "sourced from USCIS, obtained by Bloomberg."
"""

import logging
import re
import shutil
import zipfile
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import requests

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.utils.http_utils import download_file, get_workspace_dir
from models.enums.visa_program import WageUnit
from models.i129 import (
    FirstDecision,
    I129Petition,
    RegistrationStatus,
    normalize_dol_eta_case_number,
)
from models.ingest.enums import DataDomain, FormatVersion, SourceType
from models.ingest.ingest_run import IngestRun

logger = logging.getLogger(__name__)

_REPO_RAW = (
    "https://github.com/BloombergGraphics/2024-h1b-immigration-data/raw/main/"
)

# fiscal year → list of remote file parts (single .zip, or split .zip.NNN parts).
_FY_FILES: dict[int, list[str]] = {
    2021: ["TRK_13139_FY2021.zip"],
    2022: ["TRK_13139_FY2022.zip"],
    2023: [
        "TRK_13139_FY2023.zip.001",
        "TRK_13139_FY2023.zip.002",
        "TRK_13139_FY2023.zip.003",
    ],
    2024: [
        "TRK_13139_FY2024_single_reg.zip",
        "TRK_13139_FY2024_multi_reg.zip",
    ],
}

# DataSource URLs are case-normalized (lowercased) on ingest-registration, but
# GitHub raw paths are case-SENSITIVE — a lowercased path 404s. The plugin owns the
# canonical filename casing in _FY_FILES, so map a stored URL back to it before fetch.
_CANONICAL_PARTS = {part.lower(): part for parts in _FY_FILES.values() for part in parts}


def _canonical_url(url: str) -> str:
    """Rebuild the case-sensitive GitHub raw URL from a (possibly lowercased) stored URL."""
    name = Path(urlparse(url).path).name
    part = _CANONICAL_PARTS.get(name.lower())
    return _REPO_RAW + part if part else url


_REDACTION_MARKER = "(B)("


def _clean(value) -> str:
    """Strip a raw cell; blank out FOIA-redaction markers."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or _REDACTION_MARKER in text.upper():
        return ""
    return text


def _parse_date(value) -> "datetime | None":
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(value) -> "Decimal | None":
    text = _clean(value).replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return result if result > 0 else None


def _parse_int(value) -> "int | None":
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def _parse_yes_no(value) -> "bool | None":
    text = _clean(value).upper()
    if text in ("Y", "YES", "1", "TRUE"):
        return True
    if text in ("N", "NO", "0", "FALSE"):
        return False
    return None


def _annualize(amount: "Decimal | None", unit: "WageUnit | None") -> "Decimal | None":
    if amount is None:
        return None
    multipliers = {
        WageUnit.YEAR: 1,
        WageUnit.MONTH: 12,
        WageUnit.BI_WEEKLY: 26,
        WageUnit.WEEK: 52,
        WageUnit.HOUR: 2080,
    }
    return amount * multipliers.get(unit, 1)


class I129PetitionPlugin(DataSourcePlugin):
    """Ingest plugin for the Bloomberg I-129 H-1B petition FOIA snapshot."""

    domain = DataDomain.USCIS
    source_type = SourceType.I129
    data_dir = "uscis/i129_data"
    filename_prefix = "i129"

    def discover_sources(self) -> list[SourceInfo]:
        """One source per fiscal year (the first part URL stands in for split sets)."""
        sources = []
        for fiscal_year, parts in _FY_FILES.items():
            for part in parts:
                # FY2024 ships single_reg + multi_reg as two independent files; each
                # is its own source. Split .zip.NNN sets are handled in download() by
                # deriving sibling parts from the .001 URL, so only emit the .001.
                if part.endswith(tuple(f".zip.{i:03d}" for i in range(2, 100))):
                    continue
                sources.append(
                    SourceInfo(
                        url=_REPO_RAW + part,
                        domain=self.domain.value,
                        source_type=self.source_type.value,
                        format_version=FormatVersion.MODERN.value,
                        metadata={
                            "fiscal_year": fiscal_year,
                            "attribution": "sourced from USCIS, obtained by Bloomberg",
                        },
                    )
                )
        logger.info("Discovered %d I-129 source files", len(sources))
        return sources

    def download(self, source: "DataSource", run: IngestRun) -> Path:  # noqa: F821
        """Download the FY zip (concatenating split .zip.NNN parts), extract the CSV.

        Returns the extracted ``.csv`` path. The intermediate zip is deleted after
        extraction (large-file hygiene); a re-run reuses an already-extracted CSV.
        """
        data_dir = get_workspace_dir() / "data" / self.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        url = _canonical_url(source.url)
        filename = Path(urlparse(url).path).name
        if filename.endswith(".zip.001"):
            base, multipart = filename[: -len(".zip.001")], True
        elif filename.endswith(".zip"):
            base, multipart = filename[: -len(".zip")], False
        else:
            base, multipart = Path(filename).stem, False

        csv_path = data_dir / f"{base}.csv"
        if csv_path.exists():
            logger.info("[Run %s] I-129 CSV already extracted: %s", run.id, csv_path)
            self._mark_downloaded(source, csv_path)
            return csv_path

        zip_path = data_dir / f"{base}.zip"
        if multipart:
            self._download_multipart(url, zip_path, data_dir, base, run)
        else:
            logger.info("[Run %s] Downloading I-129 file: %s", run.id, url)
            download_file(url, zip_path)

        logger.info("[Run %s] Extracting CSV from %s", run.id, zip_path.name)
        with zipfile.ZipFile(zip_path) as zf:
            inner = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(inner) as src, open(csv_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        zip_path.unlink(missing_ok=True)

        self._mark_downloaded(source, csv_path)
        return csv_path

    @staticmethod
    def _download_multipart(
        first_url: str, zip_path: Path, data_dir: Path, base: str, run: IngestRun
    ) -> None:
        """Download .zip.001, .002, ... (until a part 404s) and concatenate them."""
        with open(zip_path, "wb") as out:
            part_idx = 1
            while True:
                part_url = re.sub(r"\.zip\.\d+$", f".zip.{part_idx:03d}", first_url)
                part_dest = data_dir / f"{base}.zip.{part_idx:03d}"
                try:
                    download_file(part_url, part_dest)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        break  # no more parts
                    raise
                logger.info("[Run %s] Appended part %d", run.id, part_idx)
                with open(part_dest, "rb") as part_f:
                    shutil.copyfileobj(part_f, out, length=1024 * 1024)
                part_dest.unlink(missing_ok=True)
                part_idx += 1
        if part_idx == 1:
            raise FileNotFoundError(f"No parts downloaded for {first_url}")

    @staticmethod
    def _mark_downloaded(source, dest_path: Path) -> None:
        from django.utils import timezone

        from lib.utils.http_utils import compute_file_hash

        if not source.content_hash:
            source.content_hash = compute_file_hash(dest_path)
        source.downloaded_at = source.downloaded_at or timezone.now()
        source.local_file_path = str(dest_path)
        source.save(
            update_fields=["downloaded_at", "local_file_path", "content_hash"]
        )

    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream the CSV row-by-row, tagging fiscal year + source file."""
        import csv

        fiscal_year = self._fiscal_year_from_name(filepath.name)
        source_file = filepath.name
        start_row = run.checkpoint.get("last_row", 0)

        logger.info(
            "[Run %s] Parsing I-129 CSV %s (FY%s)", run.id, source_file, fiscal_year
        )
        with open(filepath, encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for _ in range(start_row):
                if next(reader, None) is None:
                    break

            row_count = start_row
            for row in reader:
                row_count += 1
                row["_fiscal_year"] = fiscal_year
                row["_source_file"] = source_file
                row["_row_num"] = row_count
                if row_count % 10000 == 0:
                    run.checkpoint["last_row"] = row_count - 1
                    run.save(update_fields=["checkpoint"])
                yield row

        logger.info("[Run %s] Finished parsing %d rows", run.id, row_count)

    @staticmethod
    def _fiscal_year_from_name(name: str) -> int:
        match = re.search(r"FY(\d{4})", name, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    def transform(self, record: dict) -> "I129Petition | None":
        """Build an ``I129Petition`` from a row, or None if it's not a joinable petition.

        Only rows that carry a real DOL ETA case number (the selected-and-filed
        petition universe) are kept — registration-only rows have no wage/worksite/
        join key and are dropped.
        """
        case_number = normalize_dol_eta_case_number(record.get("DOL_ETA_CASE_NUMBER"))
        if not case_number:
            if self._rejection_tracker:
                self._rejection_tracker.record_rejection("no_dol_eta_case_number")
            return None

        wage_unit = WageUnit.from_dol_value(_clean(record.get("WAGE_UNIT")))
        wage_amt = _parse_decimal(record.get("WAGE_AMT"))
        comp_paid_annual = _parse_decimal(record.get("BEN_COMP_PAID"))
        pay_annual = comp_paid_annual or _annualize(wage_amt, wage_unit)

        return I129Petition(
            dol_eta_case_number=case_number,
            fiscal_year=record.get("_fiscal_year", 0),
            lottery_year=_parse_int(record.get("lottery_year")),
            status_type=RegistrationStatus.from_str(_clean(record.get("status_type"))),
            ben_multi_reg_ind=_clean(record.get("ben_multi_reg_ind")) == "1",
            first_decision=FirstDecision.from_str(_clean(record.get("FIRST_DECISION"))),
            first_decision_date=_parse_date(record.get("first_decision_date")),
            received_date=_parse_date(record.get("rec_date")),
            basis_for_classification=_clean(record.get("BASIS_FOR_CLASSIFICATION"))[:1],
            requested_action=_clean(record.get("REQUESTED_ACTION"))[:1],
            valid_from=_parse_date(record.get("valid_from")),
            valid_to=_parse_date(record.get("valid_to")),
            employer_name=_clean(record.get("employer_name"))[:255],
            i129_employer_name=_clean(record.get("i129_employer_name"))[:255],
            fein=_clean(record.get("FEIN"))[:20],
            naics_code=_clean(record.get("NAICS_CODE"))[:20],
            num_emp_in_us=_parse_int(record.get("NUM_OF_EMP_IN_US")),
            h1b_dependent=_parse_yes_no(record.get("S1Q1A")),
            willful_violator=_parse_yes_no(record.get("S1Q1B")),
            job_title=_clean(record.get("JOB_TITLE"))[:255],
            worksite_city=_clean(record.get("WORKSITE_CITY"))[:100],
            worksite_state=_clean(record.get("WORKSITE_STATE"))[:2],
            worksite_zip=_clean(record.get("WORKSITE_ZIP"))[:10],
            full_time=_parse_yes_no(record.get("FULL_TIME_IND")),
            wage_amt=wage_amt,
            wage_unit=wage_unit or "",
            comp_paid_annual=comp_paid_annual,
            pay_annual=pay_annual,
            country_of_birth=_clean(record.get("country_of_birth"))[:80],
            ben_year_of_birth=_parse_int(record.get("ben_year_of_birth")),
            gender=_clean(record.get("gender"))[:10],
            education_code=_clean(record.get("BEN_EDUCATION_CODE"))[:1],
            ed_level=_clean(record.get("ED_LEVEL_DEFINITION"))[:120],
            field_of_study=_clean(record.get("BEN_PFIELD_OF_STUDY"))[:255],
            source_file=record.get("_source_file", "")[:255],
        )

    def get_format_version(self, filepath: Path) -> FormatVersion:
        return FormatVersion.MODERN

    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        """Sanity-check the loaded petitions: at least one row was created."""
        created = run.records_created or 0
        if created == 0:
            return ValidationResult(
                passed=False,
                errors=[f"[Run {run.id}] No I-129 petitions created from source file"],
            )
        return ValidationResult(passed=True, details={"records_created": created})

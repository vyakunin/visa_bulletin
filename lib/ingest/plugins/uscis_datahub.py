"""USCIS H-1B Employer Data Hub ingest plugin (per-employer approval/denial counts).

Reads the USCIS Employer Data Hub per-fiscal-year files into ``UscisEmployerApproval``
— the government-direct, live source for the H-1B petition approval-rate feature
(FY2009+). See docs/department_of_labor/I129_DATA_INTEGRATION_ASSESSMENT.md.

Data quirks handled here (verified against the real files, 2026-07):
  * files are **UTF-16** (BOM), **TAB-separated**, with a leading ``Line by line``
    row-number column and trailing whitespace in some header names;
  * ``Industry (NAICS) Code`` may be a bare code or ``"54 - Professional, ..."``;
  * many rows (esp. FY2009) have a blank employer name — dropped (unlinkable).

Acquisition: the uscis.gov download is Akamai-anti-bot-walled (403 to non-browser
clients); the raw per-year CSVs are mirrored fetchably at github JohnBroberg/H1B_Hub,
``data/Employer_Information_<YYYY>.csv``. This plugin fetches each per-year file from
that mirror into ``data/sources/uscis_datahub/`` when it isn't already cached there,
so ``run_ingest`` is self-sufficient (no hand-placed CSVs needed). Linking to
employer clusters is a separate backfill (lib/business/i129/employer_linker.py),
same as the I-129 petitions.
"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import requests

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.utils.http_utils import download_file, get_workspace_dir
from models.ingest.enums import DataDomain, FormatVersion, SourceType
from models.ingest.ingest_run import IngestRun
from models.uscis_employer import UscisEmployerApproval

logger = logging.getLogger(__name__)

# Per-year files are cached here; missing years are fetched from the mirror below.
# Both discover_sources and download() resolve against this one dir.
_DATA_SUBDIR = "sources/uscis_datahub"

# Mirror config (parameterized so a quarterly re-ingest just bumps _FY_LAST). The
# uscis.gov Data Hub download is Akamai-anti-bot-walled (403 to non-browser clients),
# but the per-fiscal-year raw CSVs are mirrored fetchably on GitHub. If uscis.gov's
# wall is ever bypassable via a real (logged-in) browser session, a browser-fetch
# path could replace this mirror — see docs/.../I129_DATA_INTEGRATION_ASSESSMENT.md.
_MIRROR_BASE_URL = "https://raw.githubusercontent.com/JohnBroberg/H1B_Hub/main/data/"
_FILENAME_TEMPLATE = "Employer_Information_{year}.csv"
_FY_FIRST = 2009  # earliest fiscal year the Data Hub publishes
_FY_LAST = 2024  # bump this when a newer fiscal year is mirrored

# Basename → fiscal-year, resilient to the case-normalization ingest-registration
# applies to DataSource URLs (``Employer_Information_2024.csv`` vs a lowercased form).
_YEAR_RE = re.compile(r"Employer_Information_(\d{4})", re.IGNORECASE)


def _mirror_url_for_year(year: int) -> str:
    """Canonical (case-correct) GitHub raw URL for a fiscal year's file."""
    return _MIRROR_BASE_URL + _FILENAME_TEMPLATE.format(year=year)


def _year_from_name(name: str) -> "int | None":
    match = _YEAR_RE.search(name)
    return int(match.group(1)) if match else None

# Header names (whitespace-stripped) → the row keys we read.
_COL_FISCAL_YEAR = "Fiscal Year"
_COL_EMPLOYER = "Employer (Petitioner) Name"
_COL_TAX_ID = "Tax ID"
_COL_NAICS = "Industry (NAICS) Code"
_COL_CITY = "Petitioner City"
_COL_STATE = "Petitioner State"
_COL_ZIP = "Petitioner Zip Code"
_COL_INIT_APP = "Initial Approval"
_COL_INIT_DEN = "Initial Denial"
_COL_CONT_APP = "Continuing Approval"
_COL_CONT_DEN = "Continuing Denial"


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _parse_int(value) -> int:
    """Parse a count; blanks / non-numeric → 0."""
    s = _clean(value).replace(",", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _detect_encoding(filepath: Path) -> str:
    """UTF-16 (the shipped format) vs UTF-8 — sniff the BOM."""
    with open(filepath, "rb") as f:
        head = f.read(2)
    if head in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    return "utf-8-sig"


class UscisEmployerDataHubPlugin(DataSourcePlugin):
    """Plugin for USCIS H-1B Employer Data Hub per-fiscal-year files."""

    domain = DataDomain.USCIS
    source_type = SourceType.H1B_EMPLOYER_HUB
    data_dir = _DATA_SUBDIR

    def _base_path(self) -> Path:
        return get_workspace_dir() / "data" / _DATA_SUBDIR

    def discover_sources(self) -> list[SourceInfo]:
        """One source per fiscal year in the configured range (fetched by download()).

        Enumerates the FY range against the mirror rather than globbing local files,
        so a fresh checkout with no hand-placed CSVs still ingests every year —
        download() fetches each missing year and caches it locally.
        """
        sources: list[SourceInfo] = []
        for year in range(_FY_FIRST, _FY_LAST + 1):
            sources.append(
                SourceInfo(
                    url=_mirror_url_for_year(year),
                    domain=self.domain.value,
                    source_type=self.source_type.value,
                    format_version=FormatVersion.MODERN,
                    metadata={"fiscal_year": year, "mirror": "JohnBroberg/H1B_Hub"},
                )
            )
        logger.info("Discovered %d USCIS Data Hub source years", len(sources))
        return sources

    def download(self, source, run: IngestRun) -> Path:
        """Return the cached per-year file, fetching it from the mirror if absent.

        The local dir is the cache: an already-present file is reused (no re-download).
        The discover→register step normalizes the URL to a lowercased form, so match
        the basename CASE-INSENSITIVELY against the cached files
        (``Employer_Information_2024.csv`` vs the lowercased URL) — the same
        lowercased-path issue the I-129 plugin handles. On a cache miss, fetch the
        canonical (case-correct) mirror URL and save under the canonical filename.
        """
        base_path = self._base_path()
        base_path.mkdir(parents=True, exist_ok=True)

        want = Path(urlparse(source.url).path).name
        # Cache hit — reuse an already-present file, don't re-download.
        for candidate in base_path.glob("*.csv"):
            if candidate.name.lower() == want.lower():
                logger.info(
                    "[Run %s] USCIS Data Hub file (cached): %s", run.id, candidate
                )
                return candidate

        # Cache miss — fetch from the mirror (uscis.gov itself is Akamai-walled).
        year = _year_from_name(want)
        if year is None:
            raise FileNotFoundError(
                f"Cannot derive a fiscal year from USCIS Data Hub source {source.url}"
            )
        mirror_url = _mirror_url_for_year(year)
        dest_path = base_path / _FILENAME_TEMPLATE.format(year=year)
        logger.info(
            "[Run %s] USCIS Data Hub FY%s not cached; fetching mirror: %s",
            run.id,
            year,
            mirror_url,
        )
        try:
            download_file(mirror_url, dest_path)
        except requests.RequestException as exc:
            dest_path.unlink(missing_ok=True)  # don't leave a partial/empty file
            raise FileNotFoundError(
                f"USCIS Data Hub FY{year} is not cached in {base_path} and the mirror "
                f"fetch failed ({mirror_url}): {exc}. The uscis.gov download is "
                f"Akamai-anti-bot-walled; place the file in {base_path} by hand if the "
                f"mirror is unreachable."
            ) from exc
        return dest_path

    def get_format_version(self, filepath: Path) -> str:
        return FormatVersion.MODERN

    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream the UTF-16 TAB-separated file row-by-row (header keys stripped)."""
        import csv

        encoding = _detect_encoding(filepath)
        source_file = filepath.name
        logger.info(
            "[Run %s] Parsing USCIS Data Hub %s (%s)", run.id, source_file, encoding
        )
        with open(filepath, encoding=encoding, errors="ignore", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames:
                reader.fieldnames = [(fn or "").strip() for fn in reader.fieldnames]
            row_count = 0
            for row in reader:
                row_count += 1
                row["_source_file"] = source_file
                yield row
        logger.info("[Run %s] Parsed %d Data Hub rows", run.id, row_count)

    def transform(self, record: dict) -> "UscisEmployerApproval | None":
        """Build a row, or None for header junk / blank-employer (unlinkable) rows."""
        fiscal_year = _parse_int(record.get(_COL_FISCAL_YEAR))
        employer_name = _clean(record.get(_COL_EMPLOYER))
        if not fiscal_year or not employer_name:
            return None
        return UscisEmployerApproval(
            fiscal_year=fiscal_year,
            employer_name=employer_name[:255],
            tax_id=_clean(record.get(_COL_TAX_ID))[:20],
            naics_code=_clean(record.get(_COL_NAICS))[:120],
            petitioner_city=_clean(record.get(_COL_CITY))[:100],
            petitioner_state=_clean(record.get(_COL_STATE))[:2],
            petitioner_zip=_clean(record.get(_COL_ZIP))[:10],
            initial_approval=_parse_int(record.get(_COL_INIT_APP)),
            initial_denial=_parse_int(record.get(_COL_INIT_DEN)),
            continuing_approval=_parse_int(record.get(_COL_CONT_APP)),
            continuing_denial=_parse_int(record.get(_COL_CONT_DEN)),
            source_file=_clean(record.get("_source_file"))[:255],
        )

    def validate_post_ingest(self, run: IngestRun) -> ValidationResult:
        created = run.records_created or 0
        if created == 0:
            return ValidationResult(
                passed=False,
                errors=[f"[Run {run.id}] No USCIS Data Hub rows created from source file"],
            )
        return ValidationResult(passed=True, details={"records_created": created})

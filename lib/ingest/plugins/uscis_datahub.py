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
clients); the raw per-year CSVs are also mirrored (e.g. github JohnBroberg/H1B_Hub,
``data/Employer_Information_<YYYY>.csv``) which IS fetchable. Place the per-year files
in ``data/sources/uscis_datahub/`` (this plugin discovers them there); the download
step itself is out of band. Linking to employer clusters is a separate backfill
(lib/business/i129/employer_linker.py), same as the I-129 petitions.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

from lib.ingest.base import DataSourcePlugin, SourceInfo, ValidationResult
from lib.utils.http_utils import get_workspace_dir
from models.ingest.enums import DataDomain, FormatVersion, SourceType
from models.ingest.ingest_run import IngestRun
from models.uscis_employer import UscisEmployerApproval

logger = logging.getLogger(__name__)

# Per-year files live here (download is out of band — placed by hand / a fetch
# script). Both discover_sources and download() resolve against this one dir.
_DATA_SUBDIR = "sources/uscis_datahub"

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
        """Discover per-year files in data/sources/uscis_datahub/ (download is out of band)."""
        sources: list[SourceInfo] = []
        base_path = self._base_path()
        if not base_path.exists():
            return sources
        for filepath in sorted(base_path.glob("*.csv")):
            if "sample" in filepath.name.lower():
                continue
            sources.append(
                SourceInfo(
                    url=f"file://{filepath.absolute()}",
                    domain=self.domain.value,
                    source_type=self.source_type.value,
                    format_version=FormatVersion.MODERN,
                    metadata={"discovered_from": "local_filesystem"},
                )
            )
        return sources

    def download(self, source, run: IngestRun) -> Path:
        """Resolve the local per-year file for ``source`` (no HTTP — files are local).

        The discover→register step normalizes the ``file://`` URL to a lowercased
        ``https:///…`` form, so match the basename CASE-INSENSITIVELY against the
        files in the data dir (``Employer_Information_2024.csv`` vs the lowercased
        URL). Same lowercased-path issue the I-129 plugin handles.
        """
        want = Path(urlparse(source.url).path).name.lower()
        base_path = self._base_path()
        for candidate in base_path.glob("*.csv"):
            if candidate.name.lower() == want:
                logger.info("[Run %s] USCIS Data Hub file: %s", run.id, candidate)
                return candidate
        raise FileNotFoundError(
            f"USCIS Data Hub file for {source.url} not found in {base_path}"
        )

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

"""Base classes for data source plugins"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from django.db import models
from django.utils import timezone

from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, SourceType
from models.ingest.ingest_run import IngestRun


@dataclass
class SourceInfo:
    """Information about a discovered data source"""

    url: str
    domain: str
    source_type: str
    format_version: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ValidationResult:
    """
    Result of post-ingest validation.

    Attributes:
        passed: True if validation passed (no errors)
        errors: List of critical errors that should abort the pipeline
        warnings: List of non-critical warnings that should be logged but not abort
        details: Optional dict with additional validation details (for reporting)
    """

    passed: bool
    errors: list[str] = None
    warnings: list[str] = None
    details: dict = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.details is None:
            self.details = {}

        # passed should be False if there are errors
        if self.errors:
            self.passed = False


class DataSourcePlugin(ABC):
    """Base class for all data source plugins"""

    # Must be set by subclasses
    domain: DataDomain
    source_type: SourceType

    # Optional: Override in subclass to customize download behavior
    data_dir: str | None = None  # Relative to workspace/data/ (e.g., 'salary/dol_data')
    filename_prefix: str = (
        ""  # Fallback filename prefix (e.g., 'lca', 'perm', 'bulletin')
    )

    def __init__(self):
        """Initialize plugin with rejection tracker placeholder"""
        self._rejection_tracker = None

    def set_rejection_tracker(self, tracker):
        """
        Set rejection tracker for this run.

        Called by orchestrator before transform stage to enable rejection tracking.
        Plugins can use this to record why records are rejected.

        Args:
            tracker: RejectionTracker instance
        """
        self._rejection_tracker = tracker

    def generate_filename(self, source: DataSource, url_path: str) -> str | None:
        """
        Generate custom filename from URL (optional override).

        If this returns None, the base implementation will use the URL path name
        or generate from filename_prefix.

        Args:
            source: DataSource instance
            url_path: Path portion of the URL (from urlparse)

        Returns:
            Filename string or None to use default logic
        """
        return None

    def download(self, source: DataSource, run: IngestRun) -> Path:
        """
        Download source with resume support (default implementation).

        Subclasses can override if they need custom download logic.

        Args:
            source: DataSource to download
            run: IngestRun for progress tracking

        Returns:
            Path to downloaded file
        """
        import logging
        from urllib.parse import urlparse

        from lib.utils.http_utils import download_file, get_workspace_dir

        logger = logging.getLogger(__name__)

        workspace_dir = get_workspace_dir()

        # Determine data directory
        if self.data_dir:
            data_dir = workspace_dir / "data" / self.data_dir
        else:
            # Default: use domain/source_type
            data_dir = (
                workspace_dir / "data" / self.domain.value / self.source_type.value
            )

        data_dir.mkdir(parents=True, exist_ok=True)

        # Get filename from URL
        url_path = urlparse(source.url).path
        filename = Path(url_path).name

        # Try custom filename generation (subclass override)
        custom_filename = self.generate_filename(source, url_path)
        if custom_filename:
            filename = custom_filename
        elif not filename:
            # Fallback: generate from prefix and source ID
            ext = (
                ".xlsx"
                if self.source_type in [SourceType.LCA, SourceType.PERM]
                else ".html"
            )
            filename = (
                f"{self.filename_prefix or self.source_type.value}_{source.id}{ext}"
            )

        dest_path = data_dir / filename

        # Check if already downloaded (file exists locally)
        # Check file existence first (works even if DB was reset and downloaded_at is None)
        if dest_path.exists():
            if source.downloaded_at:
                logger.info(
                    f"[Run {run.id}] File already downloaded (from DB record): {dest_path}"
                )
            else:
                logger.info(
                    f"[Run {run.id}] File exists locally, skipping download: {dest_path}"
                )

            # Compute hash if not already stored (for existing files)
            from lib.utils.http_utils import compute_file_hash

            if not source.content_hash:
                content_hash = compute_file_hash(dest_path)
                logger.info(
                    f"[Run {run.id}] Computing hash for existing file: {content_hash}"
                )
                source.content_hash = content_hash

            # Update source record to reflect that file exists
            if not source.downloaded_at:
                source.downloaded_at = timezone.now()
                source.local_file_path = str(dest_path)
                source.save(
                    update_fields=["downloaded_at", "local_file_path", "content_hash"]
                )
            elif not source.content_hash:
                source.save(update_fields=["content_hash"])
            return dest_path

        # Download file
        if source.url.startswith("file://"):
            # Handle local file URL
            # Note: urlparse(file://...).path returns absolute path on POSIX, but might be just filename here
            # register_local_files.py creates URLs like file://filename.xlsx
            # If so, we need the local_file_path to know where it is

            # If source.local_file_path is set (which it should be from register_local_files), use it
            if source.local_file_path and Path(source.local_file_path).exists():
                src_path = Path(source.local_file_path)
                logger.info(f"[Run {run.id}] Using existing local file: {src_path}")
                # We can either copy it to dest_path or just return src_path
                # Returning src_path is efficient but might break if code expects file in specific dir
                # Let's copy it to data_dir/filename if it's not already there
                if src_path.absolute() != dest_path.absolute():
                    import shutil

                    logger.info(f"[Run {run.id}] Copying local file to: {dest_path}")
                    shutil.copy2(src_path, dest_path)

                # Update DB record
                if not source.downloaded_at:
                    source.downloaded_at = timezone.now()
                    source.local_file_path = str(dest_path)
                    source.save(update_fields=["downloaded_at", "local_file_path"])

                return dest_path
            else:
                # Try to parse path from URL
                path_from_url = source.url.replace("file://", "")
                if Path(path_from_url).exists():
                    src_path = Path(path_from_url)
                    logger.info(f"[Run {run.id}] Found local file from URL: {src_path}")
                    if src_path.absolute() != dest_path.absolute():
                        import shutil

                        shutil.copy2(src_path, dest_path)
                    return dest_path
                else:
                    raise FileNotFoundError(
                        f"Local file not found for URL: {source.url} (path: {path_from_url})"
                    )

        # Prefer a browser-fetched cached copy when present (Akamai-walled sources
        # like travel.state.gov that the prod box cannot fetch directly — the minipc
        # browser drops the HTML into BULLETIN_HTML_CACHE_DIR). No-op when unset.
        from lib.utils.http_utils import bulletin_cache_file

        cached = bulletin_cache_file(source.url)
        if cached is not None:
            import shutil

            logger.info(f"[Run {run.id}] Using cached HTML: {cached} -> {dest_path}")
            shutil.copy2(cached, dest_path)
        else:
            logger.info(f"[Run {run.id}] Downloading: {source.url}")
            download_file(source.url, dest_path)

        # Compute content hash for duplicate detection
        from lib.utils.http_utils import compute_file_hash

        content_hash = compute_file_hash(dest_path)
        logger.info(f"[Run {run.id}] Content hash: {content_hash}")

        # Update source record with download metadata
        source.downloaded_at = timezone.now()
        source.local_file_path = str(dest_path)
        source.content_hash = content_hash
        source.save(update_fields=["downloaded_at", "local_file_path", "content_hash"])

        return dest_path

    @abstractmethod
    def discover_sources(self) -> list[SourceInfo]:
        """
        Discover new data sources (scrape URLs, check APIs).

        Returns:
            List of SourceInfo objects for discovered sources
        """
        ...

    @abstractmethod
    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """
        Stream parse file, yield dicts, update checkpoint.

        Args:
            filepath: Path to file to parse
            run: IngestRun for checkpoint updates

        Yields:
            Dictionary records from the file
        """
        ...

    @abstractmethod
    def transform(self, record: dict) -> models.Model | None:
        """
        Apply corrections, validation, enrichment.

        Args:
            record: Raw record dictionary from parse stage

        Returns:
            Django model instance or None if record should be filtered out
        """
        ...

    @abstractmethod
    def get_format_version(self, filepath: Path) -> "FormatVersion":  # noqa: F821
        """
        Detect format version for schema changes.

        Args:
            filepath: Path to file

        Returns:
            FormatVersion enum value ('legacy', 'modern', or 'unknown')
        """
        ...

    @abstractmethod
    def validate_post_ingest(self, run: IngestRun) -> "ValidationResult":
        """
        Validate data after ingestion completes.

        This method is called automatically by the pipeline after the load stage.
        It should check for both critical errors (that should abort the pipeline)
        and warnings (non-critical issues).

        Args:
            run: IngestRun instance with completed ingestion

        Returns:
            ValidationResult with errors (abort) and warnings (non-critical)

        Examples of errors (should abort):
        - No records created when expected
        - Required fields missing across all records
        - Data integrity violations (duplicates, invalid references)

        Examples of warnings (should not abort):
        - Some files produced no records (may be expected)
        - Unusual value distributions (may be legitimate)
        - High null rates for optional fields
        - Records outside expected ranges (may be valid edge cases)
        """
        ...

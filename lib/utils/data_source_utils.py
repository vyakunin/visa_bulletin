"""Utilities for working with DataSource files and file operations."""

import csv
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cache for file stats (lazy-loaded)
_file_stats_cache: Optional[dict] = None
_cache_file_path: Optional[Path] = None


def _get_cache_file_path() -> Path:
    """Get the path to the file stats cache file.
    
    Cache path can be overridden via FILE_STATS_CACHE_PATH environment variable
    (useful for tests to use isolated cache files).
    """
    global _cache_file_path
    if _cache_file_path is None:
        # Allow environment variable override (useful for tests)
        env_cache_path = os.environ.get('FILE_STATS_CACHE_PATH')
        if env_cache_path:
            _cache_file_path = Path(env_cache_path)
        else:
            workspace_dir = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', '.'))
            _cache_file_path = workspace_dir / "data/salary/file_counts_cache.json"
    return _cache_file_path


def _load_cache() -> dict:
    """Load file stats cache from disk."""
    global _file_stats_cache
    if _file_stats_cache is not None:
        return _file_stats_cache
    
    cache_file_path = _get_cache_file_path()
    if cache_file_path.exists():
        try:
            with open(cache_file_path, 'r') as f:
                _file_stats_cache = json.load(f)
            logger.debug(f"Loaded file stats cache from {cache_file_path}")
        except Exception as e:
            logger.warning(f"Could not load cache file {cache_file_path}: {e}")
            _file_stats_cache = {}
    else:
        logger.debug(f"Cache file not found, creating new cache")
        _file_stats_cache = {}
    
    return _file_stats_cache


def _save_cache(cache: dict) -> None:
    """Save file stats cache to disk."""
    cache_file_path = _get_cache_file_path()
    try:
        # Ensure directory exists
        cache_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file_path, 'w') as f:
            json.dump(cache, f)
        logger.debug(f"Saved file stats cache to {cache_file_path}")
    except Exception as e:
        logger.warning(f"Could not save cache file {cache_file_path}: {e}")


def get_data_source_filepath(source) -> Optional[Path]:
    """
    Get the file path from a DataSource object, validating it exists.
    
    Args:
        source: DataSource object with local_file_path attribute
        
    Returns:
        Path object if file exists, None otherwise
    """
    if not source.local_file_path:
        return None
    
    filepath = Path(source.local_file_path)
    if not filepath.exists():
        return None
    
    return filepath


def _get_file_stats_impl(
    filepath: Path,
    logger_instance: Optional[logging.Logger] = None
) -> dict:
    """
    Internal implementation: Get comprehensive statistics from input file (Excel/CSV).
    
    This is the main implementation that does all file analysis work.
    For Excel files, uses max_row (fast, O(1) operation).
    For CSV files, counts all lines (O(n) but necessary).
    
    This function is not aware of caching - it always analyzes the file.
    
    Args:
        filepath: Path to the file
        logger_instance: Optional logger for progress messages
        
    Returns:
        Dict with file stats (filepath, filename, size_bytes, row_count, columns)
        
    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file type is not supported
        Exception: If file analysis fails (e.g., corrupted Excel file, CSV parsing error)
    """
    log = logger_instance or logger
    
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    
    stats = {
        'filepath': str(filepath),
        'filename': filepath.name,
        'size_bytes': filepath.stat().st_size,
        'row_count': None,
        'columns': None,
    }
    
    log.debug(f"Getting input stats for filepath: {filepath}")
    
    if filepath.suffix.lower() in ['.xlsx', '.xls']:
        from lib.utils.excel_utils import read_excel_headers, _count_excel_rows
        
        stats['row_count'] = _count_excel_rows(filepath)
        stats['columns'] = read_excel_headers(filepath)
    elif filepath.suffix.lower() == '.csv':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            # Count rows (excluding header)
            line_count = sum(1 for _ in reader)
            stats['row_count'] = line_count
            stats['columns'] = headers
    elif filepath.suffix.lower() == '.html':
        # HTML (e.g. visa bulletin): no generic row count; plugin parses content
        stats['row_count'] = None
        stats['columns'] = None
    else:
        raise ValueError(f"Unknown file type: {filepath.suffix}")
    
    return stats


def get_file_stats(
    filepath: Path,
    logger_instance: Optional[logging.Logger] = None
) -> dict:
    """
    Get comprehensive statistics from input file (Excel/CSV), with caching.
    
    This is a caching facade around _get_file_stats_impl.
    Caching improves performance when analyzing the same files multiple times.
    The cache is stored in data/salary/file_counts_cache.json.
    
    Args:
        filepath: Path to the file
        logger_instance: Optional logger for progress messages
        
    Returns:
        Dict with file stats (filepath, filename, size_bytes, row_count, columns)
        
    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file type is not supported
        Exception: If file analysis fails (e.g., corrupted Excel file, CSV parsing error)
    """
    log = logger_instance or logger
    
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    
    # Load cache and check if already cached
    cache = _load_cache()
    cache_key = filepath.as_uri()
    
    if cache_key in cache:
        cached_value = cache[cache_key]
        if cached_value is not None:
            # Handle backwards compatibility: old cache format stored just row_count (int)
            if isinstance(cached_value, dict):
                log.debug(f"Using cached stats for {filepath.name}")
                return cached_value
            # Old format (int): cache will be migrated to new format (dict) on next save
    
    # Not in cache, analyze file
    stats = _get_file_stats_impl(filepath, log)
    
    # Save to cache
    cache[cache_key] = stats
    _save_cache(cache)
    if stats['row_count'] is not None:
        log.debug(f"Cached stats for {filepath.name}: {stats['row_count']:,} rows")
    
    return stats


def count_file_rows(
    filepath: Path,
    logger_instance: Optional[logging.Logger] = None
) -> int:
    """
    Count data rows in file (excluding header), with caching.
    
    This is a wrapper around get_file_stats that extracts just the row_count.
    For Excel files, uses max_row (fast, O(1) operation).
    For CSV files, counts all lines (O(n) but necessary).
    
    Caching improves performance when counting the same files multiple times.
    The cache is stored in data/salary/file_counts_cache.json.
    
    Args:
        filepath: Path to the file
        logger_instance: Optional logger for progress messages
        
    Returns:
        Row count (excluding header)
        
    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file type is not supported
        Exception: If file analysis fails (e.g., corrupted Excel file, CSV parsing error)
    """
    log = logger_instance or logger
    
    # Check cache first for backwards compatibility with old format (int)
    cache = _load_cache()
    cache_key = filepath.as_uri()
    
    if cache_key in cache:
        cached_value = cache[cache_key]
        if cached_value is not None:
            # Handle backwards compatibility: old cache format stored just row_count (int)
            if isinstance(cached_value, int):
                log.debug(f"Using cached row count for {filepath.name}: {cached_value:,}")
                return cached_value
            elif isinstance(cached_value, dict):
                # New format: extract row_count from stats dict
                row_count = cached_value.get('row_count')
                if row_count is not None:
                    log.debug(f"Using cached row count for {filepath.name}: {row_count:,}")
                    return row_count
    
    # Not in cache, get full stats (which will cache the new format)
    stats = get_file_stats(filepath, logger_instance=log)
    return stats.get('row_count')


def get_fiscal_year_from_filename(filename: str, fallback_url: Optional[str] = None) -> Optional[int]:
    """
    Extract fiscal year from filename, with optional fallback to URL.
    
    Tries multiple patterns:
    1. FY#### pattern (e.g., "LCA_FY2024_Q4.csv" -> 2024)
    2. Any 4-digit year starting with 20 (e.g., "test_2024_data.csv" -> 2024)
    3. If filename extraction fails and fallback_url is provided, try extracting from URL
    
    This is useful for artificial filenames like "lca_367.xlsx" where the original
    filename (with fiscal year) is in the DataSource URL.
    
    Args:
        filename: Filename or path to extract fiscal year from
        fallback_url: Optional URL to extract fiscal year from if filename extraction fails
    
    Returns:
        Fiscal year as integer if found, None otherwise
    
    Examples:
        >>> get_fiscal_year_from_filename('LCA_FY2024_Q4.csv')
        2024
        >>> get_fiscal_year_from_filename('PERM_FY2023.csv')
        2023
        >>> get_fiscal_year_from_filename('test_2024_data.csv')
        2024
        >>> get_fiscal_year_from_filename('lca_367.xlsx')
        None
        >>> get_fiscal_year_from_filename('lca_367.xlsx', 'https://example.com/H-1B_Disclosure_Data_FY2018_EOY.xlsx')
        2018
        >>> get_fiscal_year_from_filename('no_year.csv')
        None
    """
    # Try FY#### pattern first (most specific - 4 digits)
    match = re.search(r'FY(\d{4})', filename, re.IGNORECASE)
    if match:
        return int(match.group(1))
    
    # Try FY## pattern (2 digits - e.g., FY17 = 2017, FY16 = 2016, FY14 = 2014)
    # Use lookahead to ensure it's followed by non-digit (or end of string), not word boundary
    # because _ is a word character and FY14_Q4 would fail with \b
    match = re.search(r'FY(\d{2})(?=\D|$)', filename, re.IGNORECASE)
    if match:
        year_2digit = int(match.group(1))
        # Convert 2-digit year to 4-digit (FY17 -> 2017, FY16 -> 2016, etc.)
        # Assume years 00-99 map to 2000-2099
        return 2000 + year_2digit
    
    # Try to find any 4-digit year starting with 20
    match = re.search(r'20\d{2}', filename)
    if match:
        return int(match.group())
    
    # Fallback to URL if filename extraction failed and URL is provided
    if fallback_url:
        # Extract filename from URL (handle full URLs, file:// URLs, and reimport:// URLs)
        from urllib.parse import urlparse
        # Handle reimport:// scheme (e.g., reimport:///path/to/file.xlsx)
        if fallback_url.startswith('reimport://'):
            # reimport:// URLs are just file paths with a custom scheme
            url_path = fallback_url.replace('reimport://', '')
        else:
            url_path = urlparse(fallback_url).path
        url_filename = Path(url_path).name if url_path else fallback_url
        
        # Try FY#### pattern in URL filename (4 digits)
        match = re.search(r'FY(\d{4})', url_filename, re.IGNORECASE)
        if match:
            return int(match.group(1))
        
        # Try FY## pattern in URL filename (2 digits)
        # Use lookahead to ensure it's followed by non-digit (or end of string)
        match = re.search(r'FY(\d{2})(?=\D|$)', url_filename, re.IGNORECASE)
        if match:
            year_2digit = int(match.group(1))
            # Convert 2-digit year to 4-digit (FY17 -> 2017, FY16 -> 2016, etc.)
            return 2000 + year_2digit
        
        # Try to find any 4-digit year starting with 20 in URL filename
        match = re.search(r'20\d{2}', url_filename)
        if match:
            return int(match.group())
    
    return None


def get_fiscal_year_from_datasource(
    source_file: str,
    data_source: 'DataSource',
    logger_instance: Optional[logging.Logger] = None
) -> Optional[int]:
    """
    Get fiscal year from DataSource using multiple strategies.
    
    For files with artificial names (e.g., lca_362.xlsx), tries multiple strategies:
    1. Extract from filename or DataSource URL (basic fallback)
    2. If URL is file:// or reimport://, check alternative DataSources with same local_file_path
    3. Check IngestRun records for original URL information
    4. Check IngestRun checkpoints for original filename
    5. Try extracting from DataSource metadata
    
    This is the sophisticated version used by both ingestion plugins and fix scripts.
    
    Args:
        source_file: Source filename (e.g., 'lca_367.xlsx')
        data_source: DataSource instance to extract fiscal year from
        logger_instance: Optional logger for debug messages
    
    Returns:
        Fiscal year if found, None otherwise
    
    Examples:
        >>> source = DataSource.objects.get(id=361)
        >>> get_fiscal_year_from_datasource('lca_361.xlsx', source)
        2018
    """
    if logger_instance is None:
        logger_instance = logger
    
    # Strategy 1: Try basic extraction from filename and URL
    fiscal_year = get_fiscal_year_from_filename(source_file, fallback_url=data_source.url)
    
    # Strategy 2: If URL is file:// or reimport://, try advanced strategies
    if fiscal_year is None and (data_source.url.startswith('file://') or data_source.url.startswith('reimport://')):
        # Strategy 2a: Check alternative DataSources with same local_file_path
        if data_source.local_file_path:
            # Import here to avoid circular dependencies
            from models.ingest.data_source import DataSource as DataSourceModel
            from django.db.models import Q
            
            other_sources = DataSourceModel.objects.filter(
                local_file_path=data_source.local_file_path
            ).exclude(id=data_source.id)
            
            for alt_source in other_sources:
                alt_fiscal_year = get_fiscal_year_from_filename(source_file, fallback_url=alt_source.url)
                if alt_fiscal_year:
                    logger_instance.debug(f"Found fiscal year from alternative DataSource {alt_source.id}: {alt_source.url}")
                    return alt_fiscal_year
        
        # Strategy 2b: Check IngestRun records for original URL info
        from models.ingest.ingest_run import IngestRun
        runs = IngestRun.objects.filter(source=data_source).order_by('-started_at')
        for run in runs:
            # Check if source URL changed (some runs might have been from web downloads)
            if run.source.url and not run.source.url.startswith('file://') and not run.source.url.startswith('reimport://'):
                fiscal_year = get_fiscal_year_from_filename(source_file, fallback_url=run.source.url)
                if fiscal_year:
                    return fiscal_year
            
            # Check checkpoint for original filename
            if run.checkpoint and isinstance(run.checkpoint, dict):
                checkpoint_filepath = run.checkpoint.get('filepath', '')
                if checkpoint_filepath:
                    checkpoint_filename = Path(checkpoint_filepath).name
                    if checkpoint_filename != source_file:
                        logger_instance.debug(f"Trying checkpoint filename: {checkpoint_filename}")
                        fiscal_year = get_fiscal_year_from_filename(checkpoint_filename)
                        if fiscal_year:
                            return fiscal_year
        
        # Strategy 2c: Try extracting from metadata
        if data_source.metadata:
            original_filename = data_source.metadata.get('original_filename') or data_source.metadata.get('filename')
            if original_filename and original_filename != source_file:
                logger_instance.debug(f"Trying metadata filename: {original_filename}")
                fiscal_year = get_fiscal_year_from_filename(original_filename)
                if fiscal_year:
                    return fiscal_year
    
    return fiscal_year


def get_source_file_date(filepath: Path, data_source: 'DataSource') -> datetime | None:
    """
    Get source file date with validation against filename-extracted year.
    
    Priority order:
    1. Extract fiscal year from filename
    2. Get file modification time (mtime)
    3. Validate: If mtime year matches extracted year → use mtime
    4. If mtime year doesn't match → use January 1st of extracted year (01.01.YYYY)
    5. Fallback to DataSource.downloaded_at if mtime unavailable
    6. Final fallback: January 1st of extracted year if no mtime but have year
    
    This ensures we trust the filename-extracted year over unreliable file dates.
    
    Args:
        filepath: Path to the source file
        data_source: DataSource instance (for fallback to downloaded_at)
    
    Returns:
        datetime object representing the source file date, or None if unavailable
    """
    # Step 1: Extract fiscal year from filename
    fiscal_year = get_fiscal_year_from_filename(filepath.name, fallback_url=data_source.url)
    
    # Step 2: Get file modification time
    mtime = None
    if filepath.exists():
        try:
            mtime_timestamp = filepath.stat().st_mtime
            mtime = datetime.fromtimestamp(mtime_timestamp)
        except (OSError, ValueError):
            # File doesn't exist or can't read mtime
            pass
    
    # Step 3 & 4: Validate mtime against extracted year
    if mtime and fiscal_year:
        mtime_year = mtime.year
        if mtime_year == fiscal_year:
            # mtime year matches extracted year → use mtime
            return mtime
        else:
            # mtime year doesn't match → use January 1st of extracted year
            return datetime(fiscal_year, 1, 1)
    elif fiscal_year:
        # Have fiscal year but no mtime → use January 1st of extracted year
        return datetime(fiscal_year, 1, 1)
    elif mtime:
        # Have mtime but no fiscal year → use mtime
        return mtime
    
    # Step 5: Fallback to DataSource.downloaded_at
    if data_source.downloaded_at:
        return data_source.downloaded_at
    
    # Step 6: No date available
    return None

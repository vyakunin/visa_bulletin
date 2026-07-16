"""Shared HTTP and file utilities for data fetching scripts"""

import hashlib
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


def get_workspace_dir() -> Path:
    """
    Get workspace directory from Bazel environment or fallback to script directory.

    When running via Bazel py_binary directly (./bazel-bin/...), BUILD_WORKSPACE_DIRECTORY
    is not set and __file__ is inside runfiles; use cwd so downloads persist in project root.
    """
    env_root = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if env_root:
        return Path(env_root)
    # Running from binary: __file__ is in runfiles; cwd is typically project root
    if "runfiles" in str(Path(__file__).resolve()):
        return Path(os.getcwd())
    return Path(__file__).parent.parent


def bulletin_cache_file(url: str) -> Path | None:
    """Return a pre-fetched HTML cache file for ``url``, or None.

    When ``BULLETIN_HTML_CACHE_DIR`` is set and it contains a file whose name equals
    the URL path's basename, that file is used instead of a network fetch. This is how
    browser-fetched travel.state.gov pages (Akamai wall bypass — see
    ``scripts/fetch_bulletin_via_browser.py``) are fed to the prod ingest, which has no
    browser. A pure no-op when the env var is unset, so existing flows are untouched.
    """
    cache_dir = os.environ.get("BULLETIN_HTML_CACHE_DIR")
    if not cache_dir:
        return None
    name = Path(urlparse(url).path).name
    if not name:
        return None
    candidate = Path(cache_dir) / name
    return candidate if candidate.is_file() else None


def fetch_page(url: str, timeout: int = 30) -> str:
    """
    Fetch HTML page content from URL.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds

    Returns:
        HTML content as string

    Raises:
        requests.RequestException: If request fails
    """
    cached = bulletin_cache_file(url)
    if cached is not None:
        logger.info(f"Using cached HTML for {url}: {cached}")
        return cached.read_text(encoding="utf-8", errors="ignore")
    logger.info(f"Fetching: {url}")
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def download_file(url: str, dest_path: Path, timeout: int = 60) -> Path:
    """
    Download a file from URL to destination path.

    Args:
        url: URL to download from
        dest_path: Destination file path
        timeout: Request timeout in seconds

    Returns:
        Path to downloaded file

    Raises:
        requests.RequestException: If download fails
    """
    logger.info(f"Downloading: {url}")
    logger.info(f"  Saving to: {dest_path}")

    response = requests.get(url, stream=True, timeout=timeout)
    response.raise_for_status()

    # Get file size if available
    total_size = int(response.headers.get("content-length", 0))
    if total_size:
        logger.info(f"  File size: {total_size / (1024 * 1024):.1f} MB")

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size and downloaded % (1024 * 1024) == 0:  # Log every MB
                    percent = (downloaded / total_size) * 100
                    logger.info(f"  Progress: {percent:.1f}%")

    logger.info(f"  ✓ Downloaded: {dest_path.name}")
    return dest_path


def is_file_saved(url: str, data_dir: Path) -> bool:
    """
    Check if a file from URL is already saved locally.

    Args:
        url: URL to check
        data_dir: Directory where files are saved

    Returns:
        True if file exists locally
    """
    filename = os.path.basename(urlparse(url).path)
    return (data_dir / filename).exists()


def compute_file_hash(filepath: Path) -> str:
    """
    Compute SHA256 hash of file content.

    This is used to detect duplicate files even when URLs change.
    Files with identical content will have the same hash regardless of URL.

    Args:
        filepath: Path to file

    Returns:
        SHA256 hash as hex string (64 characters)
    """
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        # Read in chunks to handle large files efficiently
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

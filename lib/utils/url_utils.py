"""URL utilities for canonical form and deduplication."""

from urllib.parse import urlparse, urlunparse


def normalize_source_url(url: str) -> str:
    """
    Return a canonical URL for deduplication so the same logical source
    is not treated as new when the URL format differs.

    - Scheme -> https (http and https match)
    - Netloc -> lowercase
    - Path -> lowercase, no fragment, no query, no trailing slash
      (DOS/travel.state.gov and DOL use case-insensitive paths; lowercasing
      avoids duplicate rows when discovery returns APRIL vs april etc.)
    """
    if not url or not url.strip():
        return url
    parsed = urlparse(url.strip())
    scheme = "https"
    netloc = (parsed.netloc or "").lower()
    path = (parsed.path or "/").rstrip("/") or "/"
    path = path.lower()
    normalized = urlunparse((scheme, netloc, path, "", "", ""))
    return normalized


def path_basename_from_url(url: str) -> str:
    """Return the last path segment (filename) for same-file dedup when paths differ."""
    if not url or not url.strip():
        return ""
    parsed = urlparse(url.strip())
    path = (parsed.path or "").strip("/")
    return path.rsplit("/", 1)[-1] if path else ""

"""Internet Archive (Wayback) CDX lookups for bulletin release dates.

``Bulletin.publication_date`` is the *governing* month, and ``fetched_at`` only
approximates the real State Department release date for bulletins our own cron
ingested live (4 of 290 rows as of 2026-07). For everything older, the earliest
Wayback capture of the bulletin's travel.state.gov URL is the best obtainable
proxy.

That proxy is an **upper bound**: the crawler sees the page some time *after*
State posts it. Measured against the four live-ingested bulletins the lag is
small (~1-3 days), but it grows in years when travel.state.gov was crawled less
often, so callers must treat a wayback-sourced date as "released on or before"
and weigh it with :func:`capture_gap_days` (the spacing between the first and
second capture, a per-URL crawl-density proxy).

The CDX endpoint is rate-limited and returns sporadic 503s, so every query
retries with backoff and responses are cached on disk — the 290-URL backfill is
re-runnable without re-hitting the API.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"

# The archive rejects the python-requests default UA often enough to matter.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MAX_ATTEMPTS = 5
_BACKOFF_BASE_S = 2.0
# Be a good citizen: the archive asks for well under 1 req/s sustained.
_MIN_INTERVAL_S = 1.0

_last_request_at = 0.0


@dataclass(frozen=True)
class CaptureHistory:
    """Wayback capture timestamps for one URL, oldest first."""

    url: str
    captures: tuple[datetime, ...]

    @property
    def first_capture(self) -> datetime | None:
        return self.captures[0] if self.captures else None

    @property
    def capture_gap_days(self) -> int | None:
        """Days between the first and second capture — a crawl-density proxy.

        A small gap means the URL was being crawled often around its first
        capture, so the first capture is close to the real publication moment.
        A large gap means the crawler was sparse there and the first capture may
        overstate the release date by a comparable margin.
        """
        if len(self.captures) < 2:
            return None
        return (self.captures[1] - self.captures[0]).days


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - elapsed)
    _last_request_at = time.monotonic()


def _cache_path(cache_dir: Path | None, url: str) -> Path | None:
    if cache_dir is None:
        return None
    slug = url.rstrip("/").rsplit("/", 1)[-1] or "index"
    return cache_dir / f"{slug}.cdx.json"


def fetch_captures(
    url: str,
    *,
    limit: int = 10,
    cache_dir: Path | None = None,
    timeout: int = 60,
) -> CaptureHistory:
    """Return the oldest ``limit`` successful captures of ``url``, oldest first.

    Results are cached under ``cache_dir`` (when given) keyed by the URL's last
    path segment. A URL the archive has never captured yields an empty history
    and is cached as such, so a re-run does not re-query it.
    """
    cached = _cache_path(cache_dir, url)
    if cached is not None and cached.exists():
        rows = json.loads(cached.read_text())
        return _history_from_rows(url, rows)

    rows = _query_cdx(url, limit=limit, timeout=timeout)
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(rows))
    return _history_from_rows(url, rows)


def _query_cdx(url: str, *, limit: int, timeout: int) -> list[str]:
    """Raw CDX query -> list of 14-digit capture timestamps (oldest first)."""
    params = {
        "url": url.replace("https://", "").replace("http://", ""),
        "output": "json",
        "limit": str(limit),
        "filter": "statuscode:200",
        "collapse": "timestamp:8",  # at most one capture per day
    }
    last_error: Exception | str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        _throttle()
        try:
            resp = requests.get(
                CDX_ENDPOINT,
                params=params,
                timeout=timeout,
                headers={"User-Agent": _USER_AGENT},
            )
        except requests.RequestException as exc:  # transient network blip
            last_error = exc
        else:
            if resp.status_code == 200:
                body = resp.text.strip()
                if not body:
                    return []  # archive has no captures for this URL
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError as exc:
                    last_error = exc
                else:
                    # First row is the header; column 1 is the timestamp.
                    return [row[1] for row in payload[1:]]
            else:
                last_error = f"HTTP {resp.status_code}"

        if attempt < _MAX_ATTEMPTS:
            delay = _BACKOFF_BASE_S * (2 ** (attempt - 1))
            logger.warning(
                "CDX query failed for %s (%s); retry %d/%d in %.0fs",
                url, last_error, attempt, _MAX_ATTEMPTS, delay,
            )
            time.sleep(delay)

    raise RuntimeError(f"CDX query failed for {url} after {_MAX_ATTEMPTS} attempts: {last_error}")


def _history_from_rows(url: str, rows: list[str]) -> CaptureHistory:
    stamps = []
    for raw in rows:
        try:
            stamps.append(datetime.strptime(raw, "%Y%m%d%H%M%S"))
        except (TypeError, ValueError):
            logger.warning("Skipping unparseable CDX timestamp %r for %s", raw, url)
    return CaptureHistory(url=url, captures=tuple(sorted(stamps)))


def first_capture_date(
    url: str,
    *,
    cache_dir: Path | None = None,
) -> tuple[date | None, int | None]:
    """``(first capture date, capture gap days)`` for ``url``; ``(None, None)`` if unarchived."""
    history = fetch_captures(url, cache_dir=cache_dir)
    first = history.first_capture
    return (first.date() if first else None, history.capture_gap_days)

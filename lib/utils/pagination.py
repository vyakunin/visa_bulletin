"""Pagination utilities for Django views

Provides reusable pagination calculation and query string building.
Keyset (cursor) pagination uses opaque SIGNED cursor strings; format is internal.
"""

from typing import NamedTuple

from django.core import signing

# Hard cap on page number for offset-based listing pages. Postgres has to
# materialize and sort `(page - 1) * per_page` rows just to skip them — at
# page=1263 that's 63k+ sorted rows on a filtered query, which is what
# pushed /salaries/ and /worksites/ into shm exhaustion under bot crawls.
# Past page 100 the long tail is uninteresting to real users (no one
# scrolls 5000 rows deep into a salary list) and the URLs only exist
# because crawlers walk pagination links. Returning 410 Gone above this
# cap kills the bot pattern + the slow-tail in one move.
MAX_PAGE = 100

# Depth cap for the DIRECTORY indexes (/employers/), which are a different
# problem from the salary long tail: deep index pagination is a free
# full-table export, and that is what a distributed scraper pool harvests.
# Measured 2026-07-29 over 48h of origin logs: a rotating proxy pool walked
# `?cursor=…&page=18..32` at 955 requests from 939 distinct IPs (1.02 req/IP,
# 98% no-referer). Nothing per-IP can see that, so the answer is to remove the
# prize rather than argue about who is asking.
#
# Costs real users nothing, measured rather than assumed: over 2026-06-29..07-29
# GSC recorded 16 clicks on bare /employers/ and ZERO clicks on every deep
# paginated URL (they carry 1-6 impressions each, most of which GSC itself
# flags as megasitelink bookkeeping). Employer PROFILE discovery does not
# depend on this surface either — the sitemap emits /employer/<slug>/ directly.
MAX_INDEX_PAGE = 10

# Salt scopes the signature to this use, so a cursor cannot be replayed into
# any other signed-value context in the app.
_KEYSET_SALT = "vb.pagination.keyset.v1"


class KeysetCursor(NamedTuple):
    """A decoded, signature-verified keyset position."""

    direction: str  # "next" or "prev"
    order_value: int
    pk: int
    page: int


def encode_keyset_cursor(
    order_value: int, pk: int, direction: str = "next", page: int = 1
) -> str:
    """
    Encode a SIGNED keyset cursor for pagination. Opaque to callers.

    The cursor is signed (Django SECRET_KEY) and carries its own page depth.
    Both properties are load-bearing for `MAX_INDEX_PAGE`: the cursor — not the
    `page` query param — is what actually selects rows, so a cap enforced only
    on `page` is bypassed by sending `page=1` alongside a hand-built deep
    cursor. Signing means the only cursors the view honours are ones it issued,
    and it issues none past the cap.

    Args:
        order_value: Value used for ordering (e.g. total count or total_lca_count).
        pk: Primary key of the row (for tiebreaker).
        direction: "next" or "prev" so the view knows how to apply the cursor.
        page: 1-indexed depth this cursor lands on, bound into the signature.

    Returns:
        Opaque signed cursor string.
    """
    return signing.dumps(
        {"d": direction, "o": order_value, "p": pk, "n": page},
        salt=_KEYSET_SALT,
        compress=True,
    )


def decode_keyset_cursor(cursor: str) -> KeysetCursor | None:
    """
    Decode and verify a keyset cursor. Returns None if absent, forged or stale.

    None is a soft failure by design: the caller falls back to offset
    pagination for the requested page, which is itself depth-capped. So a
    visitor holding an old-format bookmark still lands on the right page, while
    a forged deep cursor buys nothing.
    """
    if not cursor or not cursor.strip():
        return None
    try:
        data = signing.loads(cursor, salt=_KEYSET_SALT)
        direction = data["d"]
        if direction not in ("next", "prev"):
            return None
        return KeysetCursor(
            direction=direction,
            order_value=int(data["o"]),
            pk=int(data["p"]),
            page=int(data["n"]),
        )
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None


def calculate_pagination_info(total_results: int, page: int, per_page: int) -> dict:
    """
    Calculate pagination metadata.

    Args:
        total_results: Total number of results
        page: Current page number (1-indexed)
        per_page: Number of results per page

    Returns:
        Dictionary with:
        - page: Normalized page number
        - total_pages: Total number of pages
        - offset: Database offset for slicing
        - page_range: List of page numbers to display (with ellipsis removed)
    """
    total_pages = (total_results + per_page - 1) // per_page
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    offset = (page - 1) * per_page

    # Calculate page range for pagination display
    if total_pages <= 7:
        page_range = list(range(1, total_pages + 1))
    elif page <= 4:
        page_range = list(range(1, 6)) + ["...", total_pages]
    elif page >= total_pages - 3:
        page_range = [1, "..."] + list(range(total_pages - 4, total_pages + 1))
    else:
        page_range = [1, "..."] + list(range(page - 1, page + 2)) + ["...", total_pages]

    return {
        "page": page,
        "total_pages": total_pages,
        "offset": offset,
        "page_range": [p for p in page_range if p != "..."],
    }


def build_pagination_query_string(
    params: dict, param_mapping: dict[str, str] | None = None
) -> str:
    """
    Build query string for pagination links (without page param).

    Args:
        params: Dictionary of filter parameters
        param_mapping: Optional mapping from param keys to URL param names.
                      If None, uses default mapping for common params.
                      Format: {'internal_key': 'url_param_name'}

    Returns:
        URL query string (e.g., "q=engineer&state=CA&year=2023")
    """
    if param_mapping is None:
        # Default mapping for common parameters
        param_mapping = {
            "query": "q",
            "employer_filter": "employer",
            "employer_slug_filter": "employer_slug",
            "city_filter": "city",
            "state_filter": "state",
            "program_filter": "program",
            "year_filter": "year",
        }

    pagination_parts = []
    for internal_key, url_param in param_mapping.items():
        value = params.get(internal_key)
        if value:
            pagination_parts.append(f"{url_param}={value}")

    return "&".join(pagination_parts)

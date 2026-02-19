"""Pagination utilities for Django views

Provides reusable pagination calculation and query string building.
Keyset (cursor) pagination uses opaque cursor strings; format is internal.
"""

import base64


def encode_keyset_cursor(order_value: int, pk: int, direction: str = "next") -> str:
    """
    Encode a keyset cursor for pagination. Opaque to callers.
    
    Args:
        order_value: Value used for ordering (e.g. total count or total_lca_count).
        pk: Primary key of the row (for tiebreaker).
        direction: "next" or "prev" so the view knows how to apply the cursor.
    
    Returns:
        Opaque cursor string (base64-encoded "direction:order_value:pk").
    """
    raw = f"{direction}:{order_value}:{pk}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_keyset_cursor(cursor: str) -> tuple[str, int, int] | None:
    """
    Decode a keyset cursor. Returns None if invalid.
    
    Returns:
        (direction, order_value, pk) or None. direction is "next" or "prev".
    """
    if not cursor or not cursor.strip():
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        parts = raw.split(":", 2)
        if len(parts) != 3:
            return None
        direction, order_value_str, pk_str = parts
        if direction not in ("next", "prev"):
            return None
        return (direction, int(order_value_str), int(pk_str))
    except (ValueError, UnicodeDecodeError):
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
        page_range = list(range(1, 6)) + ['...', total_pages]
    elif page >= total_pages - 3:
        page_range = [1, '...'] + list(range(total_pages - 4, total_pages + 1))
    else:
        page_range = [1, '...'] + list(range(page - 1, page + 2)) + ['...', total_pages]

    return {
        'page': page,
        'total_pages': total_pages,
        'offset': offset,
        'page_range': [p for p in page_range if p != '...'],
    }


def build_pagination_query_string(params: dict, param_mapping: dict[str, str] | None = None) -> str:
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
            'query': 'q',
            'employer_filter': 'employer',
            'city_filter': 'city',
            'state_filter': 'state',
            'program_filter': 'program',
            'year_filter': 'year',
        }

    pagination_parts = []
    for internal_key, url_param in param_mapping.items():
        value = params.get(internal_key)
        if value:
            pagination_parts.append(f'{url_param}={value}')

    return '&'.join(pagination_parts)











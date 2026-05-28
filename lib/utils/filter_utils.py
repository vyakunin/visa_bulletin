"""Generic filter application utilities for Django querysets"""

from models.enums.visa_program import VisaProgram


def apply_text_search_filter(queryset, query: str, fields: list[str]):
    """
    Apply case-insensitive text search across multiple fields.

    Implementation note (PostgreSQL planner workaround):

    Django's ``__icontains`` emits ``UPPER(field::text) LIKE UPPER(%s)`` —
    the existing ``gin (UPPER(...) gin_trgm_ops)`` indexes match this
    predicate. BUT when the caller also chains
    ``order_by('-wage_annual', '-fiscal_year')[:N]`` (the
    salary_search_view / worksite_search_view list path), the planner falls
    into a classic LIMIT-pessimization: it picks
    ``Index Scan Backward on salary_record_wage_annual_*`` and filters the
    ILIKE predicate inline, expecting the LIMIT to be reached quickly.
    For low-match-low-wage keywords (CASHIER, KEEPER, COOK, MAID) it scans
    ~1.2M heap rows before finding 50 matches → 10-15s.

    The fix is to *force materialization* of the trigram filter as a
    separate plan step. PostgreSQL treats a subquery with ``OFFSET 0`` as
    an optimization fence (will not inline it). We inject
    ``WHERE id IN (SELECT id FROM <table> WHERE <UPPER-LIKE-OR-clauses> OFFSET 0)``
    via ``.extra(where=...)``. With this fence the planner picks Bitmap Heap
    Scan via the trigram indexes (~30ms) and Nested Loop joins by pkey to
    the outer ORDER BY / LIMIT — total ~50ms for the same CASHIER query.

    Args:
        queryset: Django queryset to filter
        query: Search query string
        fields: List of field names to search

    Returns:
        Filtered queryset
    """
    if not query or len(query.strip()) < 3:
        # Trigrams need ≥3 chars to use the GIN index. Patterns of 1-2 chars
        # match every row and PostgreSQL falls back to a sequential scan on
        # the full table — ~22s on /salaries/?q=R, ~5s on q=ENGINEERS truncated
        # by a deep page=N. Treat short q the same as no q (the result is
        # effectively meaningless anyway). Notion 36662b8d residual fix.
        return queryset

    model = queryset.model
    table = model._meta.db_table
    fragments = []
    params: list[str] = []
    pattern = f"%{query}%"
    for field in fields:
        column = model._meta.get_field(field).column
        fragments.append(
            f'UPPER("{table}"."{column}"::text) LIKE UPPER(%s)'
        )
        params.append(pattern)
    or_clauses = " OR ".join(fragments)
    # OFFSET 0 = PostgreSQL optimization fence; do not remove without
    # re-running the EXPLAIN ANALYZE in deployment.mdc's Django-side recipe.
    subquery_sql = (
        f'"{table}"."id" IN '
        f'(SELECT "id" FROM "{table}" WHERE {or_clauses} OFFSET 0)'
    )
    return queryset.extra(where=[subquery_sql], params=params)  # noqa: SLF001


def apply_visa_program_filter(
    queryset, program_filter: str, program_field: str = "visa_program"
):
    """
    Apply visa program filter to queryset.

    Args:
        queryset: Django queryset to filter
        program_filter: Program filter value ('h1b' or 'perm')
        program_field: Name of the visa program field (default: 'visa_program')

    Returns:
        Filtered queryset
    """
    if not program_filter:
        return queryset

    if program_filter == "h1b":
        return queryset.filter(
            **{
                f"{program_field}__in": [
                    VisaProgram.H1B,
                    VisaProgram.H1B1,
                    VisaProgram.E3,
                ]
            }
        )
    elif program_filter == "perm":
        return queryset.filter(**{f"{program_field}": VisaProgram.PERM})

    return queryset


def apply_fiscal_year_filter(
    queryset, year_filter: str | int | None, year_field: str = "fiscal_year"
):
    """
    Apply fiscal year filter to queryset.

    Args:
        queryset: Django queryset to filter
        year_filter: Year filter value (string or int)
        year_field: Name of the fiscal year field (default: 'fiscal_year')

    Returns:
        Filtered queryset
    """
    if not year_filter:
        return queryset

    try:
        year = int(year_filter)
        return queryset.filter(**{year_field: year})
    except (ValueError, TypeError):
        return queryset


def apply_filing_year_filter(
    queryset, year_filter: str | int | None, filing_date_field: str = "case_submitted"
):
    """
    Apply filing year filter to queryset.

    Args:
        queryset: Django queryset to filter
        year_filter: Year filter value (string or int)
        filing_date_field: Name of the filing date field (default: 'case_submitted')

    Returns:
        Filtered queryset
    """
    if not year_filter:
        return queryset

    try:
        year = int(year_filter)
        return queryset.filter(**{f"{filing_date_field}__year": year})
    except (ValueError, TypeError):
        return queryset

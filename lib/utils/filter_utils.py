"""Generic filter application utilities for Django querysets"""

from django.db import connections

from models.enums.visa_program import VisaProgram


def apply_text_search_filter(queryset, query: str, fields: list[str]):
    """
    Apply case-insensitive substring search across multiple fields.

    Emits an ``OR`` of ``UPPER(field::text) LIKE UPPER(%s)`` predicates, which
    match the ``gin (UPPER(...) gin_trgm_ops)`` trigram indexes on
    salary_record.job_title / soc_title (migration 0047) so PostgreSQL can use a
    Bitmap Index Scan.

    Anti-pessimization note: callers that chain
    ``order_by('-wage_annual', '-fiscal_year')[offset:offset+N]`` over this
    filter MUST resolve their page through :func:`fenced_page_ids`, NOT a plain
    sliced queryset. With the ``LIMIT`` visible to the planner the trigram
    filter triggers a classic LIMIT-pessimization (Index Scan Backward on
    ``wage_annual`` + inline trigram recheck, scanning ~1.2M heap rows for rare
    low-wage terms like CASHIER). The aggregate/count path (no ORDER BY/LIMIT)
    is unaffected and just gets a fast Bitmap count.

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
        fragments.append(f'UPPER("{table}"."{column}"::text) LIKE UPPER(%s)')
        params.append(pattern)
    where = "(" + " OR ".join(fragments) + ")"
    return queryset.extra(where=[where], params=params)  # noqa: SLF001


def fenced_page_ids(
    queryset, order_fields: tuple[str, ...], offset: int, limit: int
) -> list:
    """
    Resolve one ordered page of primary keys behind a PostgreSQL ``OFFSET 0``
    optimization fence, avoiding two planner traps on the salary/worksite list
    views (a trigram-filtered queryset sorted by ``-wage_annual, -fiscal_year``
    and sliced to a page):

    * **Rare terms** (CASHIER): with the ``LIMIT`` visible the planner picks
      ``Index Scan Backward on (wage_annual)`` and rechecks the trigram inline,
      scanning ~1.2M heap rows before it finds N matches.
    * **Common terms** (ENGINEERS, ~200k matches): resolving the page with the
      dimension ``select_related`` joins still attached makes the planner
      hash-join the whole match set against every (seq-scanned) dimension table
      before applying the ``LIMIT`` — ~6s to keep 50 rows.

    Fix: wrap the fully-filtered, projection-free queryset in a subquery with a
    trailing ``OFFSET 0``. That is a PostgreSQL optimization fence — the inner
    block is planned on its own and cannot be folded into the outer
    ``ORDER BY``/``LIMIT``, so it produces the full match set via the cheapest
    plan (Bitmap Heap Scan for selective trigrams, Seq Scan otherwise) while the
    outer does only a top-N heapsort + ``LIMIT`` on bare ids. Callers then fetch
    the ≤N full rows by pk with their joins (a nested loop by primary key,
    sub-ms). Measured on prod: ENGINEERS p4 5959→1614ms, ARCHITECT 2444→479ms,
    CASHIER 39→6ms.

    Args:
        queryset: the filtered queryset (any ``select_related``/``only`` and
            ordering on it are ignored — only its WHERE clause is used).
        order_fields: model field names; a ``-`` prefix means DESC
            (e.g. ``("-wage_annual", "-fiscal_year")``).
        offset: page slice start (rows to skip).
        limit: page size.

    Returns:
        list of primary keys in order; empty list when nothing matches.
    """
    model = queryset.model
    pk_col = model._meta.pk.column
    order_cols = {
        f: model._meta.get_field(f.lstrip("-")).column for f in order_fields
    }

    # Project only pk + ordering columns; drop ORM ordering and any joins.
    inner = queryset.order_by().values_list(
        model._meta.pk.name,
        *[model._meta.get_field(f.lstrip("-")).name for f in order_fields],
    )
    compiler = inner.query.get_compiler(using=inner.db)
    inner_sql, inner_params = compiler.as_sql()

    order_sql = ", ".join(
        f'"{order_cols[f]}" {"DESC" if f.startswith("-") else "ASC"}'
        for f in order_fields
    )
    # OFFSET 0 = optimization fence; see docstring. Do not remove without
    # re-running the EXPLAIN ANALYZE in deployment.md's Django-side recipe.
    sql = (
        f'SELECT "{pk_col}" FROM ({inner_sql} OFFSET 0) _fenced '
        f"ORDER BY {order_sql} LIMIT %s OFFSET %s"
    )
    with connections[inner.db].cursor() as cursor:
        cursor.execute(sql, list(inner_params) + [limit, offset])
        return [row[0] for row in cursor.fetchall()]


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

"""Generic filter application utilities for Django querysets"""

from typing import NamedTuple

from django.core.exceptions import EmptyResultSet
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
    try:
        inner_sql, inner_params = compiler.as_sql()
    except EmptyResultSet:
        # Provably-empty WHERE (the employer free-text ``records.none()`` path):
        # Django raises EmptyResultSet from as_sql() rather than emitting SQL.
        # No rows → no page.
        return []

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


class FencedAggregate(NamedTuple):
    """Result of :func:`fenced_aggregate` — count + wage stats over a page's
    full filtered set. ``avg``/``min``/``max`` are None when count is 0.
    """

    count: int
    avg: float | None
    min: float | None
    max: float | None


def fenced_aggregate(queryset, agg_field: str) -> FencedAggregate:
    """``count(*)`` + ``avg``/``min``/``max`` of ``agg_field`` over the filtered
    set, computed behind the same PostgreSQL ``OFFSET 0`` optimization fence as
    :func:`fenced_page_ids`.

    The count/stats aggregate is a separate query from the page-id resolution,
    so it needs its own fence. Without it, a queryset that combines a trigram
    text filter (``job_title``/``soc_title`` via :func:`apply_text_search_filter`)
    with an FK-joined employer filter and a ``worksite_state`` filter
    (e.g. ``q=Financial Analyst`` + Goldman Sachs + NY) compiles to a
    **Nested Loop Semi Join**: the planner estimates the cluster+state branch at
    ~1 row, puts the ~30k-row trigram Bitmap Heap Scan on the inner side, and
    re-scans it per (under-estimated) outer row — the aggregate never completes
    (>120s → the 504s observed on ``/salaries/``).

    Wrapping the projection-free filtered rows in a trailing ``OFFSET 0``
    subquery fences the inner block: the trigram predicate is evaluated as an
    inline ``Filter`` on the already-narrowed cluster+state rows (a cheap nested
    loop over indexed columns), and the aggregate runs over that. Measured on
    prod: Goldman Sachs + "Financial Analyst" + NY aggregate >120s (timeout) →
    22ms fenced.

    Args:
        queryset: the filtered queryset (any ``select_related``/``only`` and
            ordering on it are ignored — only its WHERE clause is used).
        agg_field: model field name to compute avg/min/max over
            (e.g. ``"wage_annual"``). ``count`` is ``count(*)`` of the rows.

    Returns:
        :class:`FencedAggregate`.
    """
    model = queryset.model
    col = model._meta.get_field(agg_field).column

    # Project only the aggregate column; drop ORM ordering and any joins.
    inner = queryset.order_by().values_list(agg_field, flat=True)
    compiler = inner.query.get_compiler(using=inner.db)
    try:
        inner_sql, inner_params = compiler.as_sql()
    except EmptyResultSet:
        # Provably-empty WHERE (e.g. the employer free-text path's
        # ``records.none()`` when a typed name resolves to zero clusters):
        # Django raises EmptyResultSet from as_sql() instead of emitting SQL.
        # An empty set has count 0 and no wage stats.
        return FencedAggregate(count=0, avg=None, min=None, max=None)

    # OFFSET 0 = optimization fence; see docstring + fenced_page_ids.
    sql = (
        f'SELECT count(*), avg("{col}"), min("{col}"), max("{col}") '
        f"FROM ({inner_sql} OFFSET 0) _fenced"
    )
    with connections[inner.db].cursor() as cursor:
        cursor.execute(sql, list(inner_params))
        count, avg, min_, max_ = cursor.fetchone()
    return FencedAggregate(count=count or 0, avg=avg, min=min_, max=max_)


def fenced_page_and_aggregate(
    queryset,
    order_fields: tuple[str, ...],
    offset: int,
    limit: int,
    agg_field: str,
) -> tuple[list, FencedAggregate]:
    """One ordered page of primary keys AND the count/avg/min/max aggregate over
    the same filtered set, in a SINGLE scan of the underlying table.

    :func:`fenced_page_ids` and :func:`fenced_aggregate` each materialize the
    full filtered match set independently, so a cold search request pays the
    expensive part (the trigram Bitmap Heap Scan over salary_record — 55k-391k
    matched rows for common terms like ENGINEERS) TWICE. That double-scan is
    the ``/salaries/?q=`` slow-tail residual from the 2026-06-21 504 swarm.

    Fix: materialize the fenced match set once in a CTE (``AS MATERIALIZED``,
    PG12+) and derive both the top-N page and the aggregate from that
    tuplestore. The heap is scanned once; the two derivations are cheap passes
    over the already-materialized rows.

    The requested ``offset`` is used as-is. If it lies beyond the end of the
    result set the page comes back empty while the aggregate is still correct —
    callers that clamp the page number to the last page (the list views) should
    re-resolve just the page via :func:`fenced_page_ids` in that (rare) case.

    Args:
        queryset: the filtered queryset (``select_related``/``only``/ordering
            are ignored — only its WHERE clause is used).
        order_fields: model field names; a ``-`` prefix means DESC.
        offset: page slice start (rows to skip).
        limit: page size.
        agg_field: model field name to compute avg/min/max over.

    Returns:
        (list of primary keys in order, :class:`FencedAggregate`).
    """
    model = queryset.model
    pk_col = model._meta.pk.column
    agg_col = model._meta.get_field(agg_field).column
    order_cols = {
        f: model._meta.get_field(f.lstrip("-")).column for f in order_fields
    }

    # Project pk + ordering + aggregate columns (deduped); drop ORM ordering
    # and any joins — same shape as fenced_page_ids/fenced_aggregate.
    field_names = [model._meta.pk.name]
    for f in order_fields:
        name = model._meta.get_field(f.lstrip("-")).name
        if name not in field_names:
            field_names.append(name)
    if agg_field not in field_names:
        field_names.append(agg_field)
    inner = queryset.order_by().values_list(*field_names)
    compiler = inner.query.get_compiler(using=inner.db)
    try:
        inner_sql, inner_params = compiler.as_sql()
    except EmptyResultSet:
        # Provably-empty WHERE (the employer free-text ``records.none()`` path).
        return [], FencedAggregate(count=0, avg=None, min=None, max=None)

    order_sql = ", ".join(
        f'"{order_cols[f]}" {"DESC" if f.startswith("-") else "ASC"}'
        for f in order_fields
    )
    # _fenced: the OFFSET-0 fence (see fenced_page_ids) + AS MATERIALIZED so
    # the match set is computed ONCE and both consumers read the tuplestore.
    # _page: top-N over the tuplestore (its inner ORDER BY/LIMIT keeps the
    # top-N heapsort; row_number() OVER () just records arrival order so the
    # final join can be re-ordered). _agg: always exactly one row, so the
    # cross join tags every page row with the aggregate (and yields a single
    # NULL-pk row when the page is empty).
    sql = (
        f"WITH _fenced AS MATERIALIZED ({inner_sql} OFFSET 0), "
        f"_page AS MATERIALIZED ("
        f'SELECT "{pk_col}", row_number() OVER () AS _rn FROM ('
        f'SELECT "{pk_col}" FROM _fenced ORDER BY {order_sql} '
        f"LIMIT %s OFFSET %s) _p), "
        f"_agg AS (SELECT count(*) AS _n, avg(\"{agg_col}\") AS _avg, "
        f'min("{agg_col}") AS _min, max("{agg_col}") AS _max FROM _fenced) '
        f'SELECT _agg._n, _agg._avg, _agg._min, _agg._max, _page."{pk_col}" '
        f"FROM _agg LEFT JOIN _page ON TRUE ORDER BY _page._rn"
    )
    with connections[inner.db].cursor() as cursor:
        cursor.execute(sql, list(inner_params) + [limit, offset])
        rows = cursor.fetchall()
    if not rows:  # cannot happen (_agg always has one row), but stay safe
        return [], FencedAggregate(count=0, avg=None, min=None, max=None)
    count, avg, min_, max_ = rows[0][:4]
    page_ids = [row[4] for row in rows if row[4] is not None]
    return page_ids, FencedAggregate(count=count or 0, avg=avg, min=min_, max=max_)


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

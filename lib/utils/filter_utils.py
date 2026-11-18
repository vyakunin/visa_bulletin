"""Generic filter application utilities for Django querysets"""

import math
from typing import NamedTuple

from django.core.exceptions import EmptyResultSet
from django.db import connections, router, transaction

from models.enums.visa_program import VisaProgram


def is_trigram_search(query: str) -> bool:
    """Whether :func:`apply_text_search_filter` filters on ``query`` at all: trigrams
    need at least 3 characters to use the GIN index."""
    return bool(query) and len(query.strip()) >= 3


def apply_text_search_filter(queryset, query: str, fields: list[str]):
    """
    Apply case-insensitive substring search across multiple fields.

    Emits an ``OR`` of ``UPPER(field::text) LIKE UPPER(%s)`` predicates, which
    match the ``gin (UPPER(...) gin_trgm_ops)`` trigram indexes on
    salary_record.job_title / soc_title (migration 0047) so PostgreSQL can use a
    Bitmap Index Scan.

    Anti-pessimization note: callers that chain
    ``order_by('-wage_annual', '-fiscal_year')[offset:offset+N]`` over this
    filter MUST resolve their page through :func:`walked_page_ids` or
    :func:`fenced_page_ids`, NOT a plain sliced queryset. With the ``LIMIT`` visible to the planner the trigram
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
    if not is_trigram_search(query):
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


def estimated_table_rows(model) -> int:
    """The planner's row count for ``model``'s table (``pg_class.reltuples``); 0 or less
    when the table has never been analyzed."""
    with connections[router.db_for_read(model)].cursor() as cursor:
        cursor.execute(
            "SELECT reltuples::bigint FROM pg_class WHERE oid = %s::regclass",
            [model._meta.db_table],
        )
        row = cursor.fetchone()
    return row[0] if row else 0


class MatchAggregate(NamedTuple):
    """Count + ``agg_field`` stats over a search's full filtered set, from
    :func:`fenced_aggregate` or :func:`parallel_aggregate`. ``avg``/``min``/``max`` are None when count is 0.
    """

    count: int
    avg: float | None
    min: float | None
    max: float | None


def fenced_aggregate(queryset, agg_field: str) -> MatchAggregate:
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
        :class:`MatchAggregate`.
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
        return MatchAggregate(count=0, avg=None, min=None, max=None)

    # OFFSET 0 = optimization fence; see docstring + fenced_page_ids.
    sql = (
        f'SELECT count(*), avg("{col}"), min("{col}"), max("{col}") '
        f"FROM ({inner_sql} OFFSET 0) _fenced"
    )
    with connections[inner.db].cursor() as cursor:
        cursor.execute(sql, list(inner_params))
        count, avg, min_, max_ = cursor.fetchone()
    return MatchAggregate(count=count or 0, avg=avg, min=min_, max=max_)


# Each walked row is a random heap read: 24k rows took 0.43s warm, about what the fence
# costs for a match set of a few hundred thousand rows.
PAGE_WALK_MAX_ROWS = 20_000
# The top of the wage ordering is executives and partners: there a broad term matches
# 1x-4.2x less often than across the table (measured on 10.78M rows, 2026-11-18).
PAGE_WALK_SLACK = 6


def walked_page_ids(
    queryset,
    order_fields: tuple[str, ...],
    offset: int,
    limit: int,
    *,
    match_count: int,
    table_rows: int,
) -> list | None:
    """One ordered page of primary keys, read from a bounded prefix of the table's own
    ordering; None when the prefix cannot prove the page, so the caller uses
    :func:`fenced_page_ids`.

    The prefix is the top ``budget`` rows of the whole table in ``order_fields`` order,
    with the queryset's WHERE applied outside it. A full page found there is exactly the
    global page; a short page, or a budget over :data:`PAGE_WALK_MAX_ROWS`, returns None.
    The budget comes from the match rate ``match_count / table_rows``, so a broad term
    (a third of the table matches "engineer") walks a few hundred rows and a rare one
    is never walked.
    """
    if match_count <= 0:
        return []
    if table_rows <= 0:
        return None
    budget = math.ceil(PAGE_WALK_SLACK * (offset + limit) * table_rows / match_count)
    if budget > PAGE_WALK_MAX_ROWS:
        return None

    model = queryset.model
    table = model._meta.db_table
    inner = queryset.order_by().values_list(model._meta.pk.name)
    compiler = inner.query.get_compiler(using=inner.db)
    try:
        inner_sql, inner_params = compiler.as_sql()
    except EmptyResultSet:
        return []
    from_clause = f'FROM "{table}"'
    if inner_sql.count(from_clause) != 1:
        return None  # a join or subquery: the prefix alias would not stand in for it

    order_sql = ", ".join(
        f'"{model._meta.get_field(f.lstrip("-")).column}" '
        f'{"DESC" if f.startswith("-") else "ASC"}'
        for f in order_fields
    )
    # The prefix is aliased as the table, so the compiled WHERE ("table"."col") reads it.
    # Its LIMIT keeps the outer WHERE from being pushed down into the walk.
    prefix = f'FROM (SELECT * FROM "{table}" ORDER BY {order_sql} LIMIT %s) "{table}"'
    walked_sql = inner_sql.replace(from_clause, prefix)
    sql = f"{walked_sql} ORDER BY {order_sql} LIMIT %s OFFSET %s"
    with connections[inner.db].cursor() as cursor:
        cursor.execute(sql, [budget, *inner_params, limit, offset])
        page = [row[0] for row in cursor.fetchall()]
    return page if len(page) == limit else None


def parallel_aggregate(
    queryset, agg_field: str, *, trigram_search: bool
) -> MatchAggregate:
    """``count(*)`` + ``avg``/``min``/``max`` of ``agg_field`` as one plain statement, so
    PostgreSQL can run a broad trigram match as a parallel bitmap scan.

    Unsafe where :func:`fenced_aggregate`'s fence is needed: an employer filter combined
    with a trigram term. JIT is off: compiling this plan took 1.1s of a 2.3s query.
    A ``trigram_search`` also has the seq scan off: prod's planner picked it for
    q=engineer, which runs upper()+LIKE on every row (4.6s against 2.7s by bitmap).
    """
    model = queryset.model
    col = model._meta.get_field(agg_field).column
    aggregated = queryset.order_by().values_list(agg_field, flat=True)
    compiler = aggregated.query.get_compiler(using=aggregated.db)
    try:
        inner_sql, inner_params = compiler.as_sql()
    except EmptyResultSet:
        return MatchAggregate(count=0, avg=None, min=None, max=None)
    sql = (
        f'SELECT count(*), avg("{col}"), min("{col}"), max("{col}")'
        f'{inner_sql[inner_sql.index(" FROM "):]}'
    )
    with transaction.atomic(using=aggregated.db), connections[aggregated.db].cursor() as cursor:
        cursor.execute("SET LOCAL jit = off")
        if trigram_search:
            cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(sql, list(inner_params))
        count, avg, min_, max_ = cursor.fetchone()
    return MatchAggregate(count=count or 0, avg=avg, min=min_, max=max_)


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

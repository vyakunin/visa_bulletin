#!/usr/bin/env python3
"""
Benchmark the SalaryRecord fenced-query optimizations against each other.

Times the three ways the `/salaries/` (and `/worksites/`) list views can resolve
a filtered page + count/avg/min/max aggregate over `salary_record`, so a
regression in the fenced-query optimization is measurable:

  * two_scan     — fenced_aggregate() + fenced_page_ids() (the pair; each
                   materializes the filtered match set once, so a cold search
                   scans it TWICE).
  * single_scan  — fenced_page_and_aggregate() (one AS MATERIALIZED fenced scan
                   yields both the ordered page and the aggregate; the current
                   cold /salaries/?q= path).
  * naive        — plain ORM .aggregate() + sliced .order_by()[...] (the
                   pre-fence path that LIMIT-pessimized / timed out; --include-naive,
                   guarded by the DB statement_timeout).

For each representative filter shape (common job-title token, rare token, employer
filter, state filter, the combined trigram+employer+state case, and a deep-page
case) it prints the wall-clock ms (min + median over N iterations) for each path,
mirroring the exact queryset `webapp/views/salary/search.py:salary_search_view`
builds (same apply_* filters, the same worksite/Unknown/null-wage excludes, and
the same ("-wage_annual", "-fiscal_year") ordering over "wage_annual").

The heavy lifting (the OFFSET-0 fence, the AS MATERIALIZED CTE) is PostgreSQL-
specific, so authoritative timing wants prod/staging Postgres with a populated
salary_record. Against an empty or small dev DB the numbers are structural-only
(they confirm the harness + each SQL path execute), not representative.

Usage:
    # local dev DB (structural-only timings)
    bazel run //scripts:benchmark_fenced_queries

    # more iterations, include the naive baseline
    bazel run //scripts:benchmark_fenced_queries -- --iterations 5 --include-naive

    # a single shape, more warmup
    bazel run //scripts:benchmark_fenced_queries -- --shape rare_title --warmup 2

    # on prod/staging (in the web container, after `bazel shutdown`):
    #   docker exec -w /app vb_web python3 -m scripts.benchmark_fenced_queries -- --iterations 5
"""

from __future__ import annotations

import argparse
import logging
import os
import statistics
import time
from collections.abc import Callable
from typing import NamedTuple

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db import connection  # noqa: E402
from django.db.models import Avg, Count, Max, Min  # noqa: E402

from django_config.logging_config import setup_logging  # noqa: E402
from lib.utils.filter_utils import (  # noqa: E402
    apply_filing_year_filter,
    apply_fiscal_year_filter,
    apply_text_search_filter,
    apply_visa_program_filter,
    fenced_aggregate,
    fenced_page_and_aggregate,
    fenced_page_ids,
)
from lib.utils.logging_utils import ScriptLogger  # noqa: E402
from models.salary import EmployerCluster, SalaryRecord  # noqa: E402

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)

# The ordering + aggregate column the salary/worksite list views use.
ORDER_FIELDS = ("-wage_annual", "-fiscal_year")
AGG_FIELD = "wage_annual"
PER_PAGE = 50
# Mirrors webapp/views/salary/search.py:_MAX_CLUSTER_IDS.
_MAX_CLUSTER_IDS = 2000


class Shape(NamedTuple):
    """One representative filter shape to benchmark.

    ``params`` maps the salary_search_view filter names (query/employer/state/
    program/fiscal_year/filing_year); ``page`` drives the offset (page 1 =
    offset 0, deep pages exercise the LIMIT-pessimization surface).
    """

    name: str
    description: str
    params: dict
    page: int


# Shapes mirror the real /salaries/ query surface (see filter_utils docstrings):
# rare terms (CASHIER) trigger LIMIT-pessimization; common terms (ENGINEER)
# hash-join the whole match set; the trigram+employer+state combo compiles to a
# Nested Loop Semi Join that the fence exists to defuse; deep pages stress OFFSET.
SHAPES: list[Shape] = [
    Shape("common_title", "common job-title token (q=ENGINEER)",
          {"query": "ENGINEER"}, page=1),
    Shape("rare_title", "rare job-title token (q=CASHIER)",
          {"query": "CASHIER"}, page=1),
    Shape("employer", "employer free-text filter (employer=GOOGLE)",
          {"employer": "GOOGLE"}, page=1),
    Shape("state", "state filter (state=CA)",
          {"state": "CA"}, page=1),
    Shape("combined", "trigram + employer + state (q=Financial Analyst, GOLDMAN, NY)",
          {"query": "Financial Analyst", "employer": "GOLDMAN", "state": "NY"}, page=1),
    Shape("deep_page", "common token, deep pagination (q=ENGINEER, page=100)",
          {"query": "ENGINEER"}, page=100),
]


def build_records(params: dict):
    """Build the filtered SalaryRecord queryset for one shape.

    Replicates the filter chain in salary_search_view (apply_* filters + the
    worksite / Unknown-employer / null-wage excludes) so the benchmark exercises
    the exact WHERE clause the fenced resolvers see in production.
    """
    query = params.get("query", "") or ""
    employer = params.get("employer", "") or ""
    records = SalaryRecord.objects.all()
    records = apply_text_search_filter(records, query, ["job_title", "soc_title"])
    if employer:
        cluster_ids = list(
            EmployerCluster.objects.filter(canonical_name__icontains=employer)
            .values_list("id", flat=True)[:_MAX_CLUSTER_IDS]
        )
        records = records.filter(employer__canonical_cluster_id__in=cluster_ids) \
            if cluster_ids else records.none()
    if params.get("state"):
        records = records.filter(worksite_state=params["state"])
    records = apply_visa_program_filter(records, params.get("program", ""))
    records = apply_fiscal_year_filter(records, params.get("fiscal_year"))
    records = apply_filing_year_filter(records, params.get("filing_year"))
    records = records.exclude(is_worksite=True).exclude(employer_name="Unknown")
    return records.filter(wage_annual__isnull=False, wage_annual__gt=0)


class PathResult(NamedTuple):
    """Timing + row-count outcome for one resolver path over one shape."""

    label: str
    ms: list[float]  # per-iteration wall-clock ms; empty when errored
    count: int | None  # matched-row count the path reported (sanity cross-check)
    error: str | None


def _time(label: str, thunk: Callable[[], tuple[int, int]], *,
          warmup: int, iterations: int) -> PathResult:
    """Run ``thunk`` warmup+iterations times, capturing per-run ms and any error.

    ``thunk`` returns (matched_count, page_len); the count is kept for the
    cross-path sanity check. On any DB error (e.g. a naive path hitting the
    statement_timeout on prod) the path is recorded as errored, not fatal.
    """
    try:
        for _ in range(warmup):
            thunk()
        samples: list[float] = []
        count = None
        for _ in range(iterations):
            start = time.perf_counter()
            count, _page_len = thunk()
            samples.append((time.perf_counter() - start) * 1000.0)
        return PathResult(label, samples, count, None)
    except Exception as exc:  # noqa: BLE001 — report, don't abort the whole run
        return PathResult(label, [], None, f"{type(exc).__name__}: {exc}")


def _two_scan(records, offset: int) -> tuple[int, int]:
    agg = fenced_aggregate(records, AGG_FIELD)
    ids = fenced_page_ids(records, ORDER_FIELDS, offset, PER_PAGE)
    return agg.count, len(ids)


def _single_scan(records, offset: int) -> tuple[int, int]:
    ids, agg = fenced_page_and_aggregate(
        records, ORDER_FIELDS, offset, PER_PAGE, AGG_FIELD
    )
    return agg.count, len(ids)


def _naive(records, offset: int) -> tuple[int, int]:
    agg = records.aggregate(
        count=Count("id"), avg=Avg(AGG_FIELD), min=Min(AGG_FIELD), max=Max(AGG_FIELD)
    )
    ids = list(
        records.order_by(*ORDER_FIELDS).values_list("id", flat=True)[
            offset:offset + PER_PAGE
        ]
    )
    return agg["count"] or 0, len(ids)


def _fmt(result: PathResult) -> str:
    """One-line summary of a path's timing (or its error)."""
    if result.error is not None:
        return f"  {result.label:<48} ERROR {result.error}"
    lo = min(result.ms)
    med = statistics.median(result.ms)
    return f"  {result.label:<48} min {lo:8.2f}ms / median {med:8.2f}ms"


def run_shape(shape: Shape, *, warmup: int, iterations: int,
              include_naive: bool) -> None:
    """Benchmark all resolver paths for one shape and print the block."""
    records = build_records(shape.params)
    offset = (shape.page - 1) * PER_PAGE
    logger.info("Shape: %s — %s [page=%d, offset=%d]",
                shape.name, shape.description, shape.page, offset)

    results = [
        _time("two_scan (fenced_aggregate + fenced_page_ids)",
              lambda: _two_scan(records, offset),
              warmup=warmup, iterations=iterations),
        _time("single_scan (fenced_page_and_aggregate)",
              lambda: _single_scan(records, offset),
              warmup=warmup, iterations=iterations),
    ]
    if include_naive:
        results.append(
            _time("naive (.aggregate + sliced .order_by)",
                  lambda: _naive(records, offset),
                  warmup=warmup, iterations=iterations)
        )

    counts = {r.count for r in results if r.count is not None}
    logger.info("  matched rows: %s",
                next(iter(counts)) if len(counts) == 1
                else f"MISMATCH across paths: {sorted(counts)}")
    for result in results:
        logger.info(_fmt(result))
    logger.info("")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark SalaryRecord fenced-query resolvers "
                    "(two_scan vs single_scan vs naive).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--shape", choices=[s.name for s in SHAPES],
                        help="Run a single shape (default: all).")
    parser.add_argument("--iterations", type=int, default=3,
                        help="Timed iterations per path (default: 3).")
    parser.add_argument("--warmup", type=int, default=1,
                        help="Warmup runs per path before timing (default: 1).")
    parser.add_argument("--include-naive", action="store_true",
                        help="Also time the naive .aggregate + sliced page path "
                             "(can hit statement_timeout on a large prod DB).")
    args = parser.parse_args()

    script_logger.log_call(
        args={"shape": args.shape, "iterations": args.iterations,
              "warmup": args.warmup, "include_naive": args.include_naive},
        context="Benchmark SalaryRecord fenced-query resolvers",
    )

    vendor = connection.vendor
    db_name = connection.settings_dict.get("NAME")
    logger.info("DB backend: %s (NAME=%s)", vendor, db_name)
    if vendor != "postgresql":
        logger.warning("Fenced SQL (OFFSET-0 fence / AS MATERIALIZED) is "
                       "PostgreSQL-specific; non-postgres timings may error.")
    total = SalaryRecord.objects.count()
    logger.info("salary_record rows: %s%s", f"{total:,}",
                " — EMPTY/small DB: timings are structural-only, not "
                "representative (run on prod/staging for real numbers)."
                if total < 10_000 else "")
    logger.info("iterations=%d warmup=%d include_naive=%s\n",
                args.iterations, args.warmup, args.include_naive)

    shapes = [s for s in SHAPES if s.name == args.shape] if args.shape else SHAPES
    for shape in shapes:
        run_shape(shape, warmup=args.warmup, iterations=args.iterations,
                  include_naive=args.include_naive)


if __name__ == "__main__":
    main()

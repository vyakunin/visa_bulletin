#!/usr/bin/env python3
"""Precompute the default render of the largest per-entity pages and of every state page.

Requests for /job-title/<slug>/, /h1b-sponsors/<slug>/, /employer/<slug>/,
/h1b-salary/<employer>/<role>/, /h1b-sponsors/in/<state>/ and /salaries/by-state/<state>/
read the stored statistics (lib.business.salary.precomputed_profiles) and aggregate
salary_record live only when there are none. This script writes them.

Usage
  docker exec -w /app vb_stg_web python3 -m scripts.cache.warm_profiles --rebuild   # after a data change, on staging
  docker exec -w /app vb_web python3 -m scripts.cache.warm_profiles --missing-only  # daily on prod: fills a new year
  bazel run //scripts/cache:warm_profiles -- --kinds job_title --limit 20

--rebuild deletes every stored profile first: re-clustering reuses cluster ids, so a
stored page can belong to a different cluster after a data graduation. Run it where
the data changed (staging); the cutover's resync carries the table to prod.

Exit 0 when every selected entity was stored, 1 when any failed.
"""

import argparse
import logging
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from django.db.models import Count  # noqa: E402

from django_config.logging_config import setup_logging  # noqa: E402
from lib.business.salary.employer_stats import (  # noqa: E402
    EMPLOYER_PROFILE_DEFAULT_YEARS,
    employer_profile_records_all_clusters,
    employer_profile_window_start,
)
from lib.business.salary.h1b_salary_pair import (  # noqa: E402
    _pair_page_key,
    pairs_with_filings,
    warm_pair_page,
)
from lib.business.salary.h1b_sponsors import (  # noqa: E402
    _sponsor_page_key,
    _state_sponsor_page_key,
    warm_role_sponsor_page,
    warm_state_sponsor_page,
)
from lib.business.salary.job_title_stats import (  # noqa: E402
    _precomputed_profile_key,
    warm_job_title_profile,
)
from lib.business.salary.precomputed_profiles import (  # noqa: E402
    clear_precomputed_profiles,
    stored_profile_keys,
)
from lib.utils.location_utils import US_STATES  # noqa: E402
from models.job_title import JobTitleCluster  # noqa: E402
from models.salary import EmployerCluster  # noqa: E402
from webapp.views.employers.profile import (  # noqa: E402
    _precomputed_payload_key,
    warm_employer_profile,
)
from webapp.views.salary.by_state import (  # noqa: E402
    _state_salary_page_key,
    warm_state_salary_page,
)

logger = logging.getLogger(__name__)

KINDS = ("job_title", "sponsors", "employer", "pair", "state")

# Below these sizes the live render is fast enough on the prod box (measured
# 2026-10-14 after the id-list filter: see the D11 ticket for the series).
# "state" ignores its floor: every state's two pages are precomputed.
DEFAULT_MIN_FILINGS = {"job_title": 3000, "sponsors": 3000, "employer": 3000, "pair": 2000, "state": 0}


def _job_title_clusters(min_filings: int):
    return JobTitleCluster.objects.filter(
        total_filings__gte=min_filings, slug__isnull=False
    ).order_by("-total_filings")


def _employer_clusters(min_filings: int):
    """Employer clusters by the rows their default render aggregates, largest first.

    Counted here rather than read off EmployerCluster.total_lca_count: the stored counters
    trail re-imports (google-llc: 27,582 stored against 130,740 rows, 2026-10-14).
    """
    sizes = (
        employer_profile_records_all_clusters(
            employer_profile_window_start(EMPLOYER_PROFILE_DEFAULT_YEARS)
        )
        .values("employer__canonical_cluster_id")
        .annotate(n=Count("id"))
        .filter(n__gte=min_filings)
    )
    by_id = {r["employer__canonical_cluster_id"]: r["n"] for r in sizes}
    clusters = EmployerCluster.objects.filter(id__in=by_id, slug__isnull=False).exclude(
        slug="unknown"
    )
    return sorted(clusters, key=lambda c: -by_id[c.id])


def plan(kind: str, min_filings: int):
    """(entity, stored key, warm function) for every entity of `kind` to precompute."""
    if kind == "job_title":
        return [(c, _precomputed_profile_key(c.id), warm_job_title_profile)
                for c in _job_title_clusters(min_filings)]
    if kind == "sponsors":
        return [(c, _sponsor_page_key(c.id), lambda c: warm_role_sponsor_page(c.id))
                for c in _job_title_clusters(min_filings)]
    if kind == "state":
        return [
            (_State(code), key(code), warm)
            for code, _name in US_STATES
            for key, warm in (
                (_state_sponsor_page_key, lambda s: warm_state_sponsor_page(s.code)),
                (_state_salary_page_key, lambda s: warm_state_salary_page(s.code)),
            )
        ]
    if kind == "pair":
        return [(_Pair(e, j), _pair_page_key(e, j), lambda p: warm_pair_page(p.emp, p.jt))
                for e, j in pairs_with_filings(min_filings)]
    start = employer_profile_window_start(EMPLOYER_PROFILE_DEFAULT_YEARS)
    return [(c, _precomputed_payload_key(c.id, start), warm_employer_profile)
            for c in _employer_clusters(min_filings)]


class _State:
    def __init__(self, code: str):
        self.code = self.slug = code


class _Pair:
    """An (employer cluster, job-title cluster) pair; `slug` names it in the log."""

    def __init__(self, emp: int, jt: int):
        self.emp, self.jt, self.slug = emp, jt, f"{emp}/{jt}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kinds", default=",".join(KINDS), help=f"comma list of {KINDS}")
    p.add_argument("--rebuild", action="store_true", help="delete every stored profile first")
    p.add_argument("--missing-only", action="store_true", help="skip entities already stored")
    p.add_argument("--limit", type=int, default=0, help="at most N entities per kind (0 = all)")
    for kind in KINDS:
        p.add_argument(f"--{kind.replace('_', '-')}-min", type=int, default=DEFAULT_MIN_FILINGS[kind],
                       help=f"min filings for a {kind} entity (default {DEFAULT_MIN_FILINGS[kind]})")
    args = p.parse_args(argv)
    setup_logging(debug=False)

    if args.rebuild:
        logger.info("cleared %d stored profiles", clear_precomputed_profiles())
    stored = stored_profile_keys() if args.missing_only else set()

    failed = 0
    for kind in [k.strip() for k in args.kinds.split(",") if k.strip()]:
        if kind not in KINDS:
            p.error(f"unknown kind {kind!r}")
        todo = plan(kind, getattr(args, f"{kind}_min"))
        if args.missing_only:
            todo = [t for t in todo if t[1] not in stored]
        if args.limit:
            todo = todo[: args.limit]
        logger.info("%s: %d to warm", kind, len(todo))
        start, slowest = time.monotonic(), (0.0, "")
        for i, (entity, _key, warm) in enumerate(todo, 1):
            t0 = time.monotonic()
            try:
                warm(entity)
            except Exception:
                failed += 1
                logger.exception("%s %s failed", kind, entity.slug)
                continue
            took = time.monotonic() - t0
            slowest = max(slowest, (took, entity.slug))
            if i % 50 == 0 or took > 30:
                logger.info("%s %d/%d %s %.1fs", kind, i, len(todo), entity.slug, took)
        logger.info("%s: %d warmed in %.0fs, slowest %s %.1fs",
                    kind, len(todo), time.monotonic() - start, slowest[1], slowest[0])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

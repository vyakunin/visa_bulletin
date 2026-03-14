# scripts/cron/refresh/smoke.py
"""Smoke tests: DB record counts, fiscal year, clustering, slugs, and HTTP endpoints. Uses runner for PSQL and run_shell."""

from __future__ import annotations

import json
import logging
import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import RefreshConfig
    from .runner import Runner

logger = logging.getLogger(__name__)

MIN_RECORDS = 100_000
MIN_RECENT_FY_RECORDS = 1_000
MIN_LINK_PERCENT = 30
MIN_SLUG_PERCENT = 99
MIN_CLUSTERED_EMPLOYERS = 100_000
MIN_JT_CLUSTERS_WITH_STATS = 1_000
MIN_EMPLOYER_CLUSTERS_WITH_STATS = 1_000

MIN_AUTOCOMPLETE_RESULTS = 1
MIN_DIRECTORY_ENTRIES = 10


def _curl_localhost(
    runner: Runner,
    path: str,
    timeout_sec: int = 10,
    host_header: str | None = None,
) -> tuple[int, str]:
    """Curl localhost:8000 via runner.run_shell. Returns (http_status_code, body).

    When host_header is set (e.g. runner.host for RemoteRunner), send that as Host
    so Django ALLOWED_HOSTS accepts the request when checking the inactive host.
    """
    host_opt = f" -H {shlex.quote('Host: ' + host_header)}" if host_header else ""
    result = runner.run_shell(
        f"curl -s -w '\\n%{{http_code}}' --max-time {timeout_sec}{host_opt} "
        f"'http://localhost:8000{path}'",
        timeout_sec=timeout_sec + 5,
    )
    output = (result.stdout or "").strip()
    lines = output.rsplit("\n", 1)
    if len(lines) == 2:
        body, code_str = lines
        try:
            return int(code_str), body
        except ValueError:
            pass
    return 0, output


def run_smoke_tests(runner: Runner, db_name: str, config: RefreshConfig) -> None:
    """Run smoke tests via runner.run_psql and HTTP checks. Raises on failure."""
    _run_db_smoke_tests(runner, db_name)
    _run_http_smoke_tests(runner)
    logger.info("All smoke tests passed")


def _run_db_smoke_tests(runner: Runner, db_name: str) -> None:
    """Database-level smoke tests: record counts, clustering, stats."""
    record_count_s = runner.run_psql(db_name, "SELECT COUNT(*) FROM salary_record;")
    record_count = int(record_count_s.strip()) if record_count_s.strip() else 0
    logger.info("Total salary records: %s", record_count)
    if record_count < MIN_RECORDS:
        raise RuntimeError(
            f"Record count too low: {record_count} (expected >{MIN_RECORDS})"
        )

    max_fy_s = runner.run_psql(db_name, "SELECT MAX(fiscal_year) FROM salary_record;")
    max_fy_s = max_fy_s.strip()
    if not max_fy_s:
        raise RuntimeError("No fiscal year data found in database")
    max_fy = int(max_fy_s)
    logger.info("Most recent fiscal year in DB: %s", max_fy)
    recent_s = runner.run_psql(
        db_name,
        f"SELECT COUNT(*) FROM salary_record WHERE fiscal_year = {max_fy};",
    )
    recent_count = int(recent_s.strip()) if recent_s.strip() else 0
    logger.info("Records for FY %s: %s", max_fy, recent_count)
    if recent_count < MIN_RECENT_FY_RECORDS:
        logger.warning(
            "Very few records for most recent fiscal year %s: %s",
            max_fy,
            recent_count,
        )

    clustered_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_record WHERE job_title_entity_id IS NOT NULL;",
    )
    linked = int(clustered_s.strip()) if clustered_s.strip() else 0
    link_pct = (linked * 100 // record_count) if record_count else 0
    logger.info("Linked records: %s (%s%%)", linked, link_pct)
    if link_pct < MIN_LINK_PERCENT:
        logger.warning(
            "Low job title link percentage: %s%% (expected >%s%%)",
            link_pct,
            MIN_LINK_PERCENT,
        )

    emp_clustered_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_employer WHERE canonical_cluster_id IS NOT NULL;",
    )
    emp_clustered = int(emp_clustered_s.strip()) if emp_clustered_s.strip() else 0
    logger.info("Clustered employers: %s", emp_clustered)
    if emp_clustered < MIN_CLUSTERED_EMPLOYERS:
        logger.warning(
            "Low clustered employer count: %s (expected >%s)",
            emp_clustered,
            MIN_CLUSTERED_EMPLOYERS,
        )

    total_clusters_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_employer_cluster;",
    )
    with_slugs_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_employer_cluster WHERE slug IS NOT NULL;",
    )
    total_clusters = int(total_clusters_s.strip()) if total_clusters_s.strip() else 0
    with_slugs = int(with_slugs_s.strip()) if with_slugs_s.strip() else 0
    if total_clusters > 0:
        slug_pct = with_slugs * 100 // total_clusters
        logger.info(
            "Employer clusters: %s total, %s with slugs (%s%%)",
            total_clusters,
            with_slugs,
            slug_pct,
        )
        if slug_pct < MIN_SLUG_PERCENT:
            raise RuntimeError(
                f"Too many employer clusters without slugs: {total_clusters - with_slugs} missing"
            )

    jt_total_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_job_title_cluster;",
    )
    jt_with_slugs_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_job_title_cluster WHERE slug IS NOT NULL;",
    )
    jt_total = int(jt_total_s.strip()) if jt_total_s.strip() else 0
    jt_with_slugs = int(jt_with_slugs_s.strip()) if jt_with_slugs_s.strip() else 0
    if jt_total > 0:
        jt_slug_pct = jt_with_slugs * 100 // jt_total
        logger.info(
            "Job title clusters: %s total, %s with slugs (%s%%)",
            jt_total,
            jt_with_slugs,
            jt_slug_pct,
        )
        if jt_slug_pct < MIN_SLUG_PERCENT:
            raise RuntimeError(
                f"Too many job title clusters without slugs: {jt_total - jt_with_slugs} missing "
                f"({jt_slug_pct}%%, expected >{MIN_SLUG_PERCENT}%%). Did populate_job_title_slugs run?"
            )

    jt_stats_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_job_title_cluster WHERE total_filings > 0;",
    )
    jt_with_stats = int(jt_stats_s.strip()) if jt_stats_s.strip() else 0
    logger.info("Job title clusters with total_filings > 0: %s", jt_with_stats)
    if jt_with_stats < MIN_JT_CLUSTERS_WITH_STATS:
        raise RuntimeError(
            f"Job title cluster stats missing: only {jt_with_stats} clusters have total_filings > 0 "
            f"(expected >{MIN_JT_CLUSTERS_WITH_STATS}). Did update_job_title_cluster_stats run?"
        )

    emp_stats_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_employer_cluster WHERE total_lca_count > 0 OR total_perm_count > 0;",
    )
    emp_with_stats = int(emp_stats_s.strip()) if emp_stats_s.strip() else 0
    logger.info("Employer clusters with filing counts > 0: %s", emp_with_stats)
    if emp_with_stats < MIN_EMPLOYER_CLUSTERS_WITH_STATS:
        raise RuntimeError(
            f"Employer cluster stats missing: only {emp_with_stats} clusters have filing counts > 0 "
            f"(expected >{MIN_EMPLOYER_CLUSTERS_WITH_STATS}). Did update_employer_stats run?"
        )


def _validate_autocomplete_fields(
    results: list[dict],
    label: str,
    required_fields: list[str],
) -> None:
    """Validate that autocomplete results contain required non-null fields."""
    for item in results:
        for field in required_fields:
            if field not in item or item[field] is None:
                raise RuntimeError(
                    f"{label} autocomplete result missing or null '{field}': {item!r}"
                )


def _run_http_smoke_tests(runner: Runner) -> None:
    """HTTP-level smoke tests: homepage, autocomplete APIs, directory and data pages.

    Run after start_services to verify the full stack (nginx -> gunicorn -> Django -> DB).
    Tests the exact issues discovered during manual staging validation:
    - Homepage loads (ALLOWED_HOSTS, nginx default server)
    - Job title autocomplete returns results with valid fields
    - Employer autocomplete returns results with valid fields
    - Job title and employer directory have entries (not empty)
    - Salaries page renders without errors
    - Dashboard page renders without errors
    """
    host_header = getattr(runner, "host", None)
    status, _ = _curl_localhost(runner, "/", host_header=host_header)
    if status != 200:
        raise RuntimeError(
            f"Homepage returned HTTP {status} (expected 200). "
            "Check ALLOWED_HOSTS, nginx config, and gunicorn status."
        )
    logger.info("[HTTP] Homepage: OK (200)")

    status, body = _curl_localhost(
        runner, "/api/job-title-autocomplete/?q=software&limit=5", host_header=host_header
    )
    if status != 200:
        raise RuntimeError(
            f"Job title autocomplete returned HTTP {status}. "
            "Check that /api/job-title-autocomplete/ endpoint exists and Django is running."
        )
    try:
        results = json.loads(body)
        if not isinstance(results, list) or len(results) < MIN_AUTOCOMPLETE_RESULTS:
            raise RuntimeError(
                f"Job title autocomplete returned {len(results) if isinstance(results, list) else 0} results "
                f"for 'software' (expected >= {MIN_AUTOCOMPLETE_RESULTS}). "
                "Did update_job_title_cluster_stats populate total_filings?"
            )
        _validate_autocomplete_fields(
            results, "Job title", required_fields=["title", "slug", "total_filings"]
        )
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Job title autocomplete returned invalid JSON. Body: {body[:500]}"
        )
    logger.info(
        "[HTTP] Job title autocomplete: OK (%d results, fields validated)", len(results)
    )

    status, body = _curl_localhost(
        runner, "/api/company-autocomplete/?q=google&limit=5", host_header=host_header
    )
    if status != 200:
        raise RuntimeError(
            f"Employer autocomplete returned HTTP {status}. "
            "Check that /api/company-autocomplete/ endpoint exists."
        )
    try:
        results = json.loads(body)
        if not isinstance(results, list) or len(results) < MIN_AUTOCOMPLETE_RESULTS:
            raise RuntimeError(
                f"Employer autocomplete returned {len(results) if isinstance(results, list) else 0} results "
                f"for 'google' (expected >= {MIN_AUTOCOMPLETE_RESULTS}). "
                "Did update_employer_stats populate filing counts?"
            )
        _validate_autocomplete_fields(
            results, "Employer", required_fields=["name", "slug", "count"]
        )
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Employer autocomplete returned invalid JSON. Body: {body[:500]}"
        )
    logger.info(
        "[HTTP] Employer autocomplete: OK (%d results, fields validated)", len(results)
    )

    status, body = _curl_localhost(runner, "/job-titles/", host_header=host_header)
    if status != 200:
        raise RuntimeError(f"Job title directory returned HTTP {status}.")
    if body.count("/job-title/") < MIN_DIRECTORY_ENTRIES:
        raise RuntimeError(
            f"Job title directory has fewer than {MIN_DIRECTORY_ENTRIES} entries. "
            "Page may be empty (total_filings = 0 or slugs missing)."
        )
    logger.info("[HTTP] Job title directory: OK (has entries)")

    status, body = _curl_localhost(runner, "/employers/", host_header=host_header)
    if status != 200:
        raise RuntimeError(f"Employer directory returned HTTP {status}.")
    if body.count("/employer/") < MIN_DIRECTORY_ENTRIES:
        raise RuntimeError(
            f"Employer directory has fewer than {MIN_DIRECTORY_ENTRIES} entries. "
            "Page may be empty (filing counts = 0 or slugs missing)."
        )
    logger.info("[HTTP] Employer directory: OK (has entries)")

    status, _ = _curl_localhost(
        runner, "/salaries/", timeout_sec=30, host_header=host_header
    )
    if status != 200:
        raise RuntimeError(
            f"Salaries page returned HTTP {status} (expected 200). "
            "Check template syntax and salary_search_view for errors."
        )
    logger.info("[HTTP] Salaries page: OK (200)")

    status, _ = _curl_localhost(
        runner, "/", timeout_sec=30, host_header=host_header
    )
    if status != 200:
        raise RuntimeError(
            f"Dashboard returned HTTP {status} (expected 200). "
            "Check dashboard_view and template for errors."
        )
    logger.info("[HTTP] Dashboard: OK (200)")

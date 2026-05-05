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
# case_submitted coverage: LCA records from FY2018+ are ~100%; pre-2018 and
# some PERM records lack the column, bringing the healthy baseline to ~70-75%.
# 65% catches catastrophic failures (near-0% after a fresh staging import or
# if populate_case_submitted completely fails) while passing healthy prod data.
MIN_CASE_SUBMITTED_PERCENT = 65

MIN_AUTOCOMPLETE_RESULTS = 1
MIN_DIRECTORY_ENTRIES = 10
MIN_PUBLISHED_BLOG_POSTS = 1
# Slug hardcoded in dashboard, about, faq, and prediction-detail templates — must exist.
REQUIRED_BLOG_SLUG = "how-my-prediction-model-works"
MIN_PREDICTED_BULLETINS = 1


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
    # `-w '\n%{http_code}'` always appends "\n<code>" after the body, so the
    # code is everything after the last newline. An empty body (302 redirect
    # with no payload) produces "\n302" — do NOT .strip() before splitting,
    # otherwise rsplit returns a single element and parsing falls through to 0.
    output = result.stdout or ""
    nl = output.rfind("\n")
    code_str = output[nl + 1:].strip() if nl >= 0 else output.strip()
    body = output[:nl] if nl >= 0 else ""
    try:
        return int(code_str), body
    except ValueError:
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

    case_submitted_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM salary_record WHERE case_submitted IS NOT NULL;",
    )
    case_submitted_count = int(case_submitted_s.strip()) if case_submitted_s.strip() else 0
    cs_pct = (case_submitted_count * 100 // record_count) if record_count else 0
    logger.info("Records with case_submitted: %s (%s%%)", case_submitted_count, cs_pct)
    if cs_pct < MIN_CASE_SUBMITTED_PERCENT:
        raise RuntimeError(
            f"case_submitted coverage too low: {cs_pct}% ({case_submitted_count:,}/{record_count:,} records). "
            f"Expected >{MIN_CASE_SUBMITTED_PERCENT}% (healthy prod baseline is ~70-75%). "
            "populate_case_submitted may have failed or DOL files are missing from data/salary/dol_data/. "
            "Check stage log for 'No records need updating' (source_file mismatch) or 'File not found'. "
            "Do not graduate until this is resolved — filing year dropdown will be broken on prod."
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

    # Blog posts — templates hardcode certain slugs; missing posts → 404 on dashboard popovers
    blog_count_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM models_blogpost WHERE is_published = true;",
    )
    blog_count = int(blog_count_s.strip()) if blog_count_s.strip() else 0
    logger.info("Published blog posts: %s", blog_count)
    if blog_count < MIN_PUBLISHED_BLOG_POSTS:
        raise RuntimeError(
            f"No published blog posts found (expected >= {MIN_PUBLISHED_BLOG_POSTS}). "
            "Blog listing page will be empty and dashboard 'Latest Analysis' card will not render."
        )
    required_slug_s = runner.run_psql(
        db_name,
        f"SELECT COUNT(*) FROM models_blogpost WHERE slug = '{REQUIRED_BLOG_SLUG}' AND is_published = true;",
    )
    required_slug_count = int(required_slug_s.strip()) if required_slug_s.strip() else 0
    if required_slug_count == 0:
        raise RuntimeError(
            f"Required blog post '{REQUIRED_BLOG_SLUG}' is missing or not published. "
            "This slug is hardcoded in dashboard, about, faq, and prediction-detail templates. "
            "All /analysis/how-my-prediction-model-works/ links will 404 after graduation."
        )
    logger.info("[DB] Blog post '%s': OK (published)", REQUIRED_BLOG_SLUG)

    # VQS predictions — dashboard 6m/12m columns and spaghetti chart depend on this data
    pb_count_s = runner.run_psql(
        db_name,
        "SELECT COUNT(*) FROM models_predictedbulletin;",
    )
    pb_count = int(pb_count_s.strip()) if pb_count_s.strip() else 0
    logger.info("PredictedBulletin rows: %s", pb_count)
    if pb_count < MIN_PREDICTED_BULLETINS:
        raise RuntimeError(
            f"No VQS prediction data found ({pb_count} PredictedBulletin rows). "
            "Dashboard 6m/12m prediction columns and prediction detail pages will be empty."
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
    """HTTP-level smoke tests: homepage, autocomplete APIs, directory, data, and blog pages.

    Run after start_services to verify the full stack (nginx -> gunicorn -> Django -> DB).
    Tests the exact issues discovered during manual staging validation:
    - Homepage loads (ALLOWED_HOSTS, nginx default server)
    - Job title autocomplete returns results with valid fields
    - Employer autocomplete returns results with valid fields
    - Job title and employer directory have entries (not empty)
    - Salaries page renders without errors
    - Dashboard page renders without errors
    - Blog listing (/analysis/) has post links
    - Required blog post slug loads (hardcoded in dashboard/about/faq/prediction-detail)
    - Prediction category landing returns 200 (not 404)
    - Prediction detail chart renders with Plotly data
    """
    # Use "localhost" as the Host header (not runner.host, which may be a private IP not in
    # ALLOWED_HOSTS). Since curl runs ON the remote machine via SSH, "localhost" is always
    # valid and is always included in the staging/prod override's ALLOWED_HOSTS.
    status, _ = _curl_localhost(runner, "/", host_header="localhost")
    if status != 200:
        raise RuntimeError(
            f"Homepage returned HTTP {status} (expected 200). "
            "Check ALLOWED_HOSTS, nginx config, and gunicorn status."
        )
    logger.info("[HTTP] Homepage: OK (200)")

    status, body = _curl_localhost(
        runner, "/api/job-title-autocomplete/?q=software&limit=5", host_header="localhost"
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
        runner, "/api/company-autocomplete/?q=google&limit=5", host_header="localhost"
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

    status, body = _curl_localhost(runner, "/job-titles/", host_header="localhost")
    if status != 200:
        raise RuntimeError(f"Job title directory returned HTTP {status}.")
    if body.count("/job-title/") < MIN_DIRECTORY_ENTRIES:
        raise RuntimeError(
            f"Job title directory has fewer than {MIN_DIRECTORY_ENTRIES} entries. "
            "Page may be empty (total_filings = 0 or slugs missing)."
        )
    logger.info("[HTTP] Job title directory: OK (has entries)")

    status, body = _curl_localhost(runner, "/employers/", host_header="localhost")
    if status != 200:
        raise RuntimeError(f"Employer directory returned HTTP {status}.")
    if body.count("/employer/") < MIN_DIRECTORY_ENTRIES:
        raise RuntimeError(
            f"Employer directory has fewer than {MIN_DIRECTORY_ENTRIES} entries. "
            "Page may be empty (filing counts = 0 or slugs missing)."
        )
    logger.info("[HTTP] Employer directory: OK (has entries)")

    status, _ = _curl_localhost(
        runner, "/salaries/", timeout_sec=30, host_header="localhost"
    )
    if status != 200:
        raise RuntimeError(
            f"Salaries page returned HTTP {status} (expected 200). "
            "Check template syntax and salary_search_view for errors."
        )
    logger.info("[HTTP] Salaries page: OK (200)")

    status, _ = _curl_localhost(
        runner, "/", timeout_sec=30, host_header="localhost"
    )
    if status != 200:
        raise RuntimeError(
            f"Dashboard returned HTTP {status} (expected 200). "
            "Check dashboard_view and template for errors."
        )
    logger.info("[HTTP] Dashboard: OK (200)")

    # Blog / analysis pages — templates hardcode /analysis/<slug>/ links; a 404 here means
    # every 'How it works →' popover on the dashboard would be broken after graduation.
    status, body = _curl_localhost(runner, "/analysis/", host_header="localhost")
    if status != 200:
        raise RuntimeError(
            f"Blog listing (/analysis/) returned HTTP {status} (expected 200). "
            "Check blog_list view and models_blogpost table."
        )
    if "/analysis/" not in body:
        raise RuntimeError(
            "Blog listing (/analysis/) rendered but contains no post links. "
            "Is models_blogpost empty or is_published=False for all rows?"
        )
    logger.info("[HTTP] Blog listing (/analysis/): OK (200, has links)")

    status, _ = _curl_localhost(
        runner, f"/analysis/{REQUIRED_BLOG_SLUG}/", host_header="localhost"
    )
    if status != 200:
        raise RuntimeError(
            f"Required blog post /analysis/{REQUIRED_BLOG_SLUG}/ returned HTTP {status}. "
            "This URL is linked from dashboard, about, faq, and prediction-detail pages. "
            "Graduating with a 404 here breaks all 'How it works →' popovers."
        )
    logger.info("[HTTP] Required blog post (%s): OK (200)", REQUIRED_BLOG_SLUG)

    # Prediction category landing — redirects (302) to latest bulletin month detail page
    status, _ = _curl_localhost(
        runner, "/predictions/employment_based/", host_header="localhost"
    )
    if status not in (200, 302):
        raise RuntimeError(
            f"/predictions/employment_based/ returned HTTP {status} (expected 200 or 302). "
            "prediction_category_landing view or URL pattern may be missing."
        )
    logger.info("[HTTP] Prediction category landing (/predictions/employment_based/): OK (%d)", status)

    # VQS prediction detail chart — follow the category landing redirect (302 → YYYY-M page)
    # to verify chart_builder produces Plotly data. Uses curl -L to follow the redirect.
    result = runner.run_shell(
        "curl -s -L -w '\\n%{http_code}' --max-time 30 -H 'Host: localhost' "
        "'http://localhost:8000/predictions/employment_based/'",
        timeout_sec=35,
    )
    output = (result.stdout or "").strip()
    lines = output.rsplit("\n", 1)
    pred_status = int(lines[1]) if len(lines) == 2 and lines[1].isdigit() else 0
    pred_body = lines[0] if len(lines) == 2 else output

    if pred_status != 200:
        raise RuntimeError(
            f"Prediction detail (employment_based, following redirect) returned HTTP {pred_status}. "
            "Check prediction_category_landing → prediction_detail view chain."
        )
    if "plotly" not in pred_body.lower():
        raise RuntimeError(
            "Prediction detail page rendered (200) but Plotly chart data is absent. "
            "chart_builder may have raised silently or vqs_predictions dict is empty."
        )
    logger.info("[HTTP] Prediction detail (employment_based, following redirect) with Plotly chart: OK (200)")

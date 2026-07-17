"""Regression tests for the GoatCounter surface classifier (2026-07-17).

The digest's per-surface breakdown reported ~2.4k views/wk (4.7% of ALL
pageviews) as `other`. The biggest contributors were not genuine long tail —
they were real, named pages the classifier could not see:

  * `/predictions`                 707 views/wk  -> `^/predictions/` hard-requires
                                                   a trailing slash; GC strips it.
  * `/employment-based`            268 views/wk  -> same bug; ALSO vanished from
                                                   the main-entry line.
  * `/when-is-the-next-visa-...`  1418 views/wk  -> no bucket at all (the top
                                                   wait-window entry point).
  * /methodology, /corrections, /ai-citation     -> no bucket.

Plus one latent over-capture: `^/es/?` matches ANY path starting with "es", so
a future `/estimate` would silently be reported as Spanish-cluster traffic.

The failure mode is SILENT: a miscounted surface looks exactly like long tail,
so a top-5 entry point can go missing from the KPI block and nobody notices.
These tests pin the contract so the next pattern edit can't reintroduce it.

Run: `uv run pytest test_surface_patterns.py` from this dir (same convention as
test_daily_checkup_server.py — the module needs httpx/mcp, so it is not a bazel
target).
"""

import re

import daily_checkup_server as m

# ── Trailing-slash contract: GC strips it, so hubs must still classify ───────


def test_bare_hub_paths_are_not_other():
    """Each of these is how GoatCounter actually records the hub page."""
    for path, expected in [
        ("/predictions", "predictions"),
        ("/employment-based", "dashboard"),
        ("/when-is-the-next-visa-bulletin", "bulletin_timing"),
        ("/methodology", "static_pages"),
        ("/corrections", "static_pages"),
        ("/ai-citation", "static_pages"),
    ]:
        got = m._bucket_path(path)
        assert got == expected, (
            f"{path} -> {got!r} (want {expected!r}); it would hide in `other` as long tail"
        )


def test_slashed_and_child_forms_still_classify():
    for path, expected in [
        ("/predictions/", "predictions"),
        ("/predictions/august-2026", "predictions"),
        ("/predictions/august-2026/", "predictions"),
        ("/employment-based/", "dashboard"),
        ("/employment-based/india/", "dashboard"),
        ("/when-is-the-next-visa-bulletin/", "bulletin_timing"),
        ("/faq", "static_pages"),
        ("/faq/", "static_pages"),
        ("/", "dashboard"),
    ]:
        assert m._bucket_path(path) == expected, path


# Buckets whose pattern may legitimately hard-require a trailing slash, because
# the bare path is NOT a route and so can never appear in the export. Verified
# 2026-07-17 against webapp/urls.py (no `path("employer/")` etc.) and against the
# full GC export (zero all-time hits on /job-title, /employer, /api). If you add
# a hub route for one of these, drop it from this set and switch it to `(/|$)`.
_NO_BARE_HUB_ROUTE = {"job_title_profile", "employer_profile", "api"}


def test_no_prefix_bucket_hard_requires_a_trailing_slash():
    """A `^/foo/`-style pattern silently loses `/foo` — allowed only with no hub route."""
    offenders = {
        name
        for name, pat in m.SURFACE_PATTERNS
        if pat.pattern.endswith("/") and not pat.pattern.endswith(("/?", "(/|$)", "/?$"))
    }
    unexpected = offenders - _NO_BARE_HUB_ROUTE
    assert unexpected == set(), (
        f"{sorted(unexpected)} end in a hard `/`, so their bare hub path falls silently into "
        "`other`; use `(/|$)` — or add to _NO_BARE_HUB_ROUTE if the bare path is not a route"
    )
    # Keep the exemption list honest: an entry that no longer ends in a hard `/`
    # (someone already fixed it) should be removed rather than linger.
    assert _NO_BARE_HUB_ROUTE <= offenders, (
        f"stale _NO_BARE_HUB_ROUTE entries: {sorted(_NO_BARE_HUB_ROUTE - offenders)}"
    )


# ── The fix must not make any bucket greedy ─────────────────────────────────


def test_spanish_does_not_steal_es_prefixed_paths():
    assert m._bucket_path("/estimate") == "other"
    assert m._bucket_path("/es") == "spanish"
    assert m._bucket_path("/es/") == "spanish"
    assert m._bucket_path("/es/faq/") == "spanish"


def test_prefix_buckets_do_not_steal_lookalikes():
    assert m._bucket_path("/predictions-archive") == "other"
    assert m._bucket_path("/employment-based-archive") == "other"


def test_employer_profile_does_not_steal_the_directory():
    assert m._bucket_path("/employer/microsoft-corporation/") == "employer_profile"
    assert m._bucket_path("/employers") == "employer_directory"
    assert m._bucket_path("/employers/rankings/") == "employer_rankings"


# ── The main-entry line has the same trailing-slash trap ────────────────────


def test_bare_employment_based_counts_as_eb_other():
    assert m._main_entry_bucket("/employment-based") == "eb_other"


def test_india_split_survives_the_fix():
    assert m._main_entry_bucket("/employment-based/india") == "eb_india"
    assert m._main_entry_bucket("/employment-based/india/") == "eb_india"
    assert m._main_entry_bucket("/employment-based/mexico") == "eb_other"
    assert m._main_entry_bucket("/") == "home"
    assert m._main_entry_bucket("/family-sponsored/india/") == "fs"
    assert m._main_entry_bucket("/salaries/") is None


# ── Taxonomy integrity ─────────────────────────────────────────────────────


def test_every_bucket_has_a_human_label():
    missing = [name for name, _ in m.SURFACE_PATTERNS if name not in m.SURFACE_LABELS]
    assert missing == [], f"{missing} would render as a raw key in the digest"


def test_other_has_a_label():
    assert "other" in m.SURFACE_LABELS


def test_bucket_names_are_unique():
    names = [name for name, _ in m.SURFACE_PATTERNS]
    assert len(names) == len(set(names))


def test_patterns_compile_and_are_anchored():
    for name, pat in m.SURFACE_PATTERNS:
        assert isinstance(pat, re.Pattern), name
        assert pat.pattern.startswith("^"), f"{name} is unanchored — would match mid-path"

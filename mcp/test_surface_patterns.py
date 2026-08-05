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
import shutil
import subprocess

import daily_checkup_server as m
import pytest

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


# ── One taxonomy, two scopes: the awk classifier is GENERATED ────────────────
#
# Per-surface latency comes from an awk program over the prod nginx log, which
# cannot import SURFACE_PATTERNS. That chain used to be hand-copied and drifted:
# by 2026-08-05 it was missing `bulletin_timing`, `spanish`, `priority_date`,
# `occupation_salary` and `h1b_sponsors`, so 679 real hits in 24h were reported
# as "no nginx traffic" for four live pSEO families — which is how a 4-6s cold
# render on /h1b-salary/ went unnoticed for weeks. The failure is silent by
# construction: an unclassifiable surface is indistinguishable from an idle one.
#
# These tests run the GENERATED awk through the real awk binary and require it
# to agree with `_bucket_path` path-for-path, so the two scopes cannot drift
# again without a red test.

# Representative of every bucket, in both the bare and trailing-slash forms
# (nginx logs the real request path; GoatCounter strips the trailing slash).
_CLASSIFIER_CASES = [
    "/", "/?utm=x", "/employment-based", "/employment-based/", "/employment-based/india/",
    "/job-title/software-engineer/", "/job-titles/", "/employer/google-llc/",
    "/employers/", "/employers/rankings/", "/predictions", "/predictions/",
    "/predictions/august-2026/", "/when-is-the-next-visa-bulletin",
    "/when-is-the-next-visa-bulletin/", "/analysis/foo/", "/salaries/", "/salaries/?q=x",
    "/worksites", "/worksites/", "/family-sponsored/", "/es", "/es/",
    "/es/priority-date/eb2/india/", "/estimate", "/priority-date", "/priority-date/",
    "/priority-date/eb2/india/", "/priority-date-calculator/", "/h1b-salary",
    "/h1b-salary/", "/h1b-salary/nurse/", "/h1b-salary/google-llc/engineer/",
    "/h1b-sponsors", "/h1b-sponsors/in/ny/", "/faq", "/faq/", "/methodology",
    "/corrections", "/ai-citation", "/some-random-thing/", "/privacy/",
]


def _awk_bin() -> str:
    # mawk is what the homeserver runs; prefer it so the test exercises the same
    # ERE engine the generated program will actually meet in production.
    for candidate in ("mawk", "gawk", "awk"):
        found = shutil.which(candidate)
        if found:
            return found
    pytest.skip("no awk binary available")


def _classify_with_awk(paths: list[str]) -> list[str]:
    chain = m._awk_surface_classifier(indent="")
    prog = f'BEGIN{{FS="\\t"}} {{ path=$1; {chain} ; print surf }}'
    res = subprocess.run(
        [_awk_bin(), prog], input="\n".join(paths), capture_output=True, text=True
    )
    assert res.returncode == 0, f"generated awk did not parse: {res.stderr}"
    return res.stdout.strip().split("\n")


def test_generated_awk_agrees_with_python_on_every_bucket():
    """The load-bearing test: both scopes must classify identically."""
    got = _classify_with_awk(_CLASSIFIER_CASES)
    mismatches = [
        (p, m._bucket_path(p), a) for p, a in zip(_CLASSIFIER_CASES, got) if m._bucket_path(p) != a
    ]
    assert mismatches == [], (
        "nginx-side and GoatCounter-side classifiers disagree: "
        + "; ".join(f"{p} py={py} awk={aw}" for p, py, aw in mismatches)
    )


def test_the_four_blinded_pseo_surfaces_classify_in_awk():
    """The exact 2026-08-05 regression: 679 hits/24h reported as no traffic."""
    paths = ["/h1b-salary/nurse/", "/priority-date/eb2/india/", "/h1b-sponsors/in/ny/", "/es/"]
    expected = ["occupation_salary", "priority_date", "h1b_sponsors", "spanish"]
    assert _classify_with_awk(paths) == expected


def test_every_nginx_visible_surface_reaches_the_awk_chain():
    chain = m._awk_surface_classifier()
    for name, _ in m.SURFACE_PATTERNS:
        if name in m._AWK_SKIPPED_SURFACES:
            assert f'surf = "{name}"' not in chain, f"{name} cannot occur in an nginx log"
        else:
            assert f'surf = "{name}"' in chain, (
                f"{name} is classified for GoatCounter but not for nginx — its latency "
                "would be reported as 'no nginx traffic'"
            )


def test_generated_awk_is_shell_and_fstring_safe():
    """The chain is embedded in a single-quoted shell string inside an f-string."""
    chain = m._awk_surface_classifier()
    assert "'" not in chain, "an apostrophe terminates the shell-quoted awk program early"
    assert "{" not in chain and "}" not in chain, "a brace breaks the f-string / awk block"


def test_untranslatable_patterns_are_rejected_loudly():
    """A Python-only construct must fail at generation, not silently misclassify."""
    with pytest.raises(ValueError, match="not anchored"):
        m._awk_surface_literal("x", r"/unanchored/")
    with pytest.raises(ValueError, match="Python-only regex"):
        m._awk_surface_literal("x", r"^/foo(?!bar)")
    with pytest.raises(ValueError, match="Python-only regex"):
        m._awk_surface_literal("x", r"^/foo\d+")


def test_privacy_is_a_static_page_not_unclassified():
    """`/privacy/` is a flat informational route (webapp/urls.py), not `other`.

    Found by the `other` row on its first real run (2026-08-05): the residual
    named `/privacy` as the only unbucketed live path on the site.
    """
    assert m._bucket_path("/privacy") == "static_pages"     # GC strips the slash
    assert m._bucket_path("/privacy/") == "static_pages"

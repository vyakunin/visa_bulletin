"""Static guard: every growth headline on the site carries its base-year gate.

A growth percentage divides by its base year's filing count, so at a base of N one
filing moves the headline by 100/N points. Measured on prod 2026-08-18: 22,485 of
the 23,782 job-title clusters that render a growth figure sit under a base of 10,
as do 27,632 of the 29,301 employer profiles. The fix is a floor
(common_stats.GROWTH_MIN_BASE_FILINGS) plus the endpoint counts beside the figure.

Three surfaces render one, and this file is the enumeration: a fourth has to come
here and declare itself. Three nets hold it, because a rule that lives only in
prose reopens the next time someone adds a tile:

  * common_stats.growth_headline is the only way to obtain the percentage outside
    that module, and it returns the gate in the same dict -- so the gate cannot be
    forgotten, only ignored;
  * the templates rendering yoy_growth are exactly the three listed below, and
    each must consult the gate and carry the endpoint counts;
  * no other template labels a stat tile as Growth, which catches a surface that
    computes the figure its own way under a different context key.

The first net is only as wide as this test's runfiles and covers
lib/business/salary plus every view module; the two template nets glob every
template there is, so they cannot miss a file.

What this CANNOT verify (a rendering test can): that the gate actually withholds
the tile. That is GrowthTileBaseFloorTest in test_job_title_profile_view.py and
test_employer_profile_view.py, and MarketOverviewGrowthGateTest in
test_salary_search_view.py.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# The primitives that produce a growth percentage without a gate beside it.
# growth_headline is the sanctioned wrapper; it lives with them, so this module
# is the one place they may be named.
_UNGATED_PRIMITIVES = ("calculate_yoy_growth", "growth_endpoint_counts")
_PRIMITIVE_HOME = _REPO / "lib/business/salary/common_stats.py"

# Every template that renders a growth percentage. Adding one means adding it
# here, which is the point.
_GROWTH_TEMPLATES = (
    "webapp/templates/webapp/employer_profile.html",
    "webapp/templates/webapp/job_title_profile.html",
    "webapp/templates/webapp/salary_search.html",
)

_GATE = "show_yoy_growth"


# A scan is only as wide as its runfiles, and a missing data dep would make every
# assertion below pass vacuously. These three are the surfaces that consume the
# growth figure today, so their presence is the proof the scan reached anything.
_MUST_BE_SCANNED = (
    "lib/business/salary/job_title_stats.py",
    "lib/business/salary/market_overview.py",
    "webapp/views/employers/profile.py",
)


def _python_sources():
    """The packages a growth tile can be computed in.

    lib/business/salary is where the primitives live and is complete by
    construction (//lib/business/salary:all_py globs the package); webapp
    arrives through //webapp:urls + //webapp/views:views, which is every view
    module. The rest of lib/ is the ingest, parsing and VQS side, which renders
    no HTML — the template scan below is what covers a surface reached some
    other way, and that one globs every template there is.
    """
    found = []
    for root in ("lib/business/salary", "webapp"):
        base = _REPO / root
        assert base.is_dir(), (
            f"{root}/ is absent from the test's runfiles — add its sources to the "
            "data of //tests:test_growth_tile_guard, or this guard silently passes."
        )
        found.extend(sorted(base.rglob("*.py")))
    scanned = {str(p.relative_to(_REPO)) for p in found}
    missing = [rel for rel in _MUST_BE_SCANNED if rel not in scanned]
    assert not missing, (
        f"these never reached the scan: {missing}. A data dep of "
        "//tests:test_growth_tile_guard was dropped, so this guard was about to "
        "report a clean sweep over files it cannot see."
    )
    return found


def test_growth_headline_is_the_only_way_to_get_the_percentage():
    """A new surface cannot obtain the number without the gate that rides with it."""
    offenders = []
    for path in _python_sources():
        if path == _PRIMITIVE_HOME:
            continue
        src = path.read_text(encoding="utf-8")
        for name in _UNGATED_PRIMITIVES:
            if re.search(rf"\b{name}\s*\(", src):
                offenders.append(f"{path.relative_to(_REPO)} calls {name}()")

    assert not offenders, (
        "these call a growth primitive directly, so their surface can render a "
        "percentage with no base-year gate:\n  "
        + "\n  ".join(offenders)
        + "\nUse common_stats.growth_headline() instead — it returns the figure, "
        "the endpoint counts and show_yoy_growth together."
    )


def test_the_templates_that_render_growth_are_the_declared_ones():
    """The enumeration is closed: a fourth growth tile has to be added here."""
    rendering = {
        str(p.relative_to(_REPO))
        for p in sorted((_REPO / "webapp/templates").rglob("*.html"))
        if "yoy_growth" in p.read_text(encoding="utf-8")
    }
    assert rendering, "no template reached this test — check the data deps"
    assert rendering == set(_GROWTH_TEMPLATES), (
        "the set of templates rendering a growth percentage changed.\n"
        f"  found:    {sorted(rendering)}\n"
        f"  declared: {sorted(_GROWTH_TEMPLATES)}\n"
        "A new one must gate on show_yoy_growth and be listed in _GROWTH_TEMPLATES."
    )


def test_every_growth_tile_consults_the_gate():
    """Rendering the percentage without reading the gate is the original defect."""
    for rel in _GROWTH_TEMPLATES:
        src = (_REPO / rel).read_text(encoding="utf-8")
        assert _GATE in src, (
            f"{rel} renders a growth percentage but never reads {_GATE}, so it "
            "prints the figure on any base year — including a base of 1, which is "
            "what produced +79000.0% on /job-title/systems-analystdeveloper-b/."
        )


def test_the_shown_figure_carries_the_counts_it_divides():
    """A percentage a reader cannot check is the half of the defect a floor leaves."""
    for rel in _GROWTH_TEMPLATES:
        src = (_REPO / rel).read_text(encoding="utf-8")
        for field in ("growth_base_filings", "growth_end_filings"):
            assert field in src, (
                f"{rel} renders a growth percentage without {field}. The endpoint "
                "counts are what make the figure checkable against the page."
            )


def test_no_other_template_labels_a_tile_as_growth():
    """The net that does not depend on the context key a new surface picks.

    //webapp:templates globs every template, so unlike the source scan this one
    cannot miss a file. A growth tile is a stat card whose label says Growth, so
    a fourth one shows up here even if it computes the figure its own way and
    calls it something other than yoy_growth.
    """
    labelled = {
        str(p.relative_to(_REPO))
        for p in sorted((_REPO / "webapp/templates").rglob("*.html"))
        if re.search(r'label="[^"]*Growth[^"]*"', p.read_text(encoding="utf-8"))
    }
    assert labelled == set(_GROWTH_TEMPLATES), (
        "the set of templates labelling a stat tile as Growth changed.\n"
        f"  found:    {sorted(labelled)}\n"
        f"  declared: {sorted(_GROWTH_TEMPLATES)}\n"
        "A new growth tile must be gated on a base-year floor before it ships — "
        "see common_stats.GROWTH_MIN_BASE_FILINGS — and listed in "
        "_GROWTH_TEMPLATES."
    )


def test_no_surface_still_calls_the_figure_year_over_year():
    """It spans the first and last qualifying year of a reader-selected window.

    `?years=` / `?program=` / `?level=` all move those endpoints, so the retired
    "YoY Growth" label was wrong about its own arithmetic wherever it appeared.
    """
    offenders = [
        str(p.relative_to(_REPO))
        for p in sorted((_REPO / "webapp/templates").rglob("*.html"))
        if "YoY Growth" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "these label the growth tile 'YoY Growth', which it is not: " f"{offenders}"
    )

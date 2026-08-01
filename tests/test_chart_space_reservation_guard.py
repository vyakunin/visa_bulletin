"""Static guard: the dashboard trend chart must reserve its height before it renders.

The chart is lazy-loaded (Plotly is fetched only once #chart-container intersects the
viewport), so the container is a spinner for several seconds and then becomes a
DASHBOARD_CHART_HEIGHT_PX-tall plot. Whatever holds that reservation has to be an
element that is actually laid out: #chart-plot ships `display:none` until the chart is
ready, so a min-height there occupies nothing and the swap pushes the whole page down
(measured 182px -> 400px, CLS ~0.17 on mobile at 390px, on / and /employment-based/*/).

The reservation therefore lives on #chart-content, and its value comes from the chart
builder's own layout height so the CSS cannot drift away from what Plotly renders.

What this CANNOT verify (a browser can): the resulting CLS. That is
`visa_bulletin_platform/scripts/measure_cls.py`, which is the gate before promotion.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DASHBOARD = _REPO / "webapp/templates/webapp/dashboard.html"
_BASE = _REPO / "webapp/templates/webapp/base.html"
_CHART_BUILDER = _REPO / "lib/business/bulletin/chart_builder.py"


def _dashboard() -> str:
    return _DASHBOARD.read_text(encoding="utf-8")


def test_chart_content_reserves_the_chart_height():
    """#chart-content carries a min-height, so the spinner->chart swap shifts nothing."""
    m = re.search(
        r'id="chart-content"[^>]*style="[^"]*min-height:\s*([^;"]+)', _dashboard()
    )
    assert m, (
        "#chart-content must reserve the chart's height inline. Without it the "
        "spinner (~182px) is replaced by the rendered chart and everything below "
        "jumps down. See .claude/rules/ for the CLS baseline."
    )
    assert "chart_height_px" in m.group(1), (
        "the reserved height must come from chart_data.chart_height_px, not a "
        f"hardcoded value (got {m.group(1)!r}) — a literal drifts from the Plotly "
        "layout height and silently reintroduces the shift."
    )


def test_reservation_is_not_placed_on_the_hidden_element():
    """A min-height on #chart-plot reserves nothing — it is display:none until render."""
    assert re.search(r'id="chart-plot"[^>]*display:\s*none', _dashboard()), (
        "#chart-plot is expected to start hidden; if that changed, revisit where the "
        "chart's space is reserved."
    )
    for path in (_BASE, _DASHBOARD):
        src = path.read_text(encoding="utf-8")
        for block in re.finditer(r"#chart-plot\s*\{([^}]*)\}", src):
            assert "min-height" not in block.group(1), (
                f"{path.name} reserves space on #chart-plot, which is display:none "
                "until the chart renders — the reservation occupies nothing. Put it "
                "on #chart-content instead."
            )


def test_builder_exports_the_height_it_renders_at():
    """The template's reservation and the Plotly layout read the same constant."""
    src = _CHART_BUILDER.read_text(encoding="utf-8")
    assert re.search(r"^DASHBOARD_CHART_HEIGHT_PX\s*=\s*\d+", src, re.M), (
        "chart_builder must define DASHBOARD_CHART_HEIGHT_PX as the single owner of "
        "the rendered chart height."
    )
    assert "height=DASHBOARD_CHART_HEIGHT_PX" in src, (
        "the Plotly layout must use DASHBOARD_CHART_HEIGHT_PX, not a literal, or the "
        "template's reservation no longer matches what renders."
    )
    assert '"chart_height_px": DASHBOARD_CHART_HEIGHT_PX' in src, (
        "the chart payload must expose chart_height_px so the template can reserve it."
    )

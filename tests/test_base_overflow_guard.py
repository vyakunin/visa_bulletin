"""Static guard: no page may scroll horizontally because of an unfilled ad slot.

An UNFILLED AdSense auto-placed slot collapses its `ins` to `width: 0` but leaves
the aswift host div at its inline `width: 1200px`. Centred inside the 0-width ins,
the host starts mid-page (left~713) and runs to ~1913px on a 1440px window, giving
the whole page a horizontal scrollbar. Observed on `/`, `/employers/rankings/` and
`/predictions/*` (the ad markup is Google's, so the fix must live on our side).

`base.html` pins this with `html, body { overflow-x: clip }`. This asserts the guard
stays wired — every page renders through base.html, so the rule lives there once.

Why `clip` and not `hidden` is load-bearing, not style: `hidden` makes the viewport a
scrollport and breaks every `position: sticky` element on the site (measured: a sticky
header scrolls away under `hidden`, stays pinned at top:0 under `clip`). So this test
also fails if someone "simplifies" clip -> hidden.

What this CANNOT verify (a real browser can): that the guard actually kills the
scrollbar against a live unfilled slot. That is the end-state check in
visa_bulletin_platform/scripts/verify_ad_render.py (asserts scrollWidth <= clientWidth
over CDP at a real viewport).
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BASE = _REPO / "webapp/templates/webapp/base.html"


def _overflow_guard_rule(css_source: str) -> str | None:
    """Return the declared overflow-x value guarding html/body, if any."""
    match = re.search(
        r"html\s*,\s*body\s*\{[^}]*overflow-x:\s*(?P<value>[a-z]+)",
        css_source,
    )
    return match.group("value") if match else None


def test_base_has_horizontal_overflow_guard():
    value = _overflow_guard_rule(_BASE.read_text(encoding="utf-8"))
    assert value is not None, (
        "base.html must guard horizontal overflow with `html, body { overflow-x: clip }`. "
        "Without it an unfilled AdSense auto-placed slot (aswift host stuck at inline "
        "width:1200px) gives every page a horizontal scrollbar."
    )


def test_overflow_guard_uses_clip_not_hidden():
    value = _overflow_guard_rule(_BASE.read_text(encoding="utf-8"))
    assert value == "clip", (
        f"overflow-x guard must be `clip`, found `{value}`. `hidden` turns the viewport "
        "into a scrollport and breaks every position:sticky element on the site "
        "(e.g. .results-table th); `clip` only establishes a clip container, so sticky "
        "and nested overflow-x:auto table scrollers keep working."
    )

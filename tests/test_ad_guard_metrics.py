"""The ad sweep's guard metrics must count what the screenshot shows.

Two blind spots let a visibly broken surface report a clean manifest. Both were
reproduced in every weekly run from 2026-07-27 to 2026-08-10 (27 captured shots:
20 carried at least one unfilled slot, and `slots_reserved_empty` read 0 on all
27 — a rule that never fires once in 27 chances is not measuring its subject).

BLIND SPOT 1 — reserved-empty counted the wrong box.
`ad_slot.html` hides an unfilled unit with
`.vb-ad-slot ins.adsbygoogle[data-ad-status="unfilled"]{display:none}`, so the
`ins` measures 0px tall. The old rule counted unfilled `ins` taller than 1px, so
it could never fire. Meanwhile the reserved height lives on the WRAPPER
(`.vb-ad-slot{min-height:280px}`, +24 when hoisted), which is what the reader
actually sees as a blank band. Measured in a local headless chromium against a
fixture built from the real CSS: a hoisted no-fill wrapper is 304px and a pos-2
wrapper 280px — 584px of visible blank — while both their `ins` elements report
height 0 / display:none. The old rule scored that 1 slot / 90px, and the 90px was
a bare auto-placed `ins` outside any wrapper, i.e. it missed every real hole and
counted something else.

BLIND SPOT 2 — over-wide counted scroll-contained elements.
`widest_el_px` is the max `getBoundingClientRect().right` over every element, so
it counts a wide table sitting inside its own `overflow-x:auto` scroller. That is
correct responsive behaviour, not a defect — base.html deliberately keeps those
scrollers working (see test_base_overflow_guard). On the same fixture it reported
2000px on BOTH a 1440 and a 390 viewport, and 2000px was the innocent table; the
element genuinely escaping to the page (the aswift host that caused the 2026-07
sitewide scrollbar) was a different node at 1200px. So flagging `widest_el_px >
viewport` naively would fire on healthy mobile tables (real runs: 837/839/821/462
px against a 390 viewport) while misattributing the blame.

What the metric must therefore use is the widest element NOT contained by a
scroller/clip below body — the one that truly reaches the page edge.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "ad_surface_screenshots.py"


def _load_sweep():
    """Import the sweep script by path (it is a PEP-723 CLI, not a package)."""
    spec = importlib.util.spec_from_file_location("ad_surface_screenshots", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sweep = _load_sweep()


def _slot(**kw):
    """An `.vb-ad-slot` wrapper as the in-page probe reports it.

    `ins_px=0` is the measured default, not a convenience: an unfilled unit is
    `display:none` under ad_slot.html's CSS, so the `ins` really does report
    zero height while the wrapper around it still shows a 280-304px band.
    """
    base = {"pos": "1", "height_px": 280, "collapsed": False, "label_shown": False,
            "hoisted": False, "filled_px": 0, "ins_px": 0}
    return sweep.AdSlotFacts(**{**base, **kw})


# ── Blind spot 1: the hole is on the wrapper, not the hidden ins ─────────────

def test_wrapper_reserving_height_with_hidden_ins_counts_as_reserved_empty():
    """The exact fixture measurement: 304px hoisted + 280px pos-2, ins 0px each."""
    metrics = sweep.derive_guard_metrics(
        [_slot(pos="1", height_px=304, hoisted=True, label_shown=True),
         _slot(pos="2", height_px=280)],
        escaping_el_px=0, viewport_width=1440,
    )
    assert metrics.slots_reserved_empty == 2
    assert metrics.reserved_empty_px == 584, (
        "a wrapper holding its reserved band with nothing rendered in it is a "
        "visible blank; measuring the display:none `ins` instead scores it 0."
    )


def test_filled_slot_is_not_reserved_empty():
    metrics = sweep.derive_guard_metrics(
        [_slot(height_px=280, filled_px=280)], escaping_el_px=0, viewport_width=1440)
    assert metrics.slots_reserved_empty == 0
    assert metrics.reserved_empty_px == 0


def test_collapsed_slot_is_not_reserved_empty():
    """A below-fold no-fill collapses to nothing — it leaves no hole to report."""
    metrics = sweep.derive_guard_metrics(
        [_slot(height_px=0, collapsed=True)], escaping_el_px=0, viewport_width=1440)
    assert metrics.slots_reserved_empty == 0
    assert metrics.reserved_empty_px == 0


def test_labelled_blank_is_reported_separately_from_a_bare_reserved_band():
    """ad_slot.html's own invariant: an empty band is a trade, a LABELLED one is a bug.

    `collapseUnlessHoisted` drops `.vb-ad-live` on a no-fill precisely so the
    "ADVERTISEMENT" caption goes with the creative that never came. The
    screenshots show captions over blanks anyway, so the two cases need separate
    numbers: the bare band is deliberate, the labelled one is not.
    """
    metrics = sweep.derive_guard_metrics(
        [_slot(pos="1", height_px=304, hoisted=True, label_shown=True),
         _slot(pos="2", height_px=280, label_shown=False)],
        escaping_el_px=0, viewport_width=1440,
    )
    assert metrics.reserved_empty_px == 584
    assert metrics.labelled_empty_slots == 1
    assert metrics.labelled_empty_px == 304


# ── Blind spot 2: over-wide must ignore scroll-contained elements ────────────

def test_over_wide_ignores_a_scroll_contained_table():
    """The probe must not hand up a contained element as the escaping width."""
    metrics = sweep.derive_guard_metrics([], escaping_el_px=0, viewport_width=390)
    assert metrics.over_wide_px == 0


def test_over_wide_reports_an_element_that_escapes_to_the_page():
    """The 2026-07 shape: aswift host reaching 1913px on a 1440 viewport."""
    metrics = sweep.derive_guard_metrics([], escaping_el_px=1913, viewport_width=1440)
    assert metrics.over_wide_px == 473, (
        "overflow-x:clip suppresses the scrollbar overflow_px measures, so an "
        "escaping element must be flagged on its own width, not via overflow_px."
    )


def test_over_wide_is_zero_when_the_widest_element_fits():
    metrics = sweep.derive_guard_metrics([], escaping_el_px=1425, viewport_width=1440)
    assert metrics.over_wide_px == 0


# ── The probe must actually collect what the derivation needs ────────────────

@pytest.mark.parametrize("field", [
    "ad_slots",          # per-wrapper facts (blind spot 1)
    "escaping_el_px",    # widest NOT scroll-contained (blind spot 2)
    "viewport_width",    # the width to compare it against
])
def test_probe_js_collects_the_fields_the_metrics_derive_from(field):
    """A derivation is only as good as the facts the in-page probe hands it.

    Cheap to break by editing PROBE_JS and forgetting the Python side, and the
    failure would be silent: a missing key reads as a clean surface.
    """
    assert field in sweep.PROBE_JS, (
        f"PROBE_JS must report `{field}` — derive_guard_metrics reads it, and a "
        "missing field degrades to a zero, which is exactly the clean-looking "
        "row this guard exists to prevent."
    )


# ── The same false all-clear, one device wide ────────────────────────────────

def _shot(device, slots_total, **kw):
    return {"device": device, "slots_total": slots_total, "captured": True, **kw}


def test_a_device_class_rendering_no_slots_is_a_blackout():
    """2026-08-10: 5/5 desktop shots captured the real site with 0 slots.

    Mobile rendered 4-9, so the all-shots-zero gate stayed quiet and the run
    reported clean while half of it had measured nothing about the ad layer.
    """
    shots = [_shot("desktop", 0) for _ in range(5)] + [
        _shot("mobile", 9), _shot("mobile", 4), _shot("mobile", 0)]
    assert sweep.blackout_devices(shots) == ["desktop"]


def test_no_blackout_when_every_device_rendered_something():
    shots = [_shot("desktop", 3), _shot("desktop", 0), _shot("mobile", 9)]
    assert sweep.blackout_devices(shots) == []


def test_blackout_ignores_shots_that_never_captured_the_site():
    """A WAF-challenged shot has no opinion about the ad layer either way.

    Counting its zero would turn one blocked surface into a fake device-wide
    blackout, which is the inverse of the bug and just as misleading.
    """
    shots = [{"device": "desktop", "captured": False, "capture_error": "WAF challenge"},
             _shot("desktop", 7)]
    assert sweep.blackout_devices(shots) == []


def test_blackout_reports_both_devices_when_the_whole_run_is_dark():
    shots = [_shot("desktop", 0), _shot("mobile", 0)]
    assert sweep.blackout_devices(shots) == ["desktop", "mobile"]


def test_a_device_that_only_loads_its_ads_on_scroll_is_not_a_blackout():
    """Both units are IntersectionObserver-gated, so desktop's first paint is zero.

    Nothing hoists pos-1 above the fold there, so it loads at ~1,800px of scroll and
    pos-2 at its own mid-content anchor. Read at first paint that is a device-wide
    blackout; read after the scroll pass it is an ordinary lazy-loaded page. The gate
    reads the post-scroll count so the sweep stops calling a lazy load an outage.
    """
    shots = [_shot("desktop", 0, slots_total_scrolled=2) for _ in range(5)]
    assert sweep.blackout_devices(shots) == []


def test_a_device_dark_after_the_scroll_pass_is_still_a_blackout():
    shots = [_shot("desktop", 0, slots_total_scrolled=0),
             _shot("mobile", 0, slots_total_scrolled=6)]
    assert sweep.blackout_devices(shots) == ["desktop"]


def test_probe_js_still_measures_the_wrapper_not_only_the_ins():
    """Guard the class-name contract with the private repo's ad_slot.html.

    `.vb-ad-slot` / `vb-ad-collapsed` / `vb-ad-live` are defined in
    visa_bulletin_platform/monetization/ad_slot.html and consumed here. Nothing
    in this repo can import them, so a rename there silently zeroes these
    metrics again; this at least pins our side of the contract.
    """
    for cls in (".vb-ad-slot", "vb-ad-collapsed", "vb-ad-live"):
        assert cls in sweep.PROBE_JS, f"PROBE_JS lost the `{cls}` contract"

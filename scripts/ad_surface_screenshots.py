#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp>=1.0.0,<2", "pillow", "playwright"]
# ///
"""Weekly visual + structural sweep of the top ad-bearing surfaces.

WHY THIS EXISTS — the ad layer is the one part of visa-bulletin.us that renders
differently for every visitor and is invisible to the test suite: slots are
injected by Google at runtime, fill rates vary by viewport/UA/demand, and an
unfilled slot has repeatedly caused user-visible damage that no unit test could
see (the 2026-07 sitewide horizontal scrollbar from an unfilled 1200px
auto-placed slot; the pos-2 reserved box that sits empty ~6s then collapses).
Screenshots are the only artifact that shows what a real reader actually gets,
and the structural probes below turn "looks fine" into numbers.

WHAT IT DOES
  1. Derives the top-N surfaces BY TRAFFIC from the full GoatCounter export
     (100% path coverage — never the top-100 `/stats/hits` cap, see
     `~/.claude/rules/complete_data_queries.md`), and picks each surface's
     single most-viewed real path. Self-maintaining: as traffic shifts, the
     sweep follows it. `--urls` overrides for ad-hoc runs.
  2. Captures each surface at DESKTOP (1440x900 — the width where the overflow
     bug bites; 1920 hides it) and MOBILE (390x844 iPhone-class, real mobile UA
     + touch emulation, because ads serve differently by UA and the anchor unit
     is mobile-first).
  3. Records structural ad diagnostics per shot (overflow px, slot fill rates,
     reserved-but-empty boxes, the tallest near-white band in the image, anchor
     presence, CLS, plus masthead geometry — ads_above_h1_px / nav_top_px /
     h1_top_px / content_below_fold) into a JSON manifest, so a regression is a
     number and not a matter of opinion.

⚠️ TWO METRICS READ CLEAN OFF A BROKEN PAGE UNTIL 2026-08-10 — what changed.
Both under-reported for months, which is worth knowing before comparing a new
manifest against an old one:

  reserved-empty  Counted unfilled `ins` elements taller than 1px. ad_slot.html
                  hides an unfilled unit outright
                  (`ins.adsbygoogle[data-ad-status="unfilled"]{display:none}`),
                  so that rule could never fire: it read 0 on all 27 shots from
                  2026-07-27 to 2026-08-10, 20 of which had unfilled slots, while
                  the screenshots showed labelled 280-300px voids. The reserved
                  band belongs to the WRAPPER (`.vb-ad-slot`), so that is what is
                  measured now — `slots_reserved_empty` / `reserved_empty_px`,
                  plus `labelled_empty_*` for the subset showing an
                  "ADVERTISEMENT" caption over blank.
  over-wide       `overflow_px` is `scrollWidth - clientWidth`, which base.html's
                  `overflow-x: clip` pins to 0 by design — so the guard that
                  exists to catch the 2026-07 sitewide scrollbar cannot see a
                  recurrence. `over_wide_px` now flags it independently. It is
                  derived from `escaping_el_px` (the widest element NOT contained
                  by a scroller below body), NOT from `widest_el_px`, which
                  counts wide tables inside their own `overflow-x:auto` scrollers
                  — legitimate responsive behaviour that reads 462-839px against
                  a 390px mobile viewport. `escaping_el` names the culprit.

A bare reserved band is reported but NOT flagged: holding an empty hoisted box on
a no-fill is a deliberate trade (collapsing it yanks ~320px out from under the
page). `labelled_empty_px` is the flagged one, per ad_slot.html's own rule that a
label over blank space "is not a trade, it is a bug".

⚠️ THE BLANK-HOLE GUARD READ 0 THROUGH 1,236px OF WHITE UNTIL 2026-08-24.
`reserved_empty` / `labelled_empty` enumerated `.vb-ad-slot` — the two wrappers
we own — while the pages carry 5-10 `ins.adsbygoogle`, so every unit Google
placed itself was unmeasured. That is the second guard in this file to measure
the box we own instead of the one the reader sees, so the fix enumerates the
class rather than the instance:

  ad_units      every ad container, whoever made it: our `.vb-ad-slot`, Google's
                `.google-auto-placed`, and any bare `ins` in neither. The
                reserved/labelled-empty and above-H1 numbers derive from all of
                them.
  blank_run_px  the tallest near-white band in the CAPTURED IMAGE, bridging a
                caption thinner than BLANK_RUN_BRIDGE_PX (the "ADVERTISEMENT"
                floating in the middle of the 1,236px void). It reads pixels, so
                no markup contract can zero it. Flagged at one full viewport
                height, which leaves the deliberate 280-304px reserved band quiet.
  settled probe The guard metrics come from the probe taken AFTER the scroll
                pass — the state the screenshot shows. At first paint a
                below-fold unit has not activated: pos-1 on
                /when-is-the-next-visa-bulletin read unlabelled-and-not-yet-
                unfilled at y=4482, and /job-title/ reported its H1 at y=333
                against y≈660 in the render, because the auto banner above it
                lands late. `cls` and `overflow_px` stay first-paint properties
                and are still measured there.

⚠️ CLASS NAMES ARE A CROSS-REPO CONTRACT. `.vb-ad-slot`, `vb-ad-collapsed`,
`vb-ad-live` and `data-vb-hi` are defined in
visa_bulletin_platform/monetization/ad_slot.html and consumed by PROBE_JS here.
Nothing in this repo can import them, so a rename there silently zeroes the
per-unit metrics — twice now. `blank_run_px` is the backstop that survives it,
because a hole in the image is a hole whatever the class is called.
//tests:test_ad_guard_metrics pins our side; the other side has no guard.

Runs against the headed debug Chrome over CDP (:9222) — a real profile is what
makes Google serve ads; headless is both ad-hostile and fingerprint-walled (see
`~/.claude/rules/browser.md`).

⚠️ THE GEO GATE — why `--geo US` is the default, and what it does NOT prove.
The site withholds adsbygoogle.js ENTIRELY from EEA/UK/CH (the "EEA loader gate"
in overrides/ad_slot.html): it fetches `/cdn-cgi/trace`, reads `loc=XX`, and if
the country is in the EEA list it never injects the loader. This box is in
Berlin, so an un-overridden capture from here renders the **ad-free EEA view**
and reports slots=0 — a sweep that looks perfectly clean while measuring
literally nothing about the ad layer. That is a false all-clear, so:

  --geo US (default)  intercept ONLY `/cdn-cgi/trace` and answer `loc=US`, so
                      the page's own gate takes the non-EEA branch and the real
                      ad stack loads. Nothing else is faked.
  --geo EEA           no interception — captures what an EEA reader truly sees
                      (correctly ad-free). Use to audit the EEA experience.

HONEST LIMIT: ad requests still originate from this box's real German IP, so
FILL RATES HERE ARE NOT REPRESENTATIVE of what a US reader gets — do not read
`slots_filled` as a business metric or compare it to AdSense reporting. What
this sweep IS good for: layout, geometry, overflow, reserved-but-empty holes,
and visual appearance with the ad stack live — including the unfilled-slot
state, which is exactly the condition that caused the 2026-07 sitewide
scrollbar. Unfilled slots here are a FEATURE of the test, not a defect.

⚠️ THE `cls` FIELD IS A COARSE SMOKE SIGNAL — NOT the CLS number of record.
`scripts/measure_cls.py` is the authoritative tool: it throttles CPU 4x and
network to slow-4G, which is what pushes the ~9.1-9.6s Plotly chart hydration
INSIDE the measurement window. This sweep probes unthrottled at ~7.5s, so it
systematically MISSES that late chart shift. Do not compare a number from here
to one from there, and above all do not conclude "ads cause CLS" because an
ads-off run here reads ~0 — that is the probe window, not the ad stack (ticket
39862b8d-409f-811b measured the opposite with the proper tool: ads-off 0.2846
vs ads-on 0.229 on the homepage, i.e. ads make it no worse). Use `cls` here
only to notice a surface worth re-measuring properly. `cls_settled` is the same
observer read again after the scroll pass, because the first read closes before a
late Auto-ads injection lands — it caught none of the shift that moved the H1 of
/job-title/ from y=333 to y=637.

INPUTS  : GoatCounter token at ~/tokens/goatcounter.token (read by the MCP);
          debug Chrome on :9222 (`agent_infra/scripts/launch_chrome_cdp.sh`);
          ~/tokens/vb_smoke_header — the WAF exemption. WAF rule 5 managed-
          challenges /job-title/ and /employer/, and without this header those
          surfaces capture the "Verify you are human" interstitial instead of
          the site. Sent to our own origin ONLY (see `_add_smoke`): a page- or
          context-wide header would leak the secret to googlesyndication and
          every other third party the ad stack talks to. Missing file = a
          stderr warning, not a crash.
OUTPUTS : ~/.cache/vb_ad_screenshots/<YYYY-MM-DD>/<surface>__<device>.jpg
          + manifest.json (per-shot diagnostics) + a printed summary table.
          Exit 0 = captured; 2 = could not reach the debug Chrome / no surfaces.

USAGE :
  uv run scripts/ad_surface_screenshots.py                  # top 5, both devices, geo=US
  uv run scripts/ad_surface_screenshots.py --surfaces 3
  uv run scripts/ad_surface_screenshots.py --geo EEA        # audit the ad-free EEA view
  uv run scripts/ad_surface_screenshots.py --urls /=dashboard --urls /salaries/=salaries
  uv run scripts/ad_surface_screenshots.py --keep 4         # prune old run dirs
  uv run scripts/ad_surface_screenshots.py --prune-dry-run  # show what WOULD prune

SCHEDULED: weekly via `ad_surface_screenshots.timer` (systemd user unit) ->
  scripts/run_ad_screenshot_sweep.sh, which captures then injects an inspect
  prompt into the visa_bulletin relay so an agent actually LOOKS at the images.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

# httpx, playwright and the daily_checkup MCP machinery are imported INSIDE the
# functions that need them (as playwright always has been), so the pure metric
# derivation below can be imported by //tests:test_ad_guard_metrics without
# resolving this script's PEP-723 environment.

OUT_ROOT = Path.home() / ".cache" / "vb_ad_screenshots"
CDP_URL = "http://127.0.0.1:9222"
BASE = "https://visa-bulletin.us"

# The WAF exemption the release scripts already use (hosting/promote.sh,
# cutover.sh, graduate.sh). Rule 5 managed-challenges every /job-title/ and
# /employer/ path, and an emulated-mobile client does NOT clear it silently —
# on 2026-08-03 both profile surfaces captured the interactive "Verify you are
# human" page instead of the site, and every guard metric read clean off it.
# Same secret and mechanism as rule 3; see
# visa_bulletin_platform/hosting/cloudflare/waf.md.
SMOKE_HEADER_FILE = Path.home() / "tokens" / "vb_smoke_header"

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)

# device -> (width, height, deviceScaleFactor, mobile, ua_override|None)
DEVICES: dict[str, tuple[int, int, int, bool, str | None]] = {
    # 1440 not 1920: the unfilled-slot overflow only manifests below ~1913px, so
    # a 1920 capture reports a clean page that is visibly broken on a laptop.
    "desktop": (1440, 900, 1, False, None),
    "mobile": (390, 844, 3, True, IPHONE_UA),
}

# Surfaces that are pure redirects/asset routes — never worth a screenshot even
# if they rank by pageviews.
SKIP_SURFACES = {"donation_click", "static_meta", "api"}

# Ads settle asynchronously: a slot can sit reserved-but-empty for ~6s before it
# either fills or collapses. Capturing earlier photographs a transient state.
AD_SETTLE_MS = 7000

# Playwright's 30s default is not enough for a full-page shot of a tall mobile
# surface with the ad stack live: /job-title/ mobile timed out on 2026-08-24 and
# took its whole record with it, leaving zero mobile coverage on the heaviest
# page. Raised, and a failure now degrades to the viewport shot instead of
# discarding diagnostics that were already collected.
SCREENSHOT_TIMEOUT_MS = 150_000

# ── Blank-hole detection, measured on the IMAGE ──────────────────────────────
# A row this light at every pixel reads as white to a reader. Stable across the
# JPEG's own noise: 232/238/244 pick out the same runs to within ~5px on the
# 2026-08-24 shots.
BLANK_ROW_MIN_LUMA = 238
# A lone caption does not break a void. The 1,236px hole on
# /when-is-the-next-visa-bulletin is 448px of white, a 16px "ADVERTISEMENT", then
# 772px more — reporting that as two runs of 448 and 772 describes something the
# reader did not experience.
BLANK_RUN_BRIDGE_PX = 32
# Below this it is ordinary section spacing, not a hole.
BLANK_RUN_MIN_PX = 120
# Flagged only past a full screen of nothing. The deliberate reserved band is
# 280-304px (see derive_guard_metrics), so this cannot fire on it — a threshold
# that flagged the by-design case every week would train the reader to skip the
# column.
BLANK_RUN_FLAG_VIEWPORTS = 1.0

# Lazy content (the Plotly charts) is gated on IntersectionObserver, so it never
# initialises in a capture that never scrolls. These bound the scroll pass that
# wakes it: step by ~80% of a viewport, pausing briefly, then return to top.
LAZY_SCROLL_STEP_FRAC = 0.8
LAZY_SCROLL_PAUSE_MS = 250
LAZY_SCROLL_MAX_STEPS = 40
LAZY_RENDER_SETTLE_MS = 3000


def _scroll_through(page) -> None:
    """Scroll top→bottom→top so IntersectionObserver-gated content renders.

    Bounded by LAZY_SCROLL_MAX_STEPS so a page that grows as lazy units load
    (ads injecting below the fold) cannot loop forever. Best-effort: a failure
    here must not lose the screenshot, so it degrades to whatever was on screen.
    """
    try:
        step = int(page.evaluate("() => window.innerHeight") * LAZY_SCROLL_STEP_FRAC)
        for _ in range(LAZY_SCROLL_MAX_STEPS):
            # behavior:'instant' is load-bearing. base.html sets `scroll-behavior: smooth`
            # on <html>, so a plain scrollBy ANIMATES: window.scrollY is unchanged when read
            # in the same tick, the at-end test below saw before === after on the very first
            # step, and the loop broke immediately and returned to the top. So this pass has
            # never scrolled — which is why the charts needed the loadPlotly fallback below,
            # and why every desktop capture read zero ad units (both are
            # IntersectionObserver-gated) and reported the device dark. Measured on staging
            # 2026-08-18: smooth 0/0/0 per step against 632/1226/1997 once settled.
            at_end = page.evaluate(
                "(s) => { const before = window.scrollY;"
                " window.scrollBy({top: s, left: 0, behavior: 'instant'});"
                " return window.scrollY === before; }",
                step,
            )
            page.wait_for_timeout(LAZY_SCROLL_PAUSE_MS)
            if at_end:
                break
        page.evaluate("() => window.scrollTo({top: 0, left: 0, behavior: 'instant'})")
        # Belt and braces for the observer-gated charts: call the site's own loader
        # directly. Verified in the headed debug Chrome that a real user DOES get these
        # charts, so forcing them makes the capture more faithful, not less.
        page.evaluate(
            "() => { if (typeof window.loadPlotly === 'function') {"
            "   window.loadPlotly(() => document.dispatchEvent(new Event('plotlyLoaded')));"
            " } }"
        )
        # Let whatever we woke up actually draw before we photograph it.
        page.wait_for_timeout(LAZY_RENDER_SETTLE_MS)
    except Exception as e:
        print(f"  WARN: lazy-content scroll pass failed ({e}); capturing as-is",
              file=sys.stderr)


# ── Structural probe: what the reader actually got ──────────────────────────
# Runs in-page after ads settle. Every field is something that has previously
# broken, or that distinguishes "ad worked" from "ad left a hole".
PROBE_JS = r"""
() => {
  const de = document.documentElement;
  const slots = [...document.querySelectorAll('ins.adsbygoogle')];
  const box = (e) => { const r = e.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height)}; };
  const status = (e) => e.getAttribute('data-ad-status') || 'none';
  const filled = slots.filter(e => status(e) === 'filled');
  const unfilled = slots.filter(e => status(e) === 'unfilled');
  // A unit that did NOT fill but still reserves vertical space is a visible hole
  // — and the space is reserved by the CONTAINER, not the ins. ad_slot.html hides
  // an unfilled ins outright (display:none), so measuring the ins finds nothing
  // while the reader is looking at a 280-304px blank band.
  //
  // Enumerate every ad container, not only the two we own. Measuring
  // `.vb-ad-slot` alone left the six auto-placed units on a 2026-08-24 mobile
  // page unmeasured (8 `ins` against 2 wrappers) — including the ones inside a
  // 1,236px void that the guard scored 0. Three kinds, in the order they nest:
  // our wrapper, Google's auto-placed container, then any `ins` in neither.
  // Report raw facts and let Python derive the counts (derive_guard_metrics), so
  // the rule is unit-testable instead of only observable in a live browser.
  const sel = (e) => e.tagName.toLowerCase()
    + (e.id ? '#' + e.id : '')
    + ((e.className || '').toString().trim()
        ? '.' + (e.className || '').toString().trim().split(/\s+/).slice(0, 3).join('.') : '');
  const unit = (e, kind, inner) => {
    const r = e.getBoundingClientRect();
    const h = Math.round(r.height);
    return {
      kind,
      pos: e.getAttribute('data-ad-pos') || kind,
      sel: sel(e),
      // document coordinates, so the band can be matched against the image
      top_px: Math.round(r.top + window.scrollY),
      height_px: h,
      // Google's containers carry no class of ours, so "left no hole" is a
      // height question for them; both tests are cheap, keep both.
      collapsed: e.classList.contains('vb-ad-collapsed') || h <= 1,
      label_shown: e.classList.contains('vb-ad-live'),
      hoisted: e.hasAttribute('data-vb-hi'),
      filled_px: inner.filter(x => status(x) === 'filled')
                      .reduce((a, x) => a + box(x).h, 0),
      ins_px: inner.reduce((a, x) => a + box(x).h, 0),
    };
  };
  const ours = [...document.querySelectorAll('.vb-ad-slot')];
  const autos = [...document.querySelectorAll('.google-auto-placed')]
    .filter(a => !a.closest('.vb-ad-slot'));
  const owned = new Set();
  for (const w of [...ours, ...autos]) {
    for (const i of w.querySelectorAll('ins.adsbygoogle')) owned.add(i);
  }
  const adUnits = [
    ...ours.map(w => unit(w, 'slot', [...w.querySelectorAll('ins.adsbygoogle')])),
    ...autos.map(w => unit(w, 'auto', [...w.querySelectorAll('ins.adsbygoogle')])),
    ...slots.filter(i => !owned.has(i)).map(i => unit(i, 'ins', [i])),
  ];
  const iframes = [...document.querySelectorAll('iframe')];
  const adIframes = iframes.filter(f => /^(aswift|google_ads|ad_iframe)/.test(f.id || '') ||
                                        /doubleclick|googlesyndication/.test(f.src || ''));
  // Anchor/sticky units park themselves in a position:fixed host.
  const anchor = [...document.querySelectorAll('ins.adsbygoogle, div')].some(e => {
    const cs = getComputedStyle(e);
    return cs.position === 'fixed' && (e.className || '').toString().includes('adsbygoogle');
  });
  // Google Auto-ads can inject an in-flow unit above the H1 — inflating the
  // masthead and shoving all real content off the first screen. Invisible to
  // every metric above (it is a FILLED unit, reserves no empty box, causes no
  // overflow), so it needs its own geometry number.
  // Found 2026-07-20 INSIDE the hero: a filled 390x390 div.google-auto-placed
  // in .hero-section put nav at y=598 and the H1 at y=755 in an 844px viewport.
  // The rule was written as `.hero-section` and so missed the same defect one
  // element over: on 2026-08-24 a ~285px banner sat between nav and H1 on
  // /job-title/ and read hero_ad_injected 0. What harms the reader is an ad
  // ABOVE THE H1, wherever it is parked, so that is what Python counts now
  // (derive_guard_metrics, from ad_units + h1_doc_top_px).
  const hero = document.querySelector('.hero-section');
  const navEl = document.querySelector('nav');
  const h1El = document.querySelector('h1');
  const topOf = (e) => e ? Math.round(e.getBoundingClientRect().top) : null;
  return {
    hero_h: hero ? Math.round(hero.getBoundingClientRect().height) : null,
    nav_top_px: topOf(navEl),
    h1_top_px: topOf(h1El),
    // document coordinates, to compare against each ad unit's top_px
    h1_doc_top_px: h1El
      ? Math.round(h1El.getBoundingClientRect().top + window.scrollY) : null,
    // Where OUR pos-1 unit sits, and whether ad_slot.html hoisted it at parse
    // (data-vb-hi = the mobile viewability lift, or the hero displacement that
    // occupies the above-fold band Auto-ads was taking on /predictions +
    // /employer/). Without these two numbers "the manual unit moved" is an
    // eyeball; with them a displacement run is a diff.
    ad1_top_px: topOf(document.querySelector('.vb-ad-slot[data-ad-pos="1"]')),
    ad1_hoisted: !!document.querySelector('.vb-ad-slot[data-ad-pos="1"][data-vb-hi]'),
    // the headline number: does ANY real content start above the fold?
    content_below_fold: (() => {
      const t = topOf(h1El);
      return t === null ? null : t >= innerHeight;
    })(),
    overflow_px: de.scrollWidth - de.clientWidth,
    html_overflow_x: getComputedStyle(de).overflowX,
    body_overflow_x: getComputedStyle(document.body).overflowX,
    doc_height: de.scrollHeight,
    slots_total: slots.length,
    slots_filled: filled.length,
    slots_unfilled: unfilled.length,
    ad_units: adUnits,
    ad_iframes: adIframes.length,
    anchor_present: anchor,
    viewport_width: de.clientWidth,
    // Kept unchanged so the metric stays comparable with earlier manifests, but
    // it is NOT the overflow signal: it counts scroll-contained elements too.
    widest_el_px: Math.max(0, ...[...document.querySelectorAll('body *')].map(e => {
      const r = e.getBoundingClientRect(); return Math.round(r.right);
    })),
    // The widest element that ESCAPES to the page — nothing between it and body
    // clips or scrolls it. This is the one that gives the viewport a horizontal
    // scrollbar (or would, without base.html's overflow-x:clip, which is exactly
    // why overflow_px cannot be trusted to catch a recurrence). A wide table
    // inside its own overflow-x:auto scroller is correct and must not count.
    ...(() => {
      let worst = 0, desc = null;
      for (const e of document.querySelectorAll('body *')) {
        const r = e.getBoundingClientRect();
        const right = Math.round(r.right);
        if (right <= de.clientWidth || right <= worst) continue;
        let contained = false;
        for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
          const ox = getComputedStyle(a).overflowX;
          if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') {
            if (Math.round(a.getBoundingClientRect().right) <= de.clientWidth) {
              contained = true; break;
            }
          }
        }
        if (contained) continue;
        worst = right;
        desc = e.tagName.toLowerCase()
             + (e.id ? '#' + e.id : '')
             + ((e.className || '').toString().trim()
                 ? '.' + (e.className || '').toString().trim().split(/\s+/).join('.')
                 : '');
      }
      // Attribution, not just a number: "something is 1913px wide" is not
      // actionable, "div.google-auto-placed is" is.
      return {escaping_el_px: worst, escaping_el: desc};
    })(),
    title: document.title,
  };
}
"""

CLS_JS = r"""
() => new Promise((res) => {
  let cls = 0;
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) if (!e.hadRecentInput) cls += e.value;
    }).observe({type: 'layout-shift', buffered: true});
  } catch (e) { return res(null); }
  setTimeout(() => res(Math.round(cls * 1000) / 1000), 500);
})
"""


class AdUnitFacts(NamedTuple):
    """One ad container — ours or Google's — as measured in-page.

    The container, not the `ins`, is what reserves the visible band, so it is
    what the reader sees when a unit does not fill.
    """

    pos: str
    kind: str            # slot = ours | auto = .google-auto-placed | ins = bare
    height_px: int       # the container's rendered height
    collapsed: bool      # left no hole: .vb-ad-collapsed, or no box at all
    label_shown: bool    # .vb-ad-live, i.e. the "ADVERTISEMENT" caption is visible
    hoisted: bool        # data-vb-hi — keeps its band on a no-fill, by design
    filled_px: int       # summed height of FILLED ins inside this container
    ins_px: int          # summed height of ALL ins inside (0 when CSS hides them)
    top_px: int          # document coordinates, to match against the image
    sel: str             # tag#id.class, so a finding names its culprit

    @classmethod
    def from_probe(cls, raw: dict) -> AdUnitFacts:
        return cls(
            pos=str(raw.get("pos") or "?"),
            kind=str(raw.get("kind") or "?"),
            height_px=int(raw.get("height_px") or 0),
            collapsed=bool(raw.get("collapsed")),
            label_shown=bool(raw.get("label_shown")),
            hoisted=bool(raw.get("hoisted")),
            filled_px=int(raw.get("filled_px") or 0),
            ins_px=int(raw.get("ins_px") or 0),
            top_px=int(raw.get("top_px") or 0),
            sel=str(raw.get("sel") or ""),
        )


class GuardMetrics(NamedTuple):
    """The derived numbers a human compares against the screenshot."""

    slots_reserved_empty: int
    reserved_empty_px: int
    labelled_empty_slots: int
    labelled_empty_px: int
    over_wide_px: int
    ads_above_h1: int
    ads_above_h1_px: int


def derive_guard_metrics(units: list[AdUnitFacts], escaping_el_px: int,
                         viewport_width: int,
                         h1_doc_top_px: int | None = None) -> GuardMetrics:
    """Turn the in-page facts into the numbers a human checks the screenshot against.

    Measured on the CONTAINER, never the `ins`. ad_slot.html hides an unfilled
    unit (`ins.adsbygoogle[data-ad-status="unfilled"]{display:none}`), so the
    `ins` reports 0px while the wrapper still holds its 280px (304px hoisted)
    band — which is the blank the reader sees. Counting the `ins` scored every
    weekly run 0 for reserved-empty, 27 shots in a row, 20 of which had unfilled
    slots.

    The containers are ALL of them, not just `.vb-ad-slot`. Counting only ours
    was the same error one level up: the pages carry 5-10 `ins.adsbygoogle`
    against 2 wrappers, so every unit Google placed itself went unmeasured.

    A bare reserved band and a LABELLED one are counted separately on purpose.
    Holding an empty band above the fold is a deliberate trade (collapsing it
    yanks ~320px out from under the page — the shift the hoist exists to remove),
    but ad_slot.html's own rule is that the caption must go with the creative
    that never came: "a label over blank space is not a trade, it is a bug." So
    `labelled_empty_px` is the number that means something is wrong, while
    `reserved_empty_px` is the number that has to agree with the screenshot.

    `ads_above_h1` counts what an Auto-ads placement does to the first screen: a
    filled unit above the headline reserves no empty box and causes no overflow,
    so it registers nowhere else while pushing every word of real content down.
    """
    empty = [u for u in units if not u.collapsed and u.height_px > 1 and u.filled_px <= 1]
    labelled = [u for u in empty if u.label_shown]
    above = ([u for u in units
              if not u.collapsed and u.height_px > 1 and u.top_px < h1_doc_top_px]
             if h1_doc_top_px is not None else [])
    return GuardMetrics(
        slots_reserved_empty=len(empty),
        reserved_empty_px=sum(u.height_px for u in empty),
        labelled_empty_slots=len(labelled),
        labelled_empty_px=sum(u.height_px for u in labelled),
        ads_above_h1=len(above),
        ads_above_h1_px=sum(u.height_px for u in above),
        # NOT `widest_el_px - viewport_width`: that counts a wide table sitting
        # inside its own overflow-x:auto scroller, which is correct responsive
        # behaviour (real mobile runs read 837/839/821/462px against a 390
        # viewport). `escaping_el_px` is the widest element NOT contained by a
        # scroller below body — the one that actually reaches the page edge, and
        # the shape that caused the 2026-07 sitewide scrollbar.
        over_wide_px=max(0, escaping_el_px - viewport_width),
    )


class BlankRun(NamedTuple):
    """A band of the rendered page carrying nothing the reader can see."""

    top_px: int
    px: int


def derive_blank_runs(blank_rows: list[bool],
                      bridge_px: int = BLANK_RUN_BRIDGE_PX,
                      min_px: int = BLANK_RUN_MIN_PX) -> list[BlankRun]:
    """Near-white bands of the captured image, tallest first.

    This is the one hole-detector with no markup contract behind it. Every
    DOM-side rule in this file has now been wrong twice in the same direction —
    it measured a container we own and reported 0 while the reader looked at a
    void — because the void is made by whatever Google put there, and next
    quarter that will be a shape nobody has named. A row of pixels is a row of
    pixels.

    `bridge_px` joins two bands separated by something thinner than a caption.
    The 2026-08-24 hole on /when-is-the-next-visa-bulletin is 448px of white, a
    16px "ADVERTISEMENT", then 772px more; calling that two runs of 448 and 772
    describes something nobody experienced, and both fall under the flag.

    Both neighbours must already be holes in their own right, because bridging
    is transitive and a bulleted list is a chain of ~14px blanks between ~10px
    text rows: bridging on the gap alone swallowed a whole link list and read
    1,572px of "white" on a page whose real void was 1,236px. Requiring
    `min_px` on each side leaves ordinary line spacing where it belongs.
    """
    runs: list[BlankRun] = []
    start: int | None = None
    for y, blank in enumerate(blank_rows):
        if blank and start is None:
            start = y
        elif not blank and start is not None:
            runs.append(BlankRun(start, y - start))
            start = None
    if start is not None:
        runs.append(BlankRun(start, len(blank_rows) - start))

    bridged: list[BlankRun] = []
    for run in runs:
        if bridged:
            prev = bridged[-1]
            if (prev.px >= min_px and run.px >= min_px
                    and run.top_px - (prev.top_px + prev.px) <= bridge_px):
                bridged[-1] = BlankRun(prev.top_px, run.top_px + run.px - prev.top_px)
                continue
        bridged.append(run)
    return sorted((r for r in bridged if r.px >= min_px), key=lambda r: -r.px)


def blank_rows_from_image(path: Path, luma_floor: int = BLANK_ROW_MIN_LUMA) -> list[bool]:
    """One bool per image row: is every pixel in it at least this light?

    Pillow is imported here, not at module scope, so the pure derivations above
    stay importable by //tests:test_ad_guard_metrics without this script's
    PEP-723 environment.
    """
    from PIL import Image

    with Image.open(path) as im:
        grey = im.convert("L")
        width, height = grey.size
        # tobytes(), not getdata(): one row is then a bytes slice and `min` runs
        # in C, which is what keeps a 1425x9550 desktop shot at ~0.2s.
        pixels = grey.tobytes()
    return [min(pixels[y * width:(y + 1) * width]) >= luma_floor for y in range(height)]


def blackout_devices(shots: list[dict]) -> list[str]:
    """Devices where every captured shot rendered ZERO ad slots.

    The all-shots-zero gate in main() only fires when the WHOLE run is empty, so
    it cannot see one device class going dark: on 2026-08-10 all five desktop
    shots captured the real site (right titles, `captured: true`) with 0 slots
    and 0 ad iframes, while mobile rendered 4-9 — and the run reported clean.
    That is gap 4's shape again (a row of zeros reading as a healthy surface),
    one device wide, so it gets a number rather than another manual noticing.

    Per-device and not per-surface on purpose: a single surface can legitimately
    carry no slots (ad_slot.html excludes /about, /contact, /faq, /privacy,
    /terms), but an entire device class rendering none across every surface is
    the ad stack failing to load.

    Counts the POST-SCROLL probe, falling back to first paint on a run that has none.
    Both units are IntersectionObserver-gated, so a desktop first paint reads zero
    wherever no hoist lifts pos-1 above the fold — dark to this gate, and serving ads
    to every reader who scrolls. What it is meant to catch is a device that renders
    nothing even once the whole page has been through the viewport.
    """
    def slots(shot: dict) -> int:
        got = shot.get("slots_total_scrolled")
        return shot.get("slots_total", 0) if got is None else got

    by_device: dict[str, list[dict]] = {}
    for s in shots:
        if s.get("error") or s.get("captured") is False:
            continue
        by_device.setdefault(s.get("device", "?"), []).append(s)
    return sorted(dev for dev, got in by_device.items()
                  if got and all(slots(g) == 0 for g in got))


def _gc_machinery():
    """The daily_checkup MCP's GC helpers — single source of truth for the export
    pull, the row filtering and the surface taxonomy. Imported lazily so this
    module stays importable (and testable) outside its PEP-723 env."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
    import daily_checkup_server as dcs
    return dcs


def _surface_label(surface: str) -> str:
    return _gc_machinery().SURFACE_LABELS.get(surface, surface)


async def _load_csv() -> Path | None:
    import httpx
    dcs = _gc_machinery()
    async with httpx.AsyncClient() as client:
        return await dcs._gc_export_full_csv(client)


def _derive_top_surfaces(n: int) -> list[tuple[str, str]]:
    """[(surface, url_path)] for the top-n surfaces by 7d pageviews.

    Full export coverage — a top-100 query would silently drop the profile long
    tail and mis-rank the surfaces this sweep is supposed to watch.
    """
    dcs = _gc_machinery()
    csv_path = asyncio.run(_load_csv())
    if not csv_path or not csv_path.exists():
        return []
    cutoff_ts = dcs._gc_export_max_ts(csv_path)
    cutoff = cutoff_ts.date() if cutoff_ts else date.today()
    anchor = cutoff - timedelta(days=1)  # last COMPLETE day (today is partial)
    start, end = anchor - timedelta(days=6), anchor
    counts = dcs._aggregate_csv_path_counts(csv_path, [("this_7d", start, end)])["this_7d"]
    by_surface: dict[str, dict[str, int]] = {}
    for path, hits in counts.items():
        surf = dcs._bucket_path(path)
        if surf in SKIP_SURFACES:
            continue
        by_surface.setdefault(surf, {})[path] = hits
    ranked = sorted(by_surface.items(), key=lambda kv: -sum(kv[1].values()))
    out: list[tuple[str, str]] = []
    for surf, paths in ranked[:n]:
        # Representative page = the single most-viewed real path in the surface.
        top_path = max(paths.items(), key=lambda kv: kv[1])[0]
        out.append((surf, top_path))
    return out


def _runs_to_prune(run_dirs: list[Path], keep: int) -> list[Path]:
    """Pure + testable: which dated run dirs fall outside the keep-N budget.

    Newest `keep` are retained. Never returns anything when keep <= 0 (a
    misconfigured keep must not wipe the archive — large_file_hygiene safety
    net), and only ever considers YYYY-MM-DD-shaped dirs.
    """
    if keep <= 0:
        return []
    dated = []
    for d in run_dirs:
        try:
            datetime.strptime(d.name, "%Y-%m-%d")
        except ValueError:
            continue  # never prune a dir we don't recognise
        dated.append(d)
    dated.sort(key=lambda p: p.name, reverse=True)
    return dated[keep:]


def _prune(keep: int, dry_run: bool) -> list[Path]:
    if not OUT_ROOT.exists():
        return []
    victims = _runs_to_prune([p for p in OUT_ROOT.iterdir() if p.is_dir()], keep)
    for v in victims:
        if dry_run:
            print(f"  [dry-run] would remove {v}")
        else:
            shutil.rmtree(v, ignore_errors=True)
            print(f"  pruned {v}")
    return victims


# A capture that fetched a WAF interstitial instead of the site must fail
# LOUDLY. Every guard metric reads perfect off a page carrying none of our
# markup — the 2026-08-03 run logged both challenged profile surfaces as
# cls 0 / overflow_px 0 / slots 0, i.e. a row of zeros indistinguishable from a
# clean surface. Under-reporting a defect is bad; fabricating a pass is worse.
INTEGRITY_JS = """() => {
  const body = document.body ? document.body.innerText.slice(0, 400) : '';
  return {
    title: document.title,
    ours: !!document.querySelector('.hero-section, a[href*="/predictions"]'),
    challenged: /just a moment|verify you are human|attention required|cf-browser-verification/i
        .test(document.title + ' ' + body),
  };
}"""


def _smoke_secret() -> str | None:
    """The x-vb-smoke value, or None if the token file is absent.

    Never printed or returned to a caller that logs it (env_and_security.md) —
    it goes straight into a request header for our own origin.
    """
    try:
        return SMOKE_HEADER_FILE.read_text().strip() or None
    except OSError:
        return None


_NO_BLANK_RUN = {"blank_run_px": 0, "blank_run_top_px": None, "blank_run_viewports": 0,
                 "blank_run_ads": [], "blank_runs": [], "blank_run_flagged": False}


def _blank_run_facts(image: Path, settled: dict, viewport_h: int) -> dict:
    """Measure the voids in the shot we just took, and name what is in them.

    Attribution comes from the DOM (which ad container overlaps the band), but
    detection never does — that is the whole point. The full-page shot is written
    in CSS pixels, so an image row and a document row are the same y.
    """
    if not image.exists():
        return {**_NO_BLANK_RUN, "blank_scan_error": "no full-page image"}
    try:
        runs = derive_blank_runs(blank_rows_from_image(image))
    except Exception as e:  # a scan failure must not cost the shot its metrics
        return {**_NO_BLANK_RUN, "blank_scan_error": str(e)}
    if not runs:
        return dict(_NO_BLANK_RUN)
    worst = runs[0]
    units = [AdUnitFacts.from_probe(u) for u in settled.get("ad_units", [])]
    inside = [u.sel or u.kind for u in units
              if u.top_px < worst.top_px + worst.px and u.top_px + u.height_px > worst.top_px]
    return {
        "blank_run_px": worst.px,
        "blank_run_top_px": worst.top_px,
        "blank_run_viewports": round(worst.px / viewport_h, 2) if viewport_h else None,
        "blank_run_ads": inside,
        "blank_runs": [[r.top_px, r.px] for r in runs[:3]],
        "blank_run_flagged": bool(viewport_h) and worst.px >= viewport_h * BLANK_RUN_FLAG_VIEWPORTS,
    }


def _capture(surfaces: list[tuple[str, str]], out_dir: Path, devices: list[str],
             geo: str, base: str = BASE) -> list[dict]:
    from playwright.sync_api import sync_playwright

    smoke = _smoke_secret()
    if smoke is None:
        print(f"WARNING: {SMOKE_HEADER_FILE} missing — /job-title/ and /employer/ "
              "will hit the WAF challenge and capture the interstitial, not the site.",
              file=sys.stderr)

    def _add_smoke(route):
        """Attach the WAF exemption to OUR OWN origin only.

        Scoped deliberately: a page-wide or context-wide extra header would ship
        the secret to googlesyndication and every other third party the ad stack
        talks to. Registered BEFORE _fake_trace so the more specific trace route
        (registered later) still wins for /cdn-cgi/trace — Playwright uses the
        last matching handler.
        """
        route.continue_(headers={**route.request.headers, "x-vb-smoke": smoke})

    def _fake_trace(route):
        """Answer ONLY /cdn-cgi/trace with a non-EEA loc, so the page's own EEA
        gate takes the ads-on branch. Nothing else about the request is faked."""
        route.fulfill(status=200, content_type="text/plain",
                      body=f"fl=0f0\nh=visa-bulletin.us\nip=0.0.0.0\nloc={geo}\n")

    shots: list[dict] = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"ERROR: cannot reach debug Chrome at {CDP_URL}: {e}", file=sys.stderr)
            print("       start it: bash ~/cursor_projects/agent_infra/scripts/launch_chrome_cdp.sh",
                  file=sys.stderr)
            raise SystemExit(2) from e
        ctx = browser.contexts[0]
        for surf, path in surfaces:
            for dev in devices:
                w, h, dsf, mobile, ua = DEVICES[dev]
                page = ctx.new_page()
                try:
                    cdp = ctx.new_cdp_session(page)
                    cdp.send("Emulation.setDeviceMetricsOverride",
                             {"width": w, "height": h, "deviceScaleFactor": dsf, "mobile": mobile})
                    if ua:
                        cdp.send("Emulation.setUserAgentOverride", {"userAgent": ua})
                    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
                    # Order matters: broad smoke-header route first, specific
                    # trace route second, so the later trace handler wins.
                    if smoke:
                        page.route(f"{base}/**", _add_smoke)
                    if geo != "EEA":
                        page.route("**/cdn-cgi/trace", _fake_trace)
                    url = f"{base}{path}"
                    # NOT networkidle: with the ad stack live, Google keeps polling and
                    # the network never goes idle — mobile captures timed out at 90s.
                    # `load` + an explicit settle is both faster and deterministic.
                    page.goto(url, wait_until="load", timeout=90_000)
                    page.wait_for_timeout(AD_SETTLE_MS)  # let slots fill or collapse
                    integrity = page.evaluate(INTEGRITY_JS)
                    if integrity["challenged"] or not integrity["ours"]:
                        # Keep the image as evidence, but never emit guard
                        # metrics for a page that is not ours — a row of zeros
                        # here reads as a clean surface (see INTEGRITY_JS).
                        fn = out_dir / f"{surf}__{dev}.jpg"
                        page.screenshot(path=str(fn), full_page=False,
                                        type="jpeg", quality=80)
                        why = ("WAF challenge interstitial"
                               if integrity["challenged"] else "no first-party markup")
                        shots.append({
                            "surface": surf, "label": _surface_label(surf),
                            "url": url, "device": dev, "viewport": f"{w}x{h}",
                            "file": str(fn), "captured": False,
                            "capture_error": f"{why} (title={integrity['title']!r})",
                        })
                        print(f"  {surf:20s} {dev:7s} ⚠ NOT CAPTURED — {why}",
                              file=sys.stderr)
                        continue
                    try:
                        cls = page.evaluate(CLS_JS)
                    except Exception:
                        cls = None
                    diag = page.evaluate(PROBE_JS)
                    # Trigger IntersectionObserver-gated lazy content before the
                    # full-page shot. The Plotly charts on / and the country
                    # landings only inject their CDN script once #chart-container
                    # intersects; a never-scrolled capture leaves every one of
                    # them showing "Loading chart..." and reads as a broken
                    # widget on inspection. Verified against the headed debug
                    # Chrome: with a real scroll the observer fires, Plotly
                    # loads and .js-plotly-plot renders, so the spinner was the
                    # capture's artifact, not a production defect. Runs AFTER
                    # the CLS + probe evaluate() calls so their numbers keep
                    # measuring the unscrolled first paint.
                    _scroll_through(page)
                    # Second probe, AFTER the scroll. Both slots load lazily on an
                    # IntersectionObserver, so on desktop — where nothing hoists pos-1 above the
                    # fold — the first-paint probe legitimately reads zero ad slots and a reader
                    # who scrolls still gets both. Judging presence on the first-paint numbers
                    # alone reported the whole desktop class dark for two Mondays while desktop
                    # was serving ads all week (2026-08-06..17). The first-paint numbers stay the
                    # manifest's primary ones — CLS and overflow are first-paint properties and
                    # must not be measured after a scroll — and the ad-presence gate reads these.
                    try:
                        diag_scrolled = page.evaluate(PROBE_JS)
                    except Exception:
                        diag_scrolled = {}
                    # CLS again, after everything has landed. The observer is
                    # `buffered: true`, so this replays from load and can only be
                    # >= the first-paint reading — but the first reading closes
                    # ~7s in, before the Auto-ads banner that put the H1 of
                    # /job-title/ at y=637 instead of y=333 ever arrives, and it
                    # reported cls 0 for that page. Both numbers are kept: `cls`
                    # stays the comparable first-paint series, `cls_settled` says
                    # whether a late injection moved the page.
                    try:
                        cls_settled = page.evaluate(CLS_JS)
                    except Exception:
                        cls_settled = None
                    fn = out_dir / f"{surf}__{dev}.jpg"
                    # A timeout here used to raise, and the record went with it —
                    # /job-title/ mobile, the heaviest surface, captured nothing
                    # at all on 2026-08-24 while its diagnostics were already in
                    # hand. Keep them: a shot we could not take is a gap to
                    # report, not a reason to discard a measurement.
                    shot_error: str | None = None
                    try:
                        page.screenshot(path=str(fn), full_page=True, type="jpeg",
                                        quality=80, timeout=SCREENSHOT_TIMEOUT_MS)
                    except Exception as e:
                        shot_error = f"full-page screenshot failed: {e}"
                        print(f"  {surf:20s} {dev:7s} ⚠ {shot_error}", file=sys.stderr)
                    # A full-page shot stitches the scrolled page but leaves position:fixed
                    # elements at their VIEWPORT offset — so the bottom anchor ad appears
                    # frozen mid-page and reads as "an ad covering the content". It is an
                    # artifact, not a bug. The viewport shot shows where fixed units really
                    # sit; compare the two before reporting any overlap.
                    fold = out_dir / f"{surf}__{dev}__viewport.jpg"
                    try:
                        page.screenshot(path=str(fold), full_page=False, type="jpeg",
                                        quality=80, timeout=SCREENSHOT_TIMEOUT_MS)
                    except Exception as e:
                        shot_error = ((shot_error + "; ") if shot_error else "") + \
                            f"viewport screenshot failed: {e}"
                    # The SETTLED probe, not first paint, is what the screenshot
                    # shows: a below-fold unit has not activated at first paint,
                    # so its label, its no-fill and any late auto placement above
                    # the H1 are all invisible there. `cls` and `overflow_px`
                    # stay first-paint properties and keep their own numbers.
                    settled = diag_scrolled or diag
                    metrics = derive_guard_metrics(
                        [AdUnitFacts.from_probe(u) for u in settled.get("ad_units", [])],
                        escaping_el_px=settled.get("escaping_el_px",
                                                   diag.get("escaping_el_px", 0)),
                        viewport_width=settled.get("viewport_width", w),
                        h1_doc_top_px=settled.get("h1_doc_top_px"),
                    )
                    blank = _blank_run_facts(fn, settled, viewport_h=h)
                    rec = {
                        "surface": surf,
                        "label": _surface_label(surf),
                        "url": url,
                        "device": dev,
                        "viewport": f"{w}x{h}",
                        "file": str(fn),
                        "size_kb": round(fn.stat().st_size / 1024) if fn.exists() else 0,
                        "captured": True,
                        "screenshot_error": shot_error,
                        "cls": cls,
                        "cls_settled": cls_settled,
                        **diag,
                        # Every flagged number is derived from the settled probe,
                        # so the manifest carries the settled copy of the fields
                        # behind them — a reader comparing a flag against a
                        # pre-activation geometry would be reading the wrong page.
                        "ad_units": settled.get("ad_units", []),
                        "hero_h": settled.get("hero_h", diag.get("hero_h")),
                        "h1_top_px": settled.get("h1_top_px", diag.get("h1_top_px")),
                        "h1_top_px_first_paint": diag.get("h1_top_px"),
                        "content_below_fold": settled.get(
                            "content_below_fold", diag.get("content_below_fold")),
                        "escaping_el": settled.get("escaping_el", diag.get("escaping_el")),
                        "escaping_el_px": settled.get(
                            "escaping_el_px", diag.get("escaping_el_px")),
                        **metrics._asdict(),
                        **blank,
                        "slots_total_scrolled": diag_scrolled.get("slots_total"),
                        "slots_filled_scrolled": diag_scrolled.get("slots_filled"),
                    }
                    shots.append(rec)
                    flag = "" if rec["overflow_px"] <= 0 else f"  ⚠ OVERFLOW {rec['overflow_px']}px"
                    if metrics.over_wide_px > 0:
                        flag += (f"  ⚠ OVER-WIDE {metrics.over_wide_px}px "
                                 f"({rec.get('escaping_el')} reaches "
                                 f"{rec.get('escaping_el_px')}px)")
                    if metrics.labelled_empty_px > 0:
                        flag += (f"  ⚠ LABELLED BLANK {metrics.labelled_empty_px}px "
                                 f"({metrics.labelled_empty_slots} slot(s))")
                    if rec.get("blank_run_flagged"):
                        flag += (f"  ⚠ BLANK BAND {rec['blank_run_px']}px "
                                 f"({rec.get('blank_run_viewports')} screens) at "
                                 f"y={rec.get('blank_run_top_px')}"
                                 + (f" over {', '.join(rec['blank_run_ads'])}"
                                    if rec.get("blank_run_ads") else ""))
                    if metrics.ads_above_h1_px > 0:
                        flag += (f"  ⚠ AD ABOVE H1 {metrics.ads_above_h1_px}px "
                                 f"({metrics.ads_above_h1} unit(s), "
                                 f"h1 at y={rec.get('h1_top_px')})")
                    if shot_error:
                        flag += "  ⚠ SCREENSHOT INCOMPLETE"
                    if rec.get("content_below_fold"):
                        flag += "  ⚠ H1 BELOW FOLD"
                    if rec.get("anchor_present"):
                        # Anchor ads were turned OFF site-wide on 2026-08-03 and have
                        # read false on all 17 shots since (9/10 were true before), so
                        # a true here now means the unit came back, not a flake.
                        flag += "  ⚠ ANCHOR PRESENT (anchor ads are off site-wide)"
                    print(f"  {surf:20s} {dev:7s} slots={rec['slots_total']}"
                          f"->{rec['slots_total_scrolled']} "
                          f"filled={rec['slots_filled']}"
                          f"->{rec['slots_filled_scrolled']} "
                          f"empty-reserved={metrics.slots_reserved_empty}"
                          f"/{metrics.reserved_empty_px}px "
                          f"cls={cls}->{cls_settled}{flag}")
                except Exception as e:  # one bad surface must not kill the sweep
                    print(f"  {surf:20s} {dev:7s} FAILED: {e}", file=sys.stderr)
                    shots.append({"surface": surf, "device": dev, "url": f"{base}{path}",
                                  "error": str(e)})
                finally:
                    page.close()  # campsite: never leak tabs into the shared debug Chrome
    return shots


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surfaces", type=int, default=5, help="top N surfaces by traffic (default 5)")
    ap.add_argument("--urls", action="append", default=[],
                    help="override as PATH=label, repeatable (skips GC derivation)")
    ap.add_argument("--devices", default="desktop,mobile")
    ap.add_argument("--geo", default="US",
                    help="country the page's EEA gate should see: a 2-letter code to load the "
                         "ad stack (default US), or 'EEA' to capture the real ad-free EEA view")
    ap.add_argument("--base", default=BASE,
                    help="origin to capture (default prod). Point at the staging stack to "
                         "validate an ad-layer change before it reaches prod — note staging "
                         "never receives an Auto-ads placement, so it proves the manual "
                         "layer's geometry, not what Google does with it.")
    ap.add_argument("--out", default=None, help="output dir (default ~/.cache/vb_ad_screenshots/<date>)")
    ap.add_argument("--keep", type=int, default=4, help="keep N newest run dirs (default 4; 0=never prune)")
    ap.add_argument("--prune-dry-run", action="store_true", help="show prune victims, capture nothing")
    args = ap.parse_args()

    if args.prune_dry_run:
        print(f"Prune dry-run (keep={args.keep}) under {OUT_ROOT}:")
        if not _prune(args.keep, dry_run=True):
            print("  nothing to prune")
        return 0

    devices = [d.strip() for d in args.devices.split(",") if d.strip() in DEVICES]
    if not devices:
        print(f"ERROR: --devices must name some of {list(DEVICES)}", file=sys.stderr)
        return 2

    if args.urls:
        surfaces = []
        for spec in args.urls:
            path, _, label = spec.partition("=")
            surfaces.append((label or _gc_machinery()._bucket_path(path), path))
    else:
        print("Deriving top surfaces from the full GoatCounter export (100% coverage)...")
        surfaces = _derive_top_surfaces(args.surfaces)
    if not surfaces:
        print("ERROR: no surfaces resolved (GC export unavailable?)", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else OUT_ROOT / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = "ad-free EEA view" if args.geo == "EEA" else f"ad stack on (gate sees loc={args.geo})"
    print(f"\nCapturing {len(surfaces)} surfaces x {len(devices)} devices -> {out_dir}")
    print(f"Geo mode: {mode}")
    for surf, path in surfaces:
        print(f"  - {surf:20s} {path}")
    print()

    shots = _capture(surfaces, out_dir, devices, args.geo, args.base)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base": args.base,
        "geo": args.geo,
        "geo_note": (
            "Ad requests originate from this box's real (German) IP, so fill rates are NOT "
            "representative of US fill and must not be read as a business metric. Layout, "
            "overflow, reserved-empty holes and CLS ARE meaningful."
        ),
        "surfaces": [{"surface": s, "path": p} for s, p in surfaces],
        "shots": shots,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    ok_shots = [s for s in shots if not s.get("error") and s.get("captured") is not False]
    uncaptured = [s for s in shots if s.get("captured") is False]
    # A bare reserved band is a deliberate trade (see derive_guard_metrics), so it
    # is reported but not flagged; a LABELLED blank and an escaping element are
    # defects. Flagging the deliberate case would fire on every employer /
    # predictions run and train the reader to ignore the whole column.
    issues = [s for s in shots if s.get("error") or s.get("overflow_px", 0) > 0
              or s.get("over_wide_px", 0) > 0
              or s.get("labelled_empty_px", 0) > 0
              or s.get("blank_run_flagged")
              or s.get("anchor_present")
              or s.get("ads_above_h1_px", 0) > 0 or s.get("content_below_fold")
              or s.get("screenshot_error")
              or s.get("captured") is False]
    print(f"\nWrote {len(ok_shots)} screenshots + manifest.json")
    print(f"Flagged {len(issues)} shot(s) with an error / overflow / over-wide element / "
          f"labelled blank / blank band / anchor unit / ad above the H1 / H1 below the "
          f"fold / incomplete or missing capture.")
    blank_px = sum(s.get("reserved_empty_px", 0) for s in ok_shots)
    if blank_px:
        print(f"Reserved-but-empty ad space across all shots: {blank_px}px "
              f"(a bare band is by design; see the LABELLED BLANK flag for the bug).")
    voids = sorted((s for s in ok_shots if s.get("blank_run_flagged")),
                   key=lambda s: -s["blank_run_px"])
    for s in voids:
        print(f"Blank band: {s['surface']} {s['device']} — {s['blank_run_px']}px "
              f"({s.get('blank_run_viewports')} screens) from y={s['blank_run_top_px']}"
              + (f", over {', '.join(s['blank_run_ads'])}" if s.get("blank_run_ads") else ""))
    if uncaptured:
        print(f"\n⚠ {len(uncaptured)} surface(s) DID NOT CAPTURE THE SITE — these are excluded "
              "from the metrics above and were NOT inspected:", file=sys.stderr)
        for s in uncaptured:
            print(f"    {s['surface']:20s} {s['device']:7s} {s['capture_error']}", file=sys.stderr)

    # Silence is not success: with the gate told we are non-EEA, a run that finds
    # ZERO ad slots everywhere has measured nothing about the ad layer — the exact
    # false all-clear this sweep exists to prevent. Fail loudly instead.
    if args.geo != "EEA" and ok_shots and all(s.get("slots_total", 0) == 0 for s in ok_shots):
        print("\nERROR: geo override is on but NO ad slots rendered on any surface — the ad "
              "layer was not exercised, so a clean result here means nothing. Check the EEA "
              "gate in overrides/ad_slot.html, the /cdn-cgi/trace intercept, and that "
              "pagead2.googlesyndication.com is reachable.", file=sys.stderr)
        return 2
    # The same false all-clear, one device wide: mobile carrying slots is enough
    # to satisfy the gate above while every desktop shot measured nothing.
    if args.geo != "EEA" and len(devices) > 1:
        dark = blackout_devices(shots)
        if dark:
            print(f"\nERROR: no ad slots rendered on ANY {'/'.join(dark)} surface, though "
                  "other devices got them — that device's shots measured nothing about the "
                  "ad layer and must not be read as clean. Re-run that device before "
                  "trusting this manifest.", file=sys.stderr)
            return 2
    if args.keep:
        print(f"\nPruning run dirs beyond keep={args.keep}:")
        if not _prune(args.keep, dry_run=False):
            print("  nothing to prune")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

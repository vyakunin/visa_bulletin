#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "mcp", "playwright"]
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
     reserved-but-empty boxes, anchor presence, CLS, plus hero geometry —
     hero_ad_injected / nav_top_px / h1_top_px / content_below_fold) into a JSON
     manifest, so a regression is a number and not a matter of opinion.

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
only to notice a surface worth re-measuring properly.

INPUTS  : GoatCounter token at ~/tokens/goatcounter.token (read by the MCP);
          debug Chrome on :9222 (`agent_infra/scripts/launch_chrome_cdp.sh`).
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

import httpx

# Reuse the MCP's full-coverage GC machinery verbatim — single source of truth
# for the export pull, the row filtering, and the surface taxonomy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))
from daily_checkup_server import (  # noqa: E402
    SURFACE_LABELS,
    _aggregate_csv_path_counts,
    _bucket_path,
    _gc_export_full_csv,
    _gc_export_max_ts,
)

OUT_ROOT = Path.home() / ".cache" / "vb_ad_screenshots"
CDP_URL = "http://127.0.0.1:9222"
BASE = "https://visa-bulletin.us"

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
  // A slot that did NOT fill but still reserves vertical space = a visible hole.
  const reservedEmpty = unfilled.filter(e => box(e).h > 1);
  const iframes = [...document.querySelectorAll('iframe')];
  const adIframes = iframes.filter(f => /^(aswift|google_ads|ad_iframe)/.test(f.id || '') ||
                                        /doubleclick|googlesyndication/.test(f.src || ''));
  // Anchor/sticky units park themselves in a position:fixed host.
  const anchor = [...document.querySelectorAll('ins.adsbygoogle, div')].some(e => {
    const cs = getComputedStyle(e);
    return cs.position === 'fixed' && (e.className || '').toString().includes('adsbygoogle');
  });
  // Google Auto-ads can inject an in-flow unit INSIDE the branding hero, above
  // the nav — which inflates the hero and shoves all real content off the first
  // screen. Invisible to every metric above (it is a FILLED slot, reserves no
  // empty box, causes no overflow), so it needs its own geometry number.
  // Found 2026-07-20: a filled 390x390 div.google-auto-placed inside
  // .hero-section put nav at y=598 and the H1 at y=755 in an 844px viewport.
  const hero = document.querySelector('.hero-section');
  const navEl = document.querySelector('nav');
  const h1El = document.querySelector('h1');
  const topOf = (e) => e ? Math.round(e.getBoundingClientRect().top) : null;
  return {
    hero_h: hero ? Math.round(hero.getBoundingClientRect().height) : null,
    // an ad Google placed inside the hero — never one of ours (.vb-ad-slot)
    hero_ad_injected: hero
      ? hero.querySelectorAll('ins.adsbygoogle, .google-auto-placed').length : 0,
    nav_top_px: topOf(navEl),
    h1_top_px: topOf(h1El),
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
    slots_reserved_empty: reservedEmpty.length,
    reserved_empty_px: reservedEmpty.reduce((a, e) => a + box(e).h, 0),
    ad_iframes: adIframes.length,
    anchor_present: anchor,
    widest_el_px: Math.max(0, ...[...document.querySelectorAll('body *')].map(e => {
      const r = e.getBoundingClientRect(); return Math.round(r.right);
    })),
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


async def _load_csv() -> Path | None:
    async with httpx.AsyncClient() as client:
        return await _gc_export_full_csv(client)


def _derive_top_surfaces(n: int) -> list[tuple[str, str]]:
    """[(surface, url_path)] for the top-n surfaces by 7d pageviews.

    Full export coverage — a top-100 query would silently drop the profile long
    tail and mis-rank the surfaces this sweep is supposed to watch.
    """
    csv_path = asyncio.run(_load_csv())
    if not csv_path or not csv_path.exists():
        return []
    cutoff_ts = _gc_export_max_ts(csv_path)
    cutoff = cutoff_ts.date() if cutoff_ts else date.today()
    anchor = cutoff - timedelta(days=1)  # last COMPLETE day (today is partial)
    start, end = anchor - timedelta(days=6), anchor
    counts = _aggregate_csv_path_counts(csv_path, [("this_7d", start, end)])["this_7d"]
    by_surface: dict[str, dict[str, int]] = {}
    for path, hits in counts.items():
        surf = _bucket_path(path)
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


def _capture(surfaces: list[tuple[str, str]], out_dir: Path, devices: list[str],
             geo: str) -> list[dict]:
    from playwright.sync_api import sync_playwright

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
                    if geo != "EEA":
                        page.route("**/cdn-cgi/trace", _fake_trace)
                    url = f"{BASE}{path}"
                    # NOT networkidle: with the ad stack live, Google keeps polling and
                    # the network never goes idle — mobile captures timed out at 90s.
                    # `load` + an explicit settle is both faster and deterministic.
                    page.goto(url, wait_until="load", timeout=90_000)
                    page.wait_for_timeout(AD_SETTLE_MS)  # let slots fill or collapse
                    try:
                        cls = page.evaluate(CLS_JS)
                    except Exception:
                        cls = None
                    diag = page.evaluate(PROBE_JS)
                    fn = out_dir / f"{surf}__{dev}.jpg"
                    page.screenshot(path=str(fn), full_page=True, type="jpeg", quality=80)
                    # A full-page shot stitches the scrolled page but leaves position:fixed
                    # elements at their VIEWPORT offset — so the bottom anchor ad appears
                    # frozen mid-page and reads as "an ad covering the content". It is an
                    # artifact, not a bug. The viewport shot shows where fixed units really
                    # sit; compare the two before reporting any overlap.
                    fold = out_dir / f"{surf}__{dev}__viewport.jpg"
                    page.screenshot(path=str(fold), full_page=False, type="jpeg", quality=80)
                    rec = {
                        "surface": surf,
                        "label": SURFACE_LABELS.get(surf, surf),
                        "url": url,
                        "device": dev,
                        "viewport": f"{w}x{h}",
                        "file": str(fn),
                        "size_kb": round(fn.stat().st_size / 1024) if fn.exists() else 0,
                        "cls": cls,
                        **diag,
                    }
                    shots.append(rec)
                    flag = "" if rec["overflow_px"] <= 0 else f"  ⚠ OVERFLOW {rec['overflow_px']}px"
                    if rec.get("hero_ad_injected"):
                        flag += (f"  ⚠ AD-IN-HERO (hero {rec.get('hero_h')}px, "
                                 f"h1 at y={rec.get('h1_top_px')})")
                    if rec.get("content_below_fold"):
                        flag += "  ⚠ H1 BELOW FOLD"
                    print(f"  {surf:20s} {dev:7s} slots={rec['slots_total']} "
                          f"filled={rec['slots_filled']} empty-reserved={rec['slots_reserved_empty']} "
                          f"cls={cls}{flag}")
                except Exception as e:  # one bad surface must not kill the sweep
                    print(f"  {surf:20s} {dev:7s} FAILED: {e}", file=sys.stderr)
                    shots.append({"surface": surf, "device": dev, "url": f"{BASE}{path}",
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
            surfaces.append((label or _bucket_path(path), path))
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

    shots = _capture(surfaces, out_dir, devices, args.geo)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base": BASE,
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

    ok_shots = [s for s in shots if not s.get("error")]
    issues = [s for s in shots if s.get("error") or s.get("overflow_px", 0) > 0
              or s.get("slots_reserved_empty", 0) > 0
              or s.get("hero_ad_injected", 0) > 0 or s.get("content_below_fold")]
    print(f"\nWrote {len(ok_shots)} screenshots + manifest.json")
    print(f"Flagged {len(issues)} shot(s) with an error / overflow / reserved-empty slot / "
          f"ad-in-hero / H1 below the fold.")

    # Silence is not success: with the gate told we are non-EEA, a run that finds
    # ZERO ad slots everywhere has measured nothing about the ad layer — the exact
    # false all-clear this sweep exists to prevent. Fail loudly instead.
    if args.geo != "EEA" and ok_shots and all(s.get("slots_total", 0) == 0 for s in ok_shots):
        print("\nERROR: geo override is on but NO ad slots rendered on any surface — the ad "
              "layer was not exercised, so a clean result here means nothing. Check the EEA "
              "gate in overrides/ad_slot.html, the /cdn-cgi/trace intercept, and that "
              "pagead2.googlesyndication.com is reachable.", file=sys.stderr)
        return 2
    if args.keep:
        print(f"\nPruning run dirs beyond keep={args.keep}:")
        if not _prune(args.keep, dry_run=False):
            print("  nothing to prune")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

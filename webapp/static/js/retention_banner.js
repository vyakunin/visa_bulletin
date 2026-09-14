/*
 * Anonymous "your date moved" return banner.
 *
 * Reads the predicted-cutoff records baked into #retention-data (Django
 * json_script) on prediction pages, remembers them per browser in localStorage,
 * and on a RETURN visit shows a dismissible banner when a series the visitor has
 * seen before now shows a different predicted cutoff. 100% client-side, anonymous
 * (no accounts, no cookies, no backend). Degrades silently when JS records are
 * absent or localStorage is unavailable (private mode / disabled).
 *
 * A change the reader can already SEE is not announced. The page marks the card or
 * row that renders each series with data-retention-key: a series whose anchor is in
 * the viewport is skipped, and a banner already up leaves as soon as its own anchor
 * scrolls in. That is what keeps a bottom-anchored banner off the card it is about —
 * on /predictions/<month>/ the cards reach the bottom of the first screen once ads
 * render above the H1 (measured y 730-900 at 1440x900), and the banner sat across
 * them, cutting the published-floor caveat mid-sentence.
 *
 * CLS: the banner is position:fixed (out of normal flow), so showing it never
 * reflows page content — zero layout shift, even on the chart-hydration pages
 * flagged for CLS (/ and /employment-based/india).
 */
(function () {
  "use strict";

  var STORE_KEY = "vb_pred_seen_v1";     // { key: {d: iso|null, s: status, t: epoch} }
  var DISMISS_KEY = "vb_pred_dismissed_v1";

  function lsGet(k) {
    try { return window.localStorage.getItem(k); } catch (e) { return null; }
  }
  function lsSet(k, v) {
    try { window.localStorage.setItem(k, v); } catch (e) { /* quota / private mode */ }
  }
  function parse(raw, fallback) {
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (e) { return fallback; }
  }

  var el = document.getElementById("retention-data");
  if (!el) return;
  var records = parse(el.textContent, null);
  if (!Array.isArray(records) || records.length === 0) return;

  var prior = parse(lsGet(STORE_KEY), {}) || {};

  // days between two ISO date strings (b - a), positive = b is later (moved forward).
  function daysBetween(aIso, bIso) {
    var a = Date.parse(aIso + "T00:00:00Z");
    var b = Date.parse(bIso + "T00:00:00Z");
    if (isNaN(a) || isNaN(b)) return null;
    return Math.round((b - a) / 86400000);
  }

  function humanizeDays(days) {
    var d = Math.abs(days);
    if (d >= 45) { var m = Math.round(d / 30); return m + (m === 1 ? " month" : " months"); }
    if (d >= 11) { var w = Math.round(d / 7); return w + (w === 1 ? " week" : " weeks"); }
    return d + (d === 1 ? " day" : " days");
  }

  function fmtIso(iso) {
    var t = Date.parse(iso + "T00:00:00Z");
    if (isNaN(t)) return iso;
    return new Date(t).toLocaleDateString(undefined, {
      year: "numeric", month: "long", day: "numeric", timeZone: "UTC"
    });
  }

  // Describe the change from prev -> rec. Returns {text, weight} or null if no
  // meaningful change. Higher weight = more significant (surfaced first).
  function describeChange(prev, rec) {
    if (!prev) return null;
    var same = prev.s === rec.s && (prev.d || null) === (rec.d || null);
    if (same) return null;

    if (prev.s === "date" && rec.s === "date") {
      var delta = daysBetween(prev.d, rec.d);
      if (delta === null || delta === 0) return null;
      var dir = delta > 0 ? "moved forward ~" : "retrogressed ~";
      return { text: dir + humanizeDays(delta), weight: Math.abs(delta) };
    }
    if (rec.s === "current") return { text: "is now Current", weight: 100000 };
    if (rec.s === "unavailable") return { text: "became Unavailable", weight: 100000 };
    if (prev.s === "unavailable" && rec.s === "date")
      return { text: "reopened — now " + fmtIso(rec.d), weight: 100000 };
    if (prev.s === "current" && rec.s === "date")
      return { text: "now shows a cutoff of " + fmtIso(rec.d), weight: 100000 };
    return { text: "changed since your last visit", weight: 50000 };
  }

  // Is this series rendered where the reader is looking right now? Anchors are
  // emitted by the page (the forecast cards, the dashboard rows) and carry a
  // whitespace-separated list, because one card shows both of its action types.
  function onScreen(key) {
    var anchor = document.querySelector('[data-retention-key~="' + key + '"]');
    if (!anchor) return false;
    var r = anchor.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;   // display:none / collapsed
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var vw = window.innerWidth || document.documentElement.clientWidth;
    return r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  }

  // Pick the single most significant changed series the reader CANNOT see.
  var best = null;
  for (var i = 0; i < records.length; i++) {
    var rec = records[i];
    if (!rec || !rec.k) continue;
    var change = describeChange(prior[rec.k], rec);
    if (!change) continue;
    if (onScreen(rec.k)) continue;   // it is on the page in front of them
    if (!best || change.weight > best.weight) {
      best = { rec: rec, text: change.text, weight: change.weight };
    }
  }

  // Update the baseline to what this page currently shows (merge over prior so
  // series only seen on other pages are preserved for cross-page comparison).
  var now = Date.now();
  for (var j = 0; j < records.length; j++) {
    var r = records[j];
    if (r && r.k) prior[r.k] = { d: r.d || null, s: r.s, t: now };
  }
  lsSet(STORE_KEY, JSON.stringify(prior));

  if (!best) return;

  // Respect an earlier dismissal of this exact change (same series + new value).
  var sig = best.rec.k + "@" + best.rec.s + ":" + (best.rec.d || "");
  if (lsGet(DISMISS_KEY) === sig) return;

  render(best, sig);

  function render(b, dismissSig) {
    var banner = document.createElement("div");
    banner.id = "retention-banner";
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");

    var msg = document.createElement("span");
    msg.className = "retention-banner__msg";
    // The label is a mid-sentence subject phrase ("the EB-2 India Final Action
    // cutoff"), so it keeps its lower-case article.
    msg.textContent = "Since your last visit, " + b.rec.l + " " + b.text + ".";

    function remove() {
      window.removeEventListener("scroll", onScroll);
      banner.parentNode && banner.parentNode.removeChild(banner);
    }

    // The load-time check holds the promise on the first screen; this holds it for
    // the rest of the visit. The moment the card this is about scrolls into view
    // the banner has nothing left to say, so it gets out of its way rather than
    // sitting across it.
    function onScroll() {
      if (onScreen(b.rec.k)) remove();
    }

    var close = document.createElement("button");
    close.type = "button";
    close.className = "retention-banner__close";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.addEventListener("click", function () {
      lsSet(DISMISS_KEY, dismissSig);
      remove();
    });

    banner.appendChild(msg);
    banner.appendChild(close);
    document.body.appendChild(banner);
    window.addEventListener("scroll", onScroll, { passive: true });
  }
})();

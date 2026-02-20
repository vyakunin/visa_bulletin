#!/usr/bin/env python3
"""
Benchmark difflib.SequenceMatcher.ratio() vs rapidfuzz.fuzz.ratio() on sample pairs.

Used to estimate Phase 2 clustering speedup if we switch to rapidfuzz.
Run: bazel run //scripts/salary:benchmark_rapidfuzz [-- N]
     N = number of pairs to benchmark (default 50_000).
"""

import difflib
import sys
import time

# Sample normalized-name pairs similar to Phase 2 LSH candidates (similar but not identical)
SAMPLE_PAIRS = [
    ("microsoft corporation", "microsft corporation"),
    ("google llc", "google inc"),
    ("amazon web services", "amazon web service"),
    ("apple inc", "apple incorporated"),
    ("meta platforms", "meta platform"),
    ("jpmorgan chase", "jp morgan chase"),
    ("bank of america", "bank of america"),
    ("wells fargo", "well fargo"),
    ("deloitte consulting", "deloitte consultants"),
    ("ernst young", "ernst and young"),
    ("accenture llc", "accenture inc"),
    ("ibm corporation", "international business machines"),
    ("oracle america", "oracle usa"),
    ("salesforce com", "salesforce inc"),
    ("adobe systems", "adobe system"),
    ("intel corporation", "intel corp"),
    ("cisco systems", "cisco system"),
    ("netflix inc", "netflix llc"),
    ("uber technologies", "uber tech"),
    ("lyft inc", "lyft llc"),
    ("airbnb inc", "airbnb llc"),
    ("stripe inc", "stripe"),
    ("square inc", "block inc"),
    ("paypal holdings", "paypal inc"),
    ("visa inc", "visa usa"),
    ("mastercard", "master card"),
    ("goldman sachs", "goldman sachs group"),
    ("morgan stanley", "morgan stanley smith barney"),
    ("citigroup", "citi group"),
    ("capital one", "capital one financial"),
    ("honeywell international", "honeywell inc"),
    ("general electric", "ge healthcare"),
    ("boeing company", "boeing"),
    ("lockheed martin", "lockheed martin corp"),
    ("northrop grumman", "northrop grumman corp"),
    ("raytheon technologies", "raytheon co"),
    ("general dynamics", "general dynamics corp"),
    ("pfizer inc", "pfizer"),
    ("johnson johnson", "jnj"),
    ("merck co", "merck sharp dohme"),
    ("abbvie inc", "abbvie"),
    ("bristol myers squibb", "bms"),
    ("amgen inc", "amgen"),
    ("gilead sciences", "gilead"),
    ("regeneron pharmaceuticals", "regeneron"),
    ("moderna inc", "moderna tx"),
    ("thermo fisher scientific", "thermo fisher"),
]


def generate_pairs(n: int) -> list[tuple[str, str]]:
    """Repeat sample pairs to get n pairs (mimics Phase 2 candidate volume)."""
    out: list[tuple[str, str]] = []
    for i in range(n):
        out.append(SAMPLE_PAIRS[i % len(SAMPLE_PAIRS)])
    return out


def bench_difflib(pairs: list[tuple[str, str]]) -> tuple[float, list[float]]:
    """Run difflib.SequenceMatcher.ratio() on all pairs; return elapsed sec and list of ratios."""
    ratios: list[float] = []
    start = time.perf_counter()
    for a, b in pairs:
        r = difflib.SequenceMatcher(None, a, b).ratio()
        ratios.append(r)
    elapsed = time.perf_counter() - start
    return elapsed, ratios


def bench_rapidfuzz(pairs: list[tuple[str, str]]) -> tuple[float, list[float]]:
    """Run rapidfuzz.fuzz.ratio() on all pairs; return elapsed sec and list of ratios (0-1)."""
    from rapidfuzz import fuzz

    ratios: list[float] = []
    start = time.perf_counter()
    for a, b in pairs:
        r = fuzz.ratio(a, b) / 100.0
        ratios.append(r)
    elapsed = time.perf_counter() - start
    return elapsed, ratios


def main() -> None:
    n = 50_000
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
        except ValueError:
            pass
    pairs = generate_pairs(n)
    print(f"Benchmarking {n:,} pairs (normalized-name style)...")
    print()

    # Difflib
    t_difflib, ratios_difflib = bench_difflib(pairs)
    rate_difflib = n / t_difflib
    print(
        f"difflib.SequenceMatcher.ratio(): {t_difflib:.3f}s  ({rate_difflib:,.0f} pairs/sec)"
    )

    # RapidFuzz
    try:
        t_rf, ratios_rf = bench_rapidfuzz(pairs)
        rate_rf = n / t_rf
        speedup = t_difflib / t_rf
        print(f"rapidfuzz.fuzz.ratio():       {t_rf:.3f}s  ({rate_rf:,.0f} pairs/sec)")
        print()
        print(f"Speedup: {speedup:.1f}x")
        print()

        # Correlation: do thresholds (0.7, 0.95) agree?
        thresh_70_d = sum(1 for r in ratios_difflib if r >= 0.7)
        thresh_70_r = sum(1 for r in ratios_rf if r >= 0.7)
        thresh_95_d = sum(1 for r in ratios_difflib if r >= 0.95)
        thresh_95_r = sum(1 for r in ratios_rf if r >= 0.95)
        print("Threshold agreement (pairs passing):")
        print(f"  >= 0.7:  difflib={thresh_70_d:,}  rapidfuzz={thresh_70_r:,}")
        print(f"  >= 0.95: difflib={thresh_95_d:,}  rapidfuzz={thresh_95_r:,}")

        # Sample ratio comparison (first 5 pairs)
        print()
        print("Sample ratio comparison (first 5 pairs):")
        for i in range(min(5, len(pairs))):
            a, b = pairs[i]
            print(f"  {a!r} vs {b!r}")
            print(
                f"    difflib={ratios_difflib[i]:.4f}  rapidfuzz={ratios_rf[i]:.4f}  diff={ratios_rf[i] - ratios_difflib[i]:+.4f}"
            )
    except ImportError as e:
        print(f"rapidfuzz not available: {e}")
        print("Install with: pip install rapidfuzz")
        sys.exit(1)


if __name__ == "__main__":
    main()

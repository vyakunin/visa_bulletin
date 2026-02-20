"""Model A: Demand de-aggregator for VQS.

Converts quarterly I-140 receipts (from raw_facts_ledger) into a virtual queue
snapshot (priority date buckets). Phase 1: naive fixed 12-month lag.
Phase 2: convolution using PERM lag distribution when available.
"""

from datetime import date, timedelta

from lib.business.vqs.queue_snapshot import VirtualQueueSnapshot
from models.enums.country import Country

# Fixed lag from priority date to I-140 receipt (Phase 1 naive).
# Per-category lag (months): EB1 faster, EB3 slower; fallback 12 when class unknown.
NAIVE_LAG_MONTHS = 12
NAIVE_LAG_BY_CLASS = {
    "1st": 6,
    "2nd": 12,
    "3rd": 18,
    "4th": 12,
    "5th": 12,
}


def _get(row, key, default=None):
    """Get attribute or dict key from a row (model or dict)."""
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _country_to_enum_value(country: int | str | None) -> int | None:
    """Convert country to enum value (int). First step in all country parsing."""
    if country is None:
        return None
    if isinstance(country, int):
        try:
            Country(country)
            return country
        except ValueError:
            return None
    # str: resolve label/slug to enum
    s = country.strip() if isinstance(country, str) else None
    if not s:
        return None
    for c in Country:
        if c.value == 0:
            continue
        if c.label == s or (s == "China" and "China" in c.label):
            return c.value
    c = Country.from_string(s.replace(" ", "_").lower())
    return c.value if c else None


def _country_matches(
    filter_country: int | str | None, dim_country: int | str | None
) -> bool:
    """True if dimensions country matches filter. Both converted to enum value (int) first."""
    filter_value = _country_to_enum_value(filter_country)
    if filter_value is None:
        return True
    dim_value = _country_to_enum_value(dim_country)
    if dim_value is None:
        return False
    return filter_value == dim_value


def _perm_lag_by_quarter(
    facts: list, knowledge_date: date
) -> dict[tuple[date, date], dict[int, float]]:
    """Build map (ref_start, ref_end) -> {lag_days: fraction} from perm_lag_distribution facts."""
    out: dict[tuple[date, date], dict[int, float]] = {}
    for row in facts:
        pub = _get(row, "publication_date")
        if pub and pub > knowledge_date:
            continue
        if _get(row, "metric") != "perm_lag_distribution":
            continue
        start = _get(row, "reference_period_start")
        end = _get(row, "reference_period_end")
        if not start or not end:
            continue
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)
        value = _get(row, "value")
        if isinstance(value, dict):
            out[(start, end)] = value
    return out


def build_virtual_queue_snapshot(
    knowledge_date: date,
    facts: list,
    visa_class: str | None = None,
    country: int | None = None,
) -> VirtualQueueSnapshot:
    """
    Build virtual queue snapshot from raw facts as of knowledge_date.

    Phase 1 (naive): Assume fixed 12-month lag from priority date to I-140 receipt.
    For each quarter Q with receipts N, assign N to PD bucket = Q start - 12 months.

    Args:
        knowledge_date: Only facts with publication_date <= this date are used.
        facts: Iterable of RawFactsLedger-like objects (or dicts with metric, value,
               reference_period_start, dimensions, publication_date).
        visa_class: Optional filter (e.g. "2nd" for EB2); dimensions["category"].
        country: Optional filter as Country enum value (e.g. Country.INDIA); dimensions["country"] must be stored as enum value (int).

    Returns:
        VirtualQueueSnapshot with demand binned by priority date (month).
    """
    snapshot = VirtualQueueSnapshot()
    perm_lag = _perm_lag_by_quarter(facts, knowledge_date) if facts else {}

    for row in facts:
        pub = _get(row, "publication_date")
        if pub and pub > knowledge_date:
            continue

        metric = _get(row, "metric")
        dims = _get(row, "dimensions") or {}

        if visa_class and dims.get("category") != visa_class:
            continue
        if not _country_matches(country, dims.get("country")):
            continue

        value = _get(row, "value")
        if not isinstance(value, (int, float)) or value < 0:
            continue

        start = _get(row, "reference_period_start")
        end = _get(row, "reference_period_end")
        if not start:
            continue
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if end and isinstance(end, str):
            end = date.fromisoformat(end)

        if metric == "i140_receipts":
            n = int(value)
            dist = perm_lag.get((start, end)) if end else None
            if dist and isinstance(dist, dict):
                for lag_days, frac in dist.items():
                    pd_date = start - timedelta(days=int(lag_days))
                    bucket_date = date(pd_date.year, pd_date.month, 1)
                    snapshot.add(bucket_date, round(n * frac))
            else:
                # Spread demand evenly across the reference period months
                if end:
                    n_months = max(
                        1, (end.year - start.year) * 12 + end.month - start.month + 1
                    )
                else:
                    n_months = 1
                per_month = max(1, n // n_months)
                remainder = n - per_month * n_months
                lag_months = NAIVE_LAG_BY_CLASS.get(visa_class, NAIVE_LAG_MONTHS)
                cursor_year, cursor_month = start.year, start.month
                for offset in range(n_months):
                    m = cursor_month + offset
                    y = cursor_year
                    while m > 12:
                        m -= 12
                        y += 1
                    lag_m = m - lag_months
                    lag_y = y
                    while lag_m <= 0:
                        lag_m += 12
                        lag_y -= 1
                    count = per_month + (1 if offset < remainder else 0)
                    if count < 0:
                        count = 0
                    snapshot.add(date(lag_y, lag_m, 1), count)

        elif metric == "perm_applications":
            # For PERM, we have the actual Priority Date (case_submitted)
            # Filter for Certified cases only
            status = dims.get("status", "")
            if status not in ("CERTIFIED", "CERTIFIED-EXPIRED"):
                continue

            # Direct addition to PD bucket (no lag estimation needed)
            pd_date = start
            bucket_date = date(pd_date.year, pd_date.month, 1)
            snapshot.add(bucket_date, int(value))

    return snapshot

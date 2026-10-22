"""Choose the 6m/12m horizon expert per series for one action type, against no-change.

Walk-forward over every bulletin: at knowledge date (publication − 1 day) each
candidate the publish dispatch can route a horizon to — GBM Gated and Oppenheim
Pace — predicts the cutoff ``horizon`` bulletins ahead, scored against the
realized bulletin. Persistence (no change) is the baseline, and is what the
dashboard renders as "No step predicted".

Decision rule (fixed before the first run): per (series, horizon), the candidate
with the lowest full-window MAE is adopted only if it beats persistence by at
least ``--margin`` days (default 10, the dispatch table's own threshold) over the
full window AND is no worse than persistence over the recent window (targets on
or after ``--recent-start``). Otherwise the series stays on persistence.

Usage:
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_horizon_dispatch \
      --action-type filing --out /app/logs/horizon_dispatch_filing.json
  scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_horizon_dispatch \
      --action-type final_action --out /app/logs/horizon_dispatch_fa.json
"""

import argparse
import calendar
import json
import logging
from collections import defaultdict
from datetime import date, timedelta

import django

django.setup()

from lib.utils.logging_utils import ScriptLogger

logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

HORIZONS = (6, 12)
CANDIDATES = ("gbm_gated", "oppenheim_pace")
BASELINE = "persistence"


def _add_months(d: date, n: int) -> date:
    month = d.month + n
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


def _series() -> list[tuple[int, str, str]]:
    from models.enums.country import Country

    return [
        (country.value, vc, f"{country.name.title()} EB-{vc[0]}")
        for country in (Country.INDIA, Country.CHINA)
        for vc in ("1st", "2nd", "3rd")
    ]


def collect_rows(action_type: str, start: date) -> list[dict]:
    from lib.business.vqs.data_cache import get_all_bulletins, get_cutoff_at_date
    from lib.business.vqs.expert_pool import expert_oppenheim_pace
    from lib.business.vqs.gbm_expert import expert_gbm_gated

    all_pub = sorted(b.publication_date for b in get_all_bulletins())
    max_pub = max(all_pub)
    rows: list[dict] = []
    for i, pub_date in enumerate(p for p in all_pub if p >= start):
        knowledge_date = pub_date - timedelta(days=1)
        for country, visa_class, label in _series():
            current = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
            if current is None:
                continue
            for horizon in HORIZONS:
                target = _add_months(pub_date, horizon - 1)
                if target > max_pub:
                    continue
                actual = get_cutoff_at_date(visa_class, country, action_type, target)
                if actual is None:
                    continue
                preds = {
                    BASELINE: current,
                    "gbm_gated": expert_gbm_gated(
                        visa_class=visa_class, country=country, action_type=action_type,
                        knowledge_date=knowledge_date, horizon=horizon,
                    ),
                    "oppenheim_pace": expert_oppenheim_pace(
                        visa_class=visa_class, country=country, action_type=action_type,
                        knowledge_date=knowledge_date, horizon=horizon,
                    ),
                }
                if any(p is None for p in preds.values()):
                    continue
                rows.append({
                    "series": label,
                    "horizon": horizon,
                    "target": target.isoformat(),
                    "actual_delta": (actual - current).days,
                    "err": {name: abs((p - actual).days) for name, p in preds.items()},
                })
        if (i + 1) % 25 == 0:
            logger.info("processed %d bulletins (%d rows)", i + 1, len(rows))
    return rows


def _mae(rows: list[dict], name: str) -> float | None:
    return round(sum(r["err"][name] for r in rows) / len(rows), 1) if rows else None


def summarize(rows: list[dict], recent_start: date, margin: float) -> dict:
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["series"], r["horizon"])].append(r)

    surfaces = {}
    for (series, horizon), grp in sorted(groups.items()):
        recent = [r for r in grp if date.fromisoformat(r["target"]) >= recent_start]
        full_mae = {n: _mae(grp, n) for n in (BASELINE, *CANDIDATES)}
        recent_mae = {n: _mae(recent, n) for n in (BASELINE, *CANDIDATES)}
        best = min(CANDIDATES, key=lambda n: full_mae[n])
        adopted = (
            full_mae[best] <= full_mae[BASELINE] - margin
            and recent_mae[best] is not None
            and recent_mae[best] <= recent_mae[BASELINE]
        )
        surfaces[f"{series} {horizon}m"] = {
            "n": len(grp),
            "n_recent": len(recent),
            "full_mae": full_mae,
            "recent_mae": recent_mae,
            "best_candidate": best,
            "dispatch": best if adopted else BASELINE,
        }
    return surfaces


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-type", default="filing", choices=["final_action", "filing"])
    parser.add_argument("--start", default="2016-01-01", help="First bulletin to forecast from")
    parser.add_argument("--recent-start", default="2021-10-01")
    parser.add_argument("--margin", type=float, default=10.0)
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()
    script_logger.log_call(args=vars(args), context="Horizon dispatch gate per action type")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rows = collect_rows(args.action_type, date.fromisoformat(args.start))
    surfaces = summarize(rows, date.fromisoformat(args.recent_start), args.margin)
    with open(args.out, "w") as fh:
        json.dump({"action_type": args.action_type, "args": vars(args),
                   "surfaces": surfaces}, fh, indent=2)

    for name, s in surfaces.items():
        f, r = s["full_mae"], s["recent_mae"]
        print(
            f"{name:<16} n={s['n']:>3} persist={f[BASELINE]:>6} gbm={f['gbm_gated']:>6} "
            f"pace={f['oppenheim_pace']:>6} | recent persist={r[BASELINE]} "
            f"best={r[s['best_candidate']]} -> {s['dispatch']}"
        )


if __name__ == "__main__":
    main()

"""Independent Expert Backtest for VQS Rebuild.

Runs each expert from expert_pool.py independently (no ensemble, no dampening)
across all 6 oversubscribed EB series and computes per-expert accuracy metrics.

This is the diagnostic step that answers: which experts actually have signal,
and for which series?

Usage:
    bazel run //scripts/vqs:backtest_experts
    bazel run //scripts/vqs:backtest_experts -- --start 2018-01-01
    bazel run //scripts/vqs:backtest_experts -- --series "India EB-2"
"""

import argparse
import datetime
import logging
import os
from collections import defaultdict
from dataclasses import dataclass

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.vqs.data_cache import get_cutoffs_for_series
from lib.business.vqs.expert_pool import (
    expert_demand_signal,
    expert_fy_reset,
    expert_linear_extrap,
    expert_momentum_3m,
    expert_persistence,
    expert_seasonal_median,
    expert_supply_aware,
)
from lib.business.vqs.regime import classify_regime
from lib.business.vqs.seasonal_predictor import get_last_N_moves
from models.enums.country import Country

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SERIES = [
    (Country.INDIA.value, "2nd", "India EB-2"),
    (Country.INDIA.value, "3rd", "India EB-3"),
    (Country.CHINA.value, "2nd", "China EB-2"),
    (Country.CHINA.value, "3rd", "China EB-3"),
    (Country.CHINA.value, "1st", "China EB-1"),
    (Country.INDIA.value, "1st", "India EB-1"),
]

ACTION_TYPE = "filing"

EXPERTS = {
    "persistence": expert_persistence,
    "seasonal_median": expert_seasonal_median,
    "linear_extrap": expert_linear_extrap,
    "momentum_3m": expert_momentum_3m,
    "fy_reset": expert_fy_reset,
    "supply_aware": expert_supply_aware,
    "demand_signal": expert_demand_signal,
}

FY_BOUNDARY_MONTHS = {9, 10, 11}


@dataclass
class PredictionRow:
    knowledge_date: datetime.date
    target_month: int
    actual: datetime.date
    previous: datetime.date
    predictions: dict[str, datetime.date | None]
    regime: str


def collect_predictions(
    visa_class: str,
    country: int,
    start_date: datetime.date,
    end_date: datetime.date,
    use_spaghetti_kd: bool = False,
) -> list[PredictionRow]:
    """Walk through bulletin history, running each expert independently.

    Args:
        use_spaghetti_kd: If True, use target_date - 1 month as knowledge_date
            (matches spaghetti evaluation). If False, use previous bulletin's
            publication_date (original backtest methodology).
    """
    from dateutil.relativedelta import relativedelta

    cutoffs = get_cutoffs_for_series(visa_class, country, ACTION_TYPE)
    if len(cutoffs) < 2:
        return []

    rows = []
    for i in range(1, len(cutoffs)):
        prev = cutoffs[i - 1]
        curr = cutoffs[i]

        pub_date = curr.bulletin.publication_date
        if pub_date < start_date or pub_date > end_date:
            continue

        if use_spaghetti_kd:
            knowledge_date = pub_date - relativedelta(months=1)
        else:
            knowledge_date = prev.bulletin.publication_date
        actual = curr.cutoff_date
        previous = prev.cutoff_date

        if actual is None or previous is None:
            continue

        moves = get_last_N_moves(visa_class, country, ACTION_TYPE, knowledge_date, 6)
        regime_state = classify_regime(moves)

        preds = {}
        for name, expert_fn in EXPERTS.items():
            try:
                pred = expert_fn(visa_class, country, ACTION_TYPE, knowledge_date)
            except Exception:
                pred = None
            preds[name] = pred

        rows.append(PredictionRow(
            knowledge_date=knowledge_date,
            target_month=pub_date.month,
            actual=actual,
            previous=previous,
            predictions=preds,
            regime=regime_state.regime.value,
        ))

    return rows


@dataclass
class ExpertMetrics:
    mae: float
    count: int
    win_vs_persistence: int
    lose_vs_persistence: int
    direction_correct: int
    direction_total: int
    mae_when_actual_moved: float | None
    count_when_actual_moved: int
    mae_fy_boundary: float | None
    mae_steady_state: float | None


def compute_expert_metrics(
    rows: list[PredictionRow], expert_name: str
) -> ExpertMetrics:
    errors = []
    persist_errors = []
    wins = 0
    losses = 0
    dir_correct = 0
    dir_total = 0
    errors_moved = []
    errors_fy = []
    errors_steady = []

    for row in rows:
        pred = row.predictions.get(expert_name)
        if pred is None:
            continue

        err = abs((pred - row.actual).days)
        persist_err = abs((row.previous - row.actual).days)
        errors.append(err)
        persist_errors.append(persist_err)

        if err < persist_err:
            wins += 1
        elif err > persist_err:
            losses += 1

        actual_move = (row.actual - row.previous).days
        if actual_move != 0:
            dir_total += 1
            pred_move = (pred - row.previous).days
            if (pred_move > 0 and actual_move > 0) or (pred_move < 0 and actual_move < 0):
                dir_correct += 1

        if actual_move != 0:
            errors_moved.append(err)

        if row.target_month in FY_BOUNDARY_MONTHS:
            errors_fy.append(err)
        else:
            errors_steady.append(err)

    if not errors:
        return ExpertMetrics(0, 0, 0, 0, 0, 0, None, 0, None, None)

    return ExpertMetrics(
        mae=sum(errors) / len(errors),
        count=len(errors),
        win_vs_persistence=wins,
        lose_vs_persistence=losses,
        direction_correct=dir_correct,
        direction_total=dir_total,
        mae_when_actual_moved=sum(errors_moved) / len(errors_moved) if errors_moved else None,
        count_when_actual_moved=len(errors_moved),
        mae_fy_boundary=sum(errors_fy) / len(errors_fy) if errors_fy else None,
        mae_steady_state=sum(errors_steady) / len(errors_steady) if errors_steady else None,
    )


def compute_regime_expert_metrics(
    rows: list[PredictionRow],
) -> dict[str, dict[str, ExpertMetrics]]:
    """Compute expert metrics broken down by regime."""
    rows_by_regime: dict[str, list[PredictionRow]] = defaultdict(list)
    for row in rows:
        rows_by_regime[row.regime].append(row)

    result = {}
    for regime, regime_rows in sorted(rows_by_regime.items()):
        expert_metrics = {}
        for expert_name in EXPERTS:
            expert_metrics[expert_name] = compute_expert_metrics(regime_rows, expert_name)
        result[regime] = expert_metrics
    return result


def print_series_results(label: str, rows: list[PredictionRow]):
    logger.info(f"\n{'='*90}")
    logger.info(f"  {label} ({len(rows)} months)")
    logger.info(f"{'='*90}")

    persist_m = compute_expert_metrics(rows, "persistence")
    logger.info(f"  Persistence baseline: MAE={persist_m.mae:.1f}d")
    logger.info("")

    header = f"  {'Expert':<18} {'MAE':>7} {'Win%':>7} {'DirAcc':>7} {'MAE(mv)':>8} {'MAE(FY)':>8} {'MAE(ss)':>8}"
    logger.info(header)
    logger.info(f"  {'-'*73}")

    for expert_name in EXPERTS:
        m = compute_expert_metrics(rows, expert_name)
        if m.count == 0:
            continue
        total_decisions = m.win_vs_persistence + m.lose_vs_persistence
        win_pct = (m.win_vs_persistence / total_decisions * 100) if total_decisions > 0 else 0
        dir_acc = (m.direction_correct / m.direction_total * 100) if m.direction_total > 0 else 0
        mae_mv = f"{m.mae_when_actual_moved:.1f}" if m.mae_when_actual_moved is not None else "N/A"
        mae_fy = f"{m.mae_fy_boundary:.1f}" if m.mae_fy_boundary is not None else "N/A"
        mae_ss = f"{m.mae_steady_state:.1f}" if m.mae_steady_state is not None else "N/A"

        marker = " <--" if expert_name != "persistence" and m.mae < persist_m.mae else ""
        logger.info(
            f"  {expert_name:<18} {m.mae:>7.1f} {win_pct:>6.1f}% {dir_acc:>6.1f}% "
            f"{mae_mv:>8} {mae_fy:>8} {mae_ss:>8}{marker}"
        )


def print_regime_results(label: str, rows: list[PredictionRow]):
    regime_metrics = compute_regime_expert_metrics(rows)

    logger.info(f"\n  --- Regime Breakdown for {label} ---")
    for regime, experts in regime_metrics.items():
        regime_count = experts["persistence"].count
        if regime_count < 3:
            continue
        persist_mae = experts["persistence"].mae

        logger.info(f"\n  Regime: {regime.upper()} ({regime_count} months, persistence MAE={persist_mae:.1f}d)")
        best_expert = None
        best_mae = persist_mae
        for expert_name, m in sorted(experts.items()):
            if m.count == 0 or expert_name == "persistence":
                continue
            marker = ""
            if m.mae < best_mae:
                best_mae = m.mae
                best_expert = expert_name
                marker = " *"
            logger.info(f"    {expert_name:<18} MAE={m.mae:>7.1f}d{marker}")

        if best_expert:
            improvement = (persist_mae - best_mae) / persist_mae * 100
            logger.info(f"    >> BEST: {best_expert} ({improvement:.1f}% better than persistence)")
        else:
            logger.info("    >> persistence wins")


def print_selection_map(all_rows: dict[str, list[PredictionRow]]):
    """Print the recommended expert selection map based on backtest data."""
    logger.info(f"\n{'='*90}")
    logger.info("  RECOMMENDED EXPERT SELECTION MAP")
    logger.info(f"{'='*90}")

    for label, rows in all_rows.items():
        regime_metrics = compute_regime_expert_metrics(rows)
        logger.info(f"\n  {label}:")
        for regime, experts in sorted(regime_metrics.items()):
            if experts["persistence"].count < 3:
                continue
            persist_mae = experts["persistence"].mae
            best_expert = "persistence"
            best_mae = persist_mae
            for name, m in experts.items():
                if m.count > 0 and m.mae < best_mae:
                    best_mae = m.mae
                    best_expert = name
            delta = persist_mae - best_mae
            logger.info(f"    {regime:<16} -> {best_expert:<18} (MAE={best_mae:.1f}d, -{delta:.1f}d vs persist)")


def print_aggregate_summary(all_rows: dict[str, list[PredictionRow]]):
    """Print aggregate summary across all series."""
    logger.info(f"\n{'='*90}")
    logger.info("  AGGREGATE SUMMARY (all series combined)")
    logger.info(f"{'='*90}")

    combined = []
    for rows in all_rows.values():
        combined.extend(rows)

    if not combined:
        return

    persist_m = compute_expert_metrics(combined, "persistence")
    logger.info(f"\n  Persistence baseline: MAE={persist_m.mae:.1f}d ({persist_m.count} predictions)")
    logger.info("")

    header = f"  {'Expert':<18} {'MAE':>7} {'Win%':>7} {'DirAcc':>7} {'MAE(mv)':>8} {'MAE(FY)':>8} {'MAE(ss)':>8}"
    logger.info(header)
    logger.info(f"  {'-'*73}")

    for expert_name in EXPERTS:
        m = compute_expert_metrics(combined, expert_name)
        if m.count == 0:
            continue
        total_decisions = m.win_vs_persistence + m.lose_vs_persistence
        win_pct = (m.win_vs_persistence / total_decisions * 100) if total_decisions > 0 else 0
        dir_acc = (m.direction_correct / m.direction_total * 100) if m.direction_total > 0 else 0
        mae_mv = f"{m.mae_when_actual_moved:.1f}" if m.mae_when_actual_moved is not None else "N/A"
        mae_fy = f"{m.mae_fy_boundary:.1f}" if m.mae_fy_boundary is not None else "N/A"
        mae_ss = f"{m.mae_steady_state:.1f}" if m.mae_steady_state is not None else "N/A"

        marker = " <-- BEATS PERSISTENCE" if expert_name != "persistence" and m.mae < persist_m.mae else ""
        logger.info(
            f"  {expert_name:<18} {m.mae:>7.1f} {win_pct:>6.1f}% {dir_acc:>6.1f}% "
            f"{mae_mv:>8} {mae_fy:>8} {mae_ss:>8}{marker}"
        )


def main():
    parser = argparse.ArgumentParser(description="Independent Expert Backtest")
    parser.add_argument("--start", type=str, default="2016-01-01")
    parser.add_argument("--end", type=str, default="2026-03-01")
    parser.add_argument("--series", type=str, default=None, help="Filter to one series label")
    parser.add_argument("--spaghetti-kd", action="store_true",
                        help="Use spaghetti-style knowledge_date (target - 1m)")
    parser.add_argument("--error-start", type=str, default=None,
                        help="Only count errors from this date onward")
    args = parser.parse_args()

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    error_start = datetime.date.fromisoformat(args.error_start) if args.error_start else None

    all_rows: dict[str, list[PredictionRow]] = {}

    for country, visa_class, label in SERIES:
        if args.series and label != args.series:
            continue

        logger.info(f"Collecting predictions for {label}...")
        rows = collect_predictions(visa_class, country, start, end, use_spaghetti_kd=args.spaghetti_kd)
        if error_start:
            rows = [r for r in rows if r.knowledge_date >= error_start]
        all_rows[label] = rows

        print_series_results(label, rows)
        print_regime_results(label, rows)

    print_aggregate_summary(all_rows)
    print_selection_map(all_rows)


if __name__ == "__main__":
    main()

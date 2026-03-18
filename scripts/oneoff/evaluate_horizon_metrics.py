import datetime
import os
from collections import defaultdict

import django
import numpy as np

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.bulletin import Bulletin
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate


def get_actual_cutoff(visa_class, country, action_type, target_date):
    """
    Finds the actual cutoff date for a specific target month.
    """
    b = Bulletin.objects.filter(
        publication_date__year=target_date.year,
        publication_date__month=target_date.month,
    ).first()

    if not b:
        return None

    cutoff = b.cutoff_dates.filter(
        visa_class=visa_class, country=country, action_type=action_type
    ).first()

    return cutoff.cutoff_date if cutoff else None


def predict_linear(visa_class, country, action_type, knowledge_date, target_date):
    """
    Predicts cutoff using Linear Extrapolation based on data available at knowledge_date.
    """
    history = VisaCutoffDate.objects.filter(
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        bulletin__publication_date__lte=knowledge_date,
    ).order_by("-bulletin__publication_date")[:24]  # Last 24 months

    valid_history = [h for h in history if h.cutoff_date]
    if len(valid_history) < 6:
        # Fallback to naive if not enough history
        return valid_history[0].cutoff_date if valid_history else None

    BASE_DATE = datetime.date(2000, 1, 1)  # noqa: N806
    X = []  # noqa: N806
    y = []

    for h in reversed(valid_history):
        m_idx = (
            h.bulletin.publication_date.year * 12 + h.bulletin.publication_date.month
        )
        d_val = (h.cutoff_date - BASE_DATE).days
        X.append(m_idx)
        y.append(d_val)

    if len(X) < 2:
        return valid_history[0].cutoff_date

    try:
        A = np.vstack([X, np.ones(len(X))]).T  # noqa: N806
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]

        target_idx = target_date.year * 12 + target_date.month
        pred_days = m * target_idx + c
        return BASE_DATE + datetime.timedelta(days=int(pred_days))
    except (ValueError, TypeError, np.linalg.LinAlgError):
        return valid_history[0].cutoff_date


def evaluate_group(name, keys, horizons, action_type, start_date, end_date):
    print(f"\n--- Evaluating Group: {name} ---")
    errors = defaultdict(lambda: defaultdict(list))

    sim_date = start_date
    while sim_date < end_date:
        # For each specific category
        for visa_class, country_name in keys:
            country = getattr(Country, country_name).value

            # 1. Get History available at sim_date
            history_qs = VisaCutoffDate.objects.filter(
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                bulletin__publication_date__lte=sim_date,
            ).order_by("bulletin__publication_date")

            history_dates = [h.bulletin.publication_date for h in history_qs]
            history_cutoffs = [h.cutoff_date for h in history_qs]

            non_none_history = [h for h in history_qs if h.cutoff_date]
            if not non_none_history:
                continue

            last_known_cutoff = non_none_history[-1].cutoff_date

            # 2. Generate forecasts for Horizons
            for h_months in horizons:
                # Calculate Target Date (Sim Date + h_months)
                y = sim_date.year + (sim_date.month + h_months - 1) // 12
                m = (sim_date.month + h_months - 1) % 12 + 1
                target_date = datetime.date(y, m, 1)

                # Get Actual
                actual = get_actual_cutoff(
                    visa_class, country, action_type, target_date
                )
                if not actual:
                    continue

                # --- A. Naive Model (Last Known) ---
                naive_pred = last_known_cutoff

                # --- B. Dashboard Logic (12-mo Avg or Hist Regression) ---
                recent_points = [
                    (d, c)
                    for d, c in zip(history_dates, history_cutoffs)
                    if c is not None and d > (sim_date - datetime.timedelta(days=365))
                ]

                dashboard_pred = None

                if len(recent_points) >= 2:
                    first = recent_points[0]
                    last = recent_points[-1]
                    months_diff = (last[0].year - first[0].year) * 12 + (
                        last[0].month - first[0].month
                    )
                    if months_diff < 1:
                        months_diff = 1
                    rate = (last[1] - first[1]).days / months_diff

                    if rate > 0:
                        months_to_target = (target_date.year - sim_date.year) * 12 + (
                            target_date.month - sim_date.month
                        )
                        add_days = rate * months_to_target
                        dashboard_pred = last[1] + datetime.timedelta(
                            days=int(add_days)
                        )
                    else:
                        dashboard_pred = predict_linear(
                            visa_class, country, action_type, sim_date, target_date
                        )
                else:
                    dashboard_pred = last_known_cutoff

                # --- C. Linear Model (24-mo Regression) ---
                linear_pred = predict_linear(
                    visa_class, country, action_type, sim_date, target_date
                )

                if dashboard_pred:
                    errors[h_months]["Dashboard"].append(
                        abs((dashboard_pred - actual).days)
                    )
                if linear_pred:
                    errors[h_months]["Linear"].append(abs((linear_pred - actual).days))
                if naive_pred:
                    errors[h_months]["Naive"].append(abs((naive_pred - actual).days))

        # Increment Sim Date
        if sim_date.month == 12:
            sim_date = datetime.date(sim_date.year + 1, 1, 1)
        else:
            sim_date = datetime.date(sim_date.year, sim_date.month + 1, 1)

    print(f"\n{name} Results (MAE in Days):")
    print(
        f"{'Horizon':<10} {'Dashboard':<12} {'Linear (24m)':<15} {'Naive':<10} {'Best'}"
    )
    print("-" * 60)

    for h in horizons:
        d_errs = errors[h]["Dashboard"]
        l_errs = errors[h]["Linear"]
        n_errs = errors[h]["Naive"]

        if not d_errs:
            continue

        mae_d = np.mean(d_errs)
        mae_l = np.mean(l_errs)
        mae_n = np.mean(n_errs)

        best_score = min(mae_d, mae_l, mae_n)
        best_model = ""
        if best_score == mae_d:
            best_model = "Dashboard"
        elif best_score == mae_l:
            best_model = "Linear"
        else:
            best_model = "Naive"

        print(
            f"{h} Month{'s' if h > 1 else ' ':<4} {mae_d:<12.1f} {mae_l:<15.1f} {mae_n:<10.1f} {best_model}"
        )


def run_horizon_evaluation():
    print("--- Starting Horizon Error Evaluation (Dynamic vs Static, Post-2023) ---")

    action_type = "final_action"
    horizons = [1, 3, 6]

    # Exclude 2023 -> Start Jan 2024
    start_date = datetime.date(2024, 1, 1)
    end_date = datetime.date(2025, 2, 1)

    dynamic_keys = [
        ("2nd", "INDIA"),
        ("3rd", "INDIA"),
        ("2nd", "CHINA"),
        ("3rd", "CHINA"),
    ]

    static_keys = [
        ("1st", "ALL"),
        ("4th", "ALL"),
    ]

    evaluate_group(
        "DYNAMIC Series (India/China EB2/3)",
        dynamic_keys,
        horizons,
        action_type,
        start_date,
        end_date,
    )
    evaluate_group(
        "STATIC Series (ROW EB1/4)",
        static_keys,
        horizons,
        action_type,
        start_date,
        end_date,
    )


if __name__ == "__main__":
    run_horizon_evaluation()

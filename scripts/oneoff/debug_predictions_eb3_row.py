import datetime
import os

# Setup Django
# sys.path.append('/Users/vyakunin/cursor_projects/visa_bulletin')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff


def debug_eb3_row():
    visa_class = "3rd"
    country = Country.ALL
    action_type = "final_action"

    print(f"--- Debugging Predictions for {visa_class} {country} ({action_type}) ---")

    # 1. Fetch Latest Prediction
    latest_pb = PredictedBulletin.objects.order_by("-generated_at").first()
    if not latest_pb:
        print("No PredictedBulletin found.")
        return

    print(
        f"Latest Prediction Set: {latest_pb.target_bulletin_month} (Created: {latest_pb.generated_at})"
    )

    pred_cutoff = PredictedCutoff.objects.filter(
        bulletin=latest_pb,
        visa_class=visa_class,
        country=country,
        action_type=action_type,
    ).first()

    if pred_cutoff:
        print(f"  Predicted Date: {pred_cutoff.predicted_date}")
        print(
            f"  Confidence Interval: {pred_cutoff.confidence_low} - {pred_cutoff.confidence_high}"
        )
        print(f"  Explanation: {pred_cutoff.explanation_markdown[:100]}...")  # truncate
    else:
        print("  No prediction found for this category.")

    # 2. Fetch Historical Data (Last 24 months)
    history = VisaCutoffDate.objects.filter(
        visa_class=visa_class, country=country, action_type=action_type
    ).order_by("-bulletin__publication_date")[:24]

    print("\n--- Historical Data (Last 5) ---")
    base_date = datetime.date(2000, 1, 1)

    for h in history[:5]:  # diverse order
        print(f"  {h.bulletin.publication_date}: {h.cutoff_date}")

    # Prepare for Linear Regression
    # X = months since start
    # Y = days since base_date

    X = []  # noqa: N806
    y = []

    # Iterate reversed (oldest first)
    for h in reversed(history):
        if not h.cutoff_date:
            continue

        # Approximate month index
        months_diff = (
            h.bulletin.publication_date.year - 2020
        ) * 12 + h.bulletin.publication_date.month
        days_val = (h.cutoff_date - base_date).days

        X.append([months_diff])
        y.append(days_val)

    if not X:
        print("Not enough data for regression.")
        return

    # 3. Simple Linear Extrapolation (Manual OLS)
    # y = mx + c
    # m = (N * sum(xy) - sum(x)*sum(y)) / (N * sum(x^2) - sum(x)^2)
    # c = (sum(y) - m * sum(x)) / N

    n = len(X)
    sum_x = sum(x[0] for x in X)
    sum_y = sum(y)
    sum_xy = sum(X[i][0] * y[i] for i in range(n))
    sum_xx = sum(X[i][0] ** 2 for i in range(n))

    if n * sum_xx - sum_x**2 == 0:
        print("Cannot calculate regression (denominator 0).")
        return

    m = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x**2)
    c = (sum_y - m * sum_x) / n

    # Predict next month
    last_pub = history[0].bulletin.publication_date
    next_month_idx = (last_pub.year - 2020) * 12 + last_pub.month + 1
    pred_days = m * next_month_idx + c

    linear_pred_date = base_date + datetime.timedelta(days=int(pred_days))

    print("\n--- Linear Extrapolation Model ---")
    print(f"  Slope (days advanced per month): {m:.2f}")
    print(f"  Intercept: {c:.2f}")
    print(f"  Linear Prediction for Next Month: {linear_pred_date}")

    # Comparison
    if pred_cutoff and pred_cutoff.predicted_date:
        diff = (pred_cutoff.predicted_date - linear_pred_date).days
        print("\n--- Comparison ---")
        print(f"  AI Prediction vs Linear: {diff} days difference")
        if diff < -30:
            print("  AI is significantly more pessimistic than linear trend.")
        elif diff > 30:
            print("  AI is significantly more optimistic than linear trend.")
        else:
            print("  AI is roughly in line with linear trend.")


if __name__ == "__main__":
    debug_eb3_row()

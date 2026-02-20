import os
from datetime import date

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.bulletin import Bulletin
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff


def analyze_shift():
    june_2025 = date(2025, 6, 1)
    july_2025 = date(2025, 7, 1)

    print("--- Analyzing Shift for India EB-3 Final Action ---")

    # Get June 2025 Actual
    june_actual = Bulletin.objects.filter(publication_date=june_2025).first()
    june_date = None
    if june_actual:
        print("June 2025 Actual Bulletin found.")
        eb3_india_june = VisaCutoffDate.objects.filter(
            bulletin=june_actual,
            visa_class="3rd",
            country=Country.INDIA,
            action_type="final_action",
        ).first()
        if eb3_india_june:
            june_date = eb3_india_june.cutoff_date
            print(f"June 2025 Actual Date: {june_date}")
        else:
            print("June 2025 EB-3 India data NOT found.")
    else:
        print("June 2025 Actual Bulletin NOT found.")

    # Get July 2025 Prediction
    july_pred = PredictedBulletin.objects.filter(
        target_bulletin_month=july_2025
    ).first()
    july_date = None
    if july_pred:
        print(f"July 2025 Prediction found (Generated: {july_pred.prediction_date})")
        eb3_india_pred = PredictedCutoff.objects.filter(
            predicted_bulletin=july_pred,
            visa_class="3rd",
            country=Country.INDIA,
            action_type="final_action",
        ).first()
        if eb3_india_pred:
            july_date = eb3_india_pred.predicted_date
            print(f"July 2025 Predicted Date: {july_date}")
        else:
            print("July 2025 EB-3 India Prediction data NOT found.")
    else:
        print("July 2025 Prediction NOT found.")

    # Calculate Delta
    if june_date and july_date:
        delta = (july_date - june_date).days
        print(f"Calculated Delta: {delta} days")
        if delta < 0:
            print(f"NEGATIVE SHIFT CONFIRMED: {delta} days")
    else:
        print("Cannot calculate delta due to missing data.")


if __name__ == "__main__":
    analyze_shift()

import sys

import django
from django.conf import settings

if not settings.configured:
    sys.path.append(".")
    django.setup()

from models.enums.country import Country
from models.vqs import PredictedBulletin


def debug_predictions(year, month):
    print(f"--- Debugging Predictions for {year}-{month} ---")
    try:
        bulletin = PredictedBulletin.objects.get(
            target_bulletin_month__year=year, target_bulletin_month__month=month
        )
        print(f"Found Bulletin: {bulletin}")
        print(f"Target Month: {bulletin.target_bulletin_month}")
        print(f"Prediction Date: {bulletin.prediction_date}")
        print(f"Generated At: {bulletin.generated_at}")

        cutoffs = list(bulletin.cutoffs.all())
        print(f"Total Cutoffs: {len(cutoffs)}")

        if not cutoffs:
            print("WARNING: No cutoffs found for this bulletin.")
            return

        print("\n--- Simulating View Logic ---")
        classes = ["1st", "2nd", "3rd", "4th", "5th"]
        countries = [
            Country.ALL,
            Country.CHINA,
            Country.INDIA,
            Country.MEXICO,
            Country.PHILIPPINES,
        ]

        # Build matrix
        matrix = {}
        for vc in classes:
            matrix[vc] = {}
            for c in countries:
                matrix[vc][c.value] = {"final_action": None, "filing": None}

        # Populate
        matches = 0
        for cutoff in bulletin.cutoffs.all():
            if cutoff.visa_class in matrix:
                if cutoff.country in matrix[cutoff.visa_class]:
                    atype = (
                        "filing" if "filing" in cutoff.action_type else "final_action"
                    )
                    matrix[cutoff.visa_class][cutoff.country][atype] = cutoff
                    matches += 1
                else:
                    if cutoff.country == 1:
                        print(
                            f"  Mismatch Country: {cutoff.country} (type {type(cutoff.country)})"
                        )
                        print(
                            f"  Available keys: {list(matrix[cutoff.visa_class].keys())}"
                        )
            else:
                if cutoff.visa_class == "1st":
                    print(f"  Mismatch Class: '{cutoff.visa_class}'")

        print(f"Total Matches in Matrix: {matches}")

        # Check specific cell
        cell = matrix["1st"][1]["final_action"]  # 1st, ALL, final
        print(f"Matrix['1st'][1]['final_action'] = {cell}")

    except PredictedBulletin.DoesNotExist:
        print(f"No PredictedBulletin found for {year}-{month}")


if __name__ == "__main__":
    debug_predictions(2026, 2)

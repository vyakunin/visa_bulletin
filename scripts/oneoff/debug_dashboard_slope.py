
import os
import sys
import datetime
import django
from dateutil.relativedelta import relativedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.visa_cutoff_date import VisaCutoffDate

def debug_calculation(visa_class, country, action_type, target_date, months_prior):
    simulation_date = target_date - relativedelta(months=months_prior)
    print(f"\n--- Debugging Dashboard Forecast ---")
    print(f"Target Date: {target_date}")
    print(f"Simulation (Prediction) Date: {simulation_date}")
    print(f"Visa: {country} {visa_class} ({action_type})")

    cutoff_12m_ago = simulation_date - datetime.timedelta(days=366)
    
    history = VisaCutoffDate.objects.filter(
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        bulletin__publication_date__lte=simulation_date,
        bulletin__publication_date__gt=cutoff_12m_ago # Optimization for query
    ).order_by('bulletin__publication_date')
    
    recent_points = []
    for h in history:
        if h.cutoff_date:
            recent_points.append((h.bulletin.publication_date, h.cutoff_date))
            print(f"  History Point: {h.bulletin.publication_date} -> {h.cutoff_date}")

    if len(recent_points) < 2:
        print("Not enough points.")
        return

    first_date, first_val = recent_points[0]
    last_date, last_val = recent_points[-1]
    
    months_diff = (last_date.year - first_date.year)*12 + (last_date.month - first_date.month)
    if months_diff < 1: months_diff = 1
    
    days_diff = (last_val - first_val).days
    rate_days_per_month = days_diff / months_diff
    
    print(f"\nCalculation details:")
    print(f"  First Point: {first_date} -> {first_val}")
    print(f"  Last Point:  {last_date} -> {last_val}")
    print(f"  Months Diff: {months_diff}")
    print(f"  Value Diff (Days): {days_diff}")
    print(f"  Rate (Days/Month): {rate_days_per_month:.2f}")
    
    prediction_jump_days = rate_days_per_month * months_prior
    predicted_date = last_val + datetime.timedelta(days=prediction_jump_days)
    print(f"  Prediction Jump (6m): {prediction_jump_days:.2f} days")
    print(f"  Predicted Cutoff: {predicted_date}")

if __name__ == "__main__":
    # India EB-3 Filing, Target April 2021
    from models.enums.country import Country
    debug_calculation("3rd", Country.INDIA.value, "filing", datetime.date(2021, 4, 1), 6)

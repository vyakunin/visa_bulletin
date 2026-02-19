
import os
import django
from datetime import date, timedelta
from statistics import mean
import logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "visa_bulletin.settings")
django.setup()

from lib.business.vqs.accuracy_metrics import compute_bulletin_accuracy, get_bulletins_in_range
from lib.business.vqs.meta_params import VqsMetaParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    base_params = VqsMetaParams.defaults()
    horizon = 6
    years = [2022, 2023, 2024]
    
    all_bulletins = []
    for year in years:
        all_bulletins.extend(get_bulletins_in_range(year, year + 1))
        
    print(f"Evaluating Baseline at Horizon {horizon} for {len(all_bulletins)} bulletins...")
    
    rows = compute_bulletin_accuracy(
        bulletins=all_bulletins,
        meta=base_params,
        horizon=horizon
    )
    
    valid_rows = [r for r in rows if r.error_days is not None]
    valid_rows.sort(key=lambda x: x.error_days, reverse=True)
    
    print(f"\nTop 20 Worst Offenders (Horizon {horizon}):")
    print(f"{'Series':<20} | {'Bulletin':<12} | {'Pred':<12} | {'Actual':<12} | {'Error'}")
    print("-" * 75)
    for r in valid_rows[:20]:
        series = f"{r.visa_class}/{r.country}"
        print(f"{series:<20} | {str(r.bulletin_date):<12} | {str(r.predicted_cutoff):<12} | {str(r.actual_cutoff):<12} | {r.error_days} days")
        
    overall_mae = mean([r.error_days for r in valid_rows])
    print(f"\nOverall MAE (n={len(valid_rows)}): {overall_mae:.2f} days")

if __name__ == "__main__":
    main()

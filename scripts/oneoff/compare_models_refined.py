
import os
import sys
import datetime
import numpy as np
from collections import defaultdict
import django
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin
from models.enums.country import Country

def calculate_metrics(errors):
    if not errors:
        return 0, 0, 0
    mae = np.mean(errors)
    med_ae = np.median(errors)
    mse = np.mean(np.square(errors))
    return mae, med_ae, mse

def run_refined_comparison():
    print("--- Starting Refined Model Comparison (Iter 2): System vs Linear Extrapolation ---")
    print("Grouping: 2023 and all Octobers -> 'NOISY', Rest -> 'REST'")
    
    action_type = "final_action"
    preds = PredictedBulletin.objects.all().order_by('target_bulletin_month')
    
    system_errors = defaultdict(list)
    linear_errors = defaultdict(list)
    
    BASE_DATE = datetime.date(2000, 1, 1)

    for pb in preds:
        target_month = pb.target_bulletin_month
        knowledge_date = pb.prediction_date
        
        # Classification Logic
        is_october = (target_month.month == 10)
        is_2023 = (target_month.year == 2023)
        
        if is_october or is_2023:
            group_key_suffix = "NOISY"
        else:
            group_key_suffix = "REST"

        actual_bulletin = Bulletin.objects.filter(
            publication_date__year=target_month.year,
            publication_date__month=target_month.month
        ).first()
        
        if not actual_bulletin:
            continue
            
        actual_cutoffs = {
            (c.visa_class, c.country): c.cutoff_date 
            for c in actual_bulletin.cutoff_dates.filter(action_type=action_type) 
            if c.cutoff_date
        }
        
        system_preds = {
            (c.visa_class, c.country): c.predicted_date
            for c in pb.cutoffs.filter(action_type=action_type)
            if c.predicted_date
        }
        
        categories_to_test = [
            k for k in actual_cutoffs.keys() 
            if k[0] in ["1st", "2nd", "3rd", "4th", "5th"]
        ]
                
        for key in categories_to_test:
            visa_class, country = key
            actual_date = actual_cutoffs[key]
            
            # --- System Prediction Error ---
            sys_pred = system_preds.get(key)
            if not sys_pred:
                continue
                
            sys_err = abs((sys_pred - actual_date).days)
            
            # --- Linear Baseline ---
            history = VisaCutoffDate.objects.filter(
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                bulletin__publication_date__lt=target_month
            ).filter(
                bulletin__publication_date__lte=knowledge_date
            ).order_by('-bulletin__publication_date')[:24]
            
            X = []
            y = []
            valid_history = [h for h in history if h.cutoff_date]
            
            if len(valid_history) < 6:
                continue
                
            for h in reversed(valid_history):
                m_idx = h.bulletin.publication_date.year * 12 + h.bulletin.publication_date.month
                d_val = (h.cutoff_date - BASE_DATE).days
                X.append(m_idx)
                y.append(d_val)
                
            if len(X) > 1:
                A = np.vstack([X, np.ones(len(X))]).T
                m, c = np.linalg.lstsq(A, y, rcond=None)[0]
                target_idx = target_month.year * 12 + target_month.month
                pred_days = m * target_idx + c
                linear_pred_date = BASE_DATE + datetime.timedelta(days=int(pred_days))
                lin_err = abs((linear_pred_date - actual_date).days)
            else:
                lin_err = abs((valid_history[0].cutoff_date - actual_date).days)

            full_key = (visa_class, country, group_key_suffix)
            system_errors[full_key].append(sys_err)
            linear_errors[full_key].append(lin_err)
            
            agg_key = ("ALL", "ALL", group_key_suffix)
            system_errors[agg_key].append(sys_err)
            linear_errors[agg_key].append(lin_err)

    # --- Reporting ---
    print(f"\n{'Group':<10} {'Metric':<10} {'System':<10} {'Linear':<10} {'Diff':<10}")
    print("-" * 60)

    for group in ["NOISY", "REST"]:
        sys_errs = system_errors[("ALL", "ALL", group)]
        lin_errs = linear_errors[("ALL", "ALL", group)]
        
        if not sys_errs:
            print(f"{group:<10} N/A (No samples)")
            continue
            
        s_mae, s_med, s_mse = calculate_metrics(sys_errs)
        l_mae, l_med, l_mse = calculate_metrics(lin_errs)
        
        print(f"{group:<10} {'MAE':<10} {s_mae:<10.1f} {l_mae:<10.1f} {s_mae-l_mae:<10.1f}")
        print(f"{'':<10} {'MedAE':<10} {s_med:<10.1f} {l_med:<10.1f} {s_med-l_med:<10.1f}")
        print(f"{'':<10} {'MSE':<10} {s_mse:<10.0f} {l_mse:<10.0f} {s_mse-l_mse:<10.0f}")
        print("-" * 60)
        
if __name__ == "__main__":
    run_refined_comparison()

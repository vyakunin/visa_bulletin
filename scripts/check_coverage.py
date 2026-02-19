
import os
import sys
import django
from datetime import date
from dateutil.relativedelta import relativedelta

sys.path.append(".")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.bulletin import Bulletin
from models.vqs import PredictedBulletin

def check():
    start_date = date(2025, 6, 1)
    end_date = date(2026, 5, 1)
    
    current = start_date
    while current <= end_date:
        b = Bulletin.objects.filter(publication_date=current).first()
        pb = PredictedBulletin.objects.filter(target_bulletin_month=current).first()
        
        b_str = "FOUND" if b else "MISSING"
        pb_str = f"FOUND (Know: {pb.prediction_date})" if pb else "MISSING"
        
        print(f"{current.strftime('%B %Y')}: Bulletin={b_str}, Prediction={pb_str}")
        
        current += relativedelta(months=1)

if __name__ == "__main__":
    check()

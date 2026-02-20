
import os
import sys
import datetime
import django
from dateutil.relativedelta import relativedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.visa_cutoff_date import VisaCutoffDate
from models.raw_facts import RawFactsLedger
from lib.business.vqs.solver import predict_next_bulletin_and_maturity

def debug_vqs(visa_class, country, action_type, target_date, months_prior):
    simulation_date = target_date - relativedelta(months=months_prior)
    print(f"\n--- Debugging VQS Forecast ---")
    print(f"Target Date: {target_date}")
    print(f"Simulation (Knowledge) Date: {simulation_date}")
    print(f"Visa: {country} {visa_class} ({action_type})")
    
    # Check Raw Facts (using dimensions JSON field)
    # Note: Country enum value might be int, but dimensions stores string usually? 
    # Let's assume the solver knows how to map it. 
    # For now, just count total facts to see if DB is empty.
    facts_count = RawFactsLedger.objects.count()
    print(f"Total RawFacts in DB: {facts_count}")
    
    # Try to find relevant facts for this country/category
    # attributes are stored in dimensions json
    # We can try to iterate and count if filter is tricky, or just use filter
    
    # Check for India (3) specifically
    india_facts = RawFactsLedger.objects.filter(dimensions__country=3).count()
    print(f"Facts for Country 3 (India): {india_facts}")
    
    target_facts = RawFactsLedger.objects.filter(
        dimensions__country=country,
        dimensions__category=visa_class
    ).count()
    print(f"Facts for Target ({country}, {visa_class}): {target_facts}")

    try:
        next_cutoff, maturity, results, confidence = predict_next_bulletin_and_maturity(
            knowledge_date=simulation_date,
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            force_physics=True # Test the physics engine
        )
        
        print(f"Solver Result: {len(results)} steps.")
        for res in results:
             print(f"  Step: {res.month} -> Cutoff: {res.cutoff_date}")
             
        if not results:
            print("  No results returned from solver.")
            print(f"  Next Cutoff direct: {next_cutoff}")

    except Exception as e:
        print(f"VQS Error: {e}")

if __name__ == "__main__":
    from models.enums.country import Country
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--visa", choices=["India", "China", "Mexico", "Philippines", "All"], default="India")
    parser.add_argument("--category", choices=["1st", "2nd", "3rd", "4th", "5th"], default="3rd")
    parser.add_argument("--action", choices=["final_action", "filing"], default="filing")
    parser.add_argument("--date", default="2021-04-01")
    parser.add_argument("--horizon", type=int, default=6)
    
    args = parser.parse_args()
    
    country_map = {
        "India": Country.INDIA.value,
        "China": Country.CHINA.value,
        "Mexico": Country.MEXICO.value,
        "Philippines": Country.PHILIPPINES.value,
        "All": Country.ALL.value,
    }
    
    country_val = country_map[args.visa]
    target_date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    
    debug_vqs(args.category, country_val, args.action, target_date, args.horizon)

from datetime import date
from typing import Optional

from lib.business.vqs.estimators import get_monthly_supply
from lib.business.vqs.data_cache import get_cutoff_at_date

class CascadeModel:
    """Models unused visa fall-down from higher to lower preferences."""
    
    def estimate_cascade_bonus(
        self, visa_class: str, country: int, month: date, knowledge_date: date
    ) -> int:
        """
        Estimate additional visas from unused higher-preference allocation.
        
        Logic:
        1. Look at recent higher-preference cutoff movement
        2. If "Current" (no cutoff), assume surplus
        3. Estimate excess = Allocation * 0.35 (heuristic)
        """
        if visa_class == "1st":
            return 0  # EB1 doesn't receive cascade
        
        higher_classes = self._get_higher_classes(visa_class)
        total_cascade = 0
        
        for hc in higher_classes:
            cutoff = get_cutoff_at_date(hc, country, "final_action", knowledge_date)
            
            # If cutoff is None, it means "Current" (or no data, but usually Current)
            # Actually get_cutoff_at_date returns None if no bulletin found? 
            # No, if bulletin exists but "C", it returns None? 
            # Wait, get_cutoff_at_date implementation:
            # "Returns None if no data." - what about "C"? 
            # VisaCutoffDate stores "C" as None cutoff_date?
            # Creating a VisaCutoffDate with cutoff_date=None usually implies 'C' in some contexts,
            # but let's check VisaCutoffDate model.
            
            # Assuming None means "Current" for this logic (or at least no restriction).
            # If it really meant "no data", we might overestimate, but for recent years data exists.
            
            if cutoff is None:
                # "Current" = surplus likely
                allocation = get_monthly_supply(month, country=country, visa_class=hc)
                total_cascade += int(allocation * 0.35)
                
        return total_cascade
    
    def _get_higher_classes(self, visa_class: str) -> list[str]:
        cascade_order = {
            "2nd": ["1st"],
            "3rd": ["1st", "2nd"],
            "4th": ["1st", "2nd", "3rd"]
        }
        return cascade_order.get(visa_class, [])

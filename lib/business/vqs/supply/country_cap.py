from datetime import date
from lib.business.vqs.estimators import (
    DEFAULT_ANNUAL_EB_LIMIT,
    PER_COUNTRY_SHARE,
    OVERSUBSCRIBED_COUNTRIES,
)

class CountryCapModel:
    """Applies the 7% per-country cap with fall-down rules."""
    
    def apply_cap(self, country: int, proposed_supply: int, month: date) -> int:
        """
        Apply per-country cap to proposed supply.
        
        Args:
            country: Country enum value
            proposed_supply: Total supply available for this series (base + spillover)
            month: Simulation month
            
        Returns:
            Capped supply
        """
        if country in OVERSUBSCRIBED_COUNTRIES:
            annual_cap = DEFAULT_ANNUAL_EB_LIMIT * PER_COUNTRY_SHARE
            monthly_cap = annual_cap / 12
            # Allow 20% buffer for fall-down from ROW or other unused
            limit = int(monthly_cap * 1.2)
            return min(proposed_supply, limit)
            
        return proposed_supply

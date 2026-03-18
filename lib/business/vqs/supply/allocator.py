from dataclasses import dataclass
from datetime import date

from lib.business.vqs.estimators import get_monthly_supply as get_base_supply_estimator
from lib.business.vqs.supply.cascade import CascadeModel
from lib.business.vqs.supply.country_cap import CountryCapModel
from lib.business.vqs.supply.fb_spillover import FBSpilloverModel


@dataclass
class MonthlySupplyAllocation:
    """Per-series monthly visa supply estimate."""

    visa_class: str
    country: int
    month: date
    base_supply: int  # From statutory allocation
    cascade_bonus: int  # From unused higher-preference visas
    fb_spillover_bonus: int  # From unused family visas
    total: int  # Sum (capped)


class SupplyAllocator:
    """Computes per-series monthly visa supply considering cross-bucket dependencies."""

    def __init__(self):
        self.cascade = CascadeModel()
        self.spillover = FBSpilloverModel()
        self.country_cap = CountryCapModel()

    def get_supply(
        self, visa_class: str, country: int, month: date, knowledge_date: date
    ) -> MonthlySupplyAllocation:
        """Estimate monthly visa supply for a specific series."""

        # 1. Base supply (Statutory + Seasonality)
        # We reuse the existing estimator but stripped of spillover if possible?
        # get_monthly_supply in estimators includes spillover (Layer 5)
        # and EB1 bonus.
        # Ideally we'd use a cleaner base.
        # But for now let's use it and subtract if we want to be pure,
        # or just accept it includes some static spillover and we add dynamic.
        # Actually, get_monthly_supply includes:
        # Layer 5: Spillover (FB -> EB in Q4)
        # We also have FBSpilloverModel doing similar thing.
        # Let's trust the estimator for the base logic for now to avoid divergence.

        base = get_base_supply_estimator(month, country=country, visa_class=visa_class)

        # 2. Dynamic Cascade (New!)
        cascade = self.cascade.estimate_cascade_bonus(
            visa_class, country, month, knowledge_date
        )

        # 3. Dynamic FB Spillover (Refinement)
        # Only add if the base estimator didn't already cover it?
        # The base estimator adds fixed 15% in Q4.
        # Our new model adds 13k/month in Q4.
        # Let's treat FBSpilloverModel as the "extra" or "correction" if we had actual data.
        # Since currently it just returns 13k fixed, let's skip it to avoid double counting
        # UNLESS we move to using real data.
        # For this Phase, the big win is CASCADE.
        fb_bonus = 0

        # 4. Cap
        raw_total = base + cascade + fb_bonus
        final_total = self.country_cap.apply_cap(country, raw_total, month, visa_class)

        return MonthlySupplyAllocation(
            visa_class=visa_class,
            country=country,
            month=month,
            base_supply=base,
            cascade_bonus=cascade,
            fb_spillover_bonus=fb_bonus,
            total=final_total,
        )

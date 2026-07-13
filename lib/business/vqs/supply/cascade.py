from datetime import date

from lib.business.vqs.data_cache import is_current_at_date
from lib.business.vqs.estimators import get_monthly_supply


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
            # A higher preference going "Current" (its annual limit is not binding)
            # frees unused allocation to fall down to lower preferences. Use
            # is_current_at_date, NOT `get_cutoff_at_date(...) is None`: the latter
            # returns the stale last-real cutoff during a Current spell, so this
            # bonus never fired for a Current higher-preference series.
            if is_current_at_date(hc, country, "final_action", knowledge_date):
                allocation = get_monthly_supply(month, country=country, visa_class=hc)
                total_cascade += int(allocation * 0.35)

        return total_cascade

    def _get_higher_classes(self, visa_class: str) -> list[str]:
        cascade_order = {
            "2nd": ["1st"],
            "3rd": ["1st", "2nd"],
            "4th": ["1st", "2nd", "3rd"],
        }
        return cascade_order.get(visa_class, [])

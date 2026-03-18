from datetime import date

from lib.business.vqs.estimators import (
    DEFAULT_ANNUAL_EB_LIMIT,
    OVERSUBSCRIBED_COUNTRIES,
    PER_CLASS_SHARE,
    PER_COUNTRY_SHARE,
)


class CountryCapModel:
    """Applies the 7% per-country cap with fall-down rules."""

    def apply_cap(
        self,
        country: int,
        proposed_supply: int,
        month: date,
        visa_class: str | None = None,
    ) -> int:
        """Apply per-country cap proportional to visa class share.

        The 7% country cap (9800/year) is split across visa classes using INA
        §203(b) shares. Without this, each class could individually consume up
        to the full country cap, allowing 5x overcount in aggregate.
        """
        if country in OVERSUBSCRIBED_COUNTRIES:
            class_share = PER_CLASS_SHARE.get(visa_class, 0.286) if visa_class else 1.0
            annual_cap = DEFAULT_ANNUAL_EB_LIMIT * PER_COUNTRY_SHARE * class_share
            monthly_cap = annual_cap / 12
            limit = int(monthly_cap * 1.2)
            return min(proposed_supply, limit)

        return proposed_supply

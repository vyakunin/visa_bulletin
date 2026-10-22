"""Canonical URL paths for a prediction month — every internal link, canonical tag and
sitemap entry takes its path from here.

Employment-based months live at ``/predictions/<monthname>-<year>/`` for their whole
lifecycle: forecast before the bulletin drops, accuracy archive after, at one URL. The
bare-numeric ``/predictions/<y>-<m>/`` and ``/predictions/employment_based/<y>-<m>/``
aliases 301 there, so a link built in either form spends a redirect.
"""

from datetime import date

from models.enums.visa_category import VisaCategory

MONTH_SLUGS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def forecast_url_for(target: date) -> str:
    return f"/predictions/{MONTH_SLUGS[target.month - 1]}-{target.year}/"


def prediction_canonical_path(category: str, year: int, month: int) -> str:
    """Family-sponsored keeps its own self-canonical ``/predictions/family_sponsored/<y>-<m>/``."""
    if category == VisaCategory.EMPLOYMENT_BASED.value:
        return forecast_url_for(date(year, month, 1))
    return f"/predictions/{category}/{year}-{month}/"

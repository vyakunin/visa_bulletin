"""Anonymous personalization — server side of the "your date moved" return banner.

Builds a small, stable list of predicted-cutoff records that a prediction page
bakes into the DOM (via Django's ``json_script``). The client
(``static/js/retention_banner.js``) stores these per browser in ``localStorage``
and, on a RETURN visit, shows a dismissible "your date moved" banner when a
series it has seen before now shows a different predicted cutoff. Purely
client-side + anonymous: no backend write, no cookie, no PII.

The comparison KEY must be stable across the URL-canonicalization scheme (the
month prediction pages were consolidated to a single canonical URL) AND
consistent across BOTH surfaces that emit records — the
``/predictions/<month>-<year>/`` forecast page and the
``/employment-based/<country>/`` (and family-sponsored) dashboards — so a series
seen on one page is matched on the other. It is therefore built from the
underlying enum values (category / country / visa_class / action_type), NEVER
from the request path.
"""

from __future__ import annotations

from datetime import date

from models.enums.action_type import ActionType
from models.enums.country import Country

# EB preference code -> short display label. Matches the stored visa_class values
# ("1st".."5th") used by both the forecast page and the dashboard aggregation, so
# a series lines up across the two surfaces. Family-sponsored codes ("F1".."F4")
# are already short and are used verbatim.
_EB_SHORT = {"1st": "EB-1", "2nd": "EB-2", "3rd": "EB-3", "4th": "EB-4", "5th": "EB-5"}

_ACTION_LABEL = {
    ActionType.FINAL_ACTION.value: "Final Action",
    ActionType.FILING.value: "Dates for Filing",
}

# Record status values (also mirrored in retention_banner.js).
STATUS_DATE = "date"            # a concrete predicted cutoff date
STATUS_CURRENT = "current"      # no backlog / "Current"
STATUS_UNAVAILABLE = "unavailable"  # category hit its FY annual limit


def retention_key(category: str, country_value: int, visa_class: str, action_type: str) -> str:
    """Stable, URL-independent comparison key for one predicted series."""
    return f"{category}|{country_value}|{visa_class}|{action_type}"


def _class_short(visa_class: str) -> str:
    return _EB_SHORT.get(visa_class, visa_class)


def _country_short(country_value: int) -> str:
    try:
        return Country(country_value).label.split(" (")[0]
    except ValueError:
        return "your country"


def series_label(category: str, country_value: int, visa_class: str, action_type: str) -> str:
    """Human subject phrase for the banner, e.g. "the EB-2 India Final Action cutoff"."""
    action = _ACTION_LABEL.get(action_type, "cutoff")
    return f"the {_class_short(visa_class)} {_country_short(country_value)} {action} cutoff"


def make_record(
    category: str,
    country_value: int,
    visa_class: str,
    action_type: str,
    *,
    status: str,
    predicted_date: date | None,
) -> dict:
    """One baked record. Keys are terse (repeated in-page for every series)."""
    return {
        "k": retention_key(category, country_value, visa_class, action_type),
        "l": series_label(category, country_value, visa_class, action_type),
        "s": status,
        "d": predicted_date.isoformat() if predicted_date else None,
    }

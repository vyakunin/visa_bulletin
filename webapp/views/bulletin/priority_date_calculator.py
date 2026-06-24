"""Interactive Green Card Priority Date Calculator (/priority-date-calculator/).

SEO + utility page for the "priority date calculator" / "green card priority
date calculator" / "visa bulletin calculator" cluster — real GSC demand (the
head term "priority date calculator" pulls clicks at pos ~5 onto pages that
aren't a calculator; ~2,800 impressions/28d across the cluster) with NO matching
page on the site until now.

The page bakes the latest bulletin's full Final Action + Dates-for-Filing cutoff
matrix (EB-1..EB-5 + F1..F4 x five chargeability areas) into the HTML as JSON;
the "is my priority date current?" comparison runs entirely client-side, so the
page is CHEAP (one query for the latest bulletin's rows) and fully cacheable. No
live VQS solver — "when will it become current" is LINKED to the prediction +
per-country landing pages, not embedded.
"""

import json

from django.shortcuts import render

from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.employment_preference import EmploymentPreference
from models.enums.family_preference import FamilyPreference
from models.enums.visa_category import VisaCategory
from models.visa_cutoff_date import VisaCutoffDate

# Calculator dropdown — ordered (key, short label, long label, group). Only keys
# that actually have data in the latest bulletin are surfaced (see the view).
_CALC_CATEGORIES = [
    ("eb1", "EB-1", "EB-1: Priority Workers", "Employment-based"),
    ("eb2", "EB-2", "EB-2: Professionals with Advanced Degrees", "Employment-based"),
    ("eb3", "EB-3", "EB-3: Skilled Workers & Professionals", "Employment-based"),
    ("eb3ow", "EB-3 Other Workers", "EB-3: Other Workers", "Employment-based"),
    ("eb4", "EB-4", "EB-4: Special Immigrants", "Employment-based"),
    ("eb5", "EB-5", "EB-5: Immigrant Investors (Unreserved)", "Employment-based"),
    ("f1", "F1", "F1: Unmarried Sons/Daughters of U.S. Citizens", "Family-sponsored"),
    ("f2a", "F2A", "F2A: Spouses/Children of Permanent Residents", "Family-sponsored"),
    ("f2b", "F2B", "F2B: Unmarried Sons/Daughters (21+) of LPRs", "Family-sponsored"),
    ("f3", "F3", "F3: Married Sons/Daughters of U.S. Citizens", "Family-sponsored"),
    ("f4", "F4", "F4: Siblings of Adult U.S. Citizens", "Family-sponsored"),
]

# Normalized EB display label -> calculator key (EmploymentPreference.normalize_for_display).
_EB_LABEL_TO_KEY = {
    "EB-1: Priority Workers": "eb1",
    "EB-2: Professionals with Advanced Degrees": "eb2",
    "EB-3: Skilled Workers, Professionals": "eb3",
    "EB-3: Other Workers": "eb3ow",
    "EB-4: Special Immigrants": "eb4",
}
# EB-5 splits into several sub-lines in recent bulletins; the calculator surfaces
# the main "Unreserved" figure (what people mean by "EB-5"), falling back to the
# pre-split "All Categories" line for older bulletins. Lower index = preferred.
_EB5_PREFERENCE = ["EB-5: Unreserved", "EB-5: All Categories"]

_FAMILY_KEYS = {"F1": "f1", "F2A": "f2a", "F2B": "f2b", "F3": "f3", "F4": "f4"}

# Chargeability areas the calculator offers, in search-interest order. India/China
# carry the backlog demand; "All Other Countries" (Country.ALL) is the ROW default.
_CALC_COUNTRIES = [
    (Country.ALL, "All Other Countries"),
    (Country.INDIA, "India"),
    (Country.CHINA, "China"),
    (Country.MEXICO, "Mexico"),
    (Country.PHILIPPINES, "Philippines"),
]

# EB classes / countries that have a dedicated per-country landing page, so the
# calculator can deep-link "see the full trend + history" for the chosen combo.
_LANDING_EB = {"eb1", "eb2", "eb3"}
_LANDING_COUNTRY_SLUG = {
    Country.INDIA.value: "india",
    Country.CHINA.value: "china",
    Country.MEXICO.value: "mexico",
    Country.PHILIPPINES.value: "philippines",
}


def _status_from_row(row: VisaCutoffDate) -> dict:
    """A single cutoff cell: Current / Unavailable / a real date / no data."""
    if row.is_current:
        return {"status": "current", "display": "Current", "iso": None}
    if row.is_unavailable:
        return {"status": "unavailable", "display": "Unavailable", "iso": None}
    if row.cutoff_date:
        return {
            "status": "date",
            "display": row.cutoff_date.strftime("%B %-d, %Y"),
            "iso": row.cutoff_date.isoformat(),
        }
    return {"status": "none", "display": row.cutoff_value or "No data", "iso": None}


def _category_key_for_row(row: VisaCutoffDate) -> str | None:
    """Map a bulletin row to a calculator category key, or None if unsupported."""
    if row.visa_category == VisaCategory.EMPLOYMENT_BASED:
        norm = EmploymentPreference.normalize_for_display(row.visa_class)
        if norm in _EB_LABEL_TO_KEY:
            return _EB_LABEL_TO_KEY[norm]
        if norm in _EB5_PREFERENCE:
            return "eb5"
        return None
    if row.visa_category == VisaCategory.FAMILY_SPONSORED:
        fam = FamilyPreference.normalize_legacy_name((row.visa_class or "").strip())
        return _FAMILY_KEYS.get(fam)
    return None


def _build_matrix() -> tuple[dict, str]:
    """Bake {cat_key: {country_value: {"final"|"filing": status}}} from the latest bulletin.

    One query (latest bulletin rows for the five offered countries). Returns the
    matrix plus the bulletin month label. EB-5 collapses its sub-lines to the
    preferred Unreserved/All-Categories figure (see _EB5_PREFERENCE).
    """
    latest = Bulletin.objects.order_by("-publication_date").first()
    if latest is None:
        return {}, ""

    wanted_countries = [c.value for c, _ in _CALC_COUNTRIES]
    rows = VisaCutoffDate.objects.filter(bulletin=latest, country__in=wanted_countries)

    matrix: dict[str, dict[str, dict[str, dict]]] = {}
    eb5_rank: dict[tuple[str, str], int] = {}  # (country, action) -> chosen precedence
    for row in rows:
        if row.action_type == ActionType.FINAL_ACTION.value:
            action = "final"
        elif row.action_type == ActionType.FILING.value:
            action = "filing"
        else:
            continue

        cat_key = _category_key_for_row(row)
        if cat_key is None:
            continue

        cval = str(row.country)
        slot = matrix.setdefault(cat_key, {}).setdefault(cval, {})

        if cat_key == "eb5":
            norm = EmploymentPreference.normalize_for_display(row.visa_class)
            rank = _EB5_PREFERENCE.index(norm) if norm in _EB5_PREFERENCE else len(_EB5_PREFERENCE)
            if action in slot and eb5_rank.get((cval, action), 99) <= rank:
                continue  # keep the better-ranked sub-line already stored
            eb5_rank[(cval, action)] = rank

        slot[action] = _status_from_row(row)

    return matrix, latest.publication_date.strftime("%B %Y")


def _faq(bulletin_month: str) -> list[dict]:
    return [
        {
            "q": "How do I use this priority date calculator?",
            "a": (
                "Pick your green-card category (EB-1/EB-2/EB-3, EB-4, EB-5, or a "
                "family F-category) and your country of chargeability, then enter "
                "your priority date. The calculator compares it to the Final Action "
                f"and Dates-for-Filing cutoffs in the {bulletin_month} U.S. Visa "
                "Bulletin and tells you whether your date is current."
            ),
        },
        {
            "q": "What does it mean for my priority date to be “current”?",
            "a": (
                "Your priority date is current when it is earlier than the Final "
                "Action cutoff for your category and country in the latest Visa "
                "Bulletin — at that point a green-card number is available and "
                "USCIS or the consulate can approve your case. If the category shows "
                "“Current” (C), there is no backlog at all."
            ),
        },
        {
            "q": "Where do I find my priority date?",
            "a": (
                "It is printed on your I-140 or I-130 approval notice (Form I-797). "
                "For PERM-based employment cases it is the date your labor "
                "certification was filed with the Department of Labor."
            ),
        },
        {
            "q": "What is the difference between Final Action and Dates for Filing?",
            "a": (
                "Final Action Dates govern when USCIS or the consulate can approve "
                "the green card. Dates for Filing govern when you may submit the "
                "application (Form I-485 / DS-260) and are usually ahead of Final "
                "Action Dates, so you can often file before your case can be approved."
            ),
        },
    ]


def priority_date_calculator_view(request):
    """Render the interactive green-card priority-date calculator."""
    matrix, bulletin_month = _build_matrix()

    # Only offer categories/countries that actually have data this month.
    categories = [
        {"key": key, "short": short, "long": long_label, "group": group}
        for key, short, long_label, group in _CALC_CATEGORIES
        if key in matrix
    ]
    countries = [
        {"value": str(c.value), "label": label}
        for c, label in _CALC_COUNTRIES
        if any(str(c.value) in matrix.get(cat["key"], {}) for cat in categories)
    ]

    page_title = "Priority Date Calculator: Is My Green Card Date Current?"
    page_heading = "Green Card Priority Date Calculator"
    page_description = (
        "Free priority date calculator: enter your priority date, category, and "
        f"country to check if it is current in the {bulletin_month} U.S. Visa "
        "Bulletin (Final Action and Dates for Filing)."
    )
    canonical_url = request.build_absolute_uri(request.path)
    faq = _faq(bulletin_month)
    structured_data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in faq
        ],
    }

    # Client-side config: the cutoff matrix + the deep-link maps for "see the full
    # trend" (per-country landing) once a combo is chosen.
    calc_config = {
        "month": bulletin_month,
        "matrix": matrix,
        "landingEb": sorted(_LANDING_EB),
        "landingCountrySlug": _LANDING_COUNTRY_SLUG,
    }

    context = {
        "page_title": page_title,
        "page_heading": page_heading,
        "page_description": page_description,
        "canonical_url": canonical_url,
        "og_url": canonical_url,
        "structured_data": json.dumps(structured_data),
        "bulletin_month": bulletin_month,
        "categories": categories,
        "countries": countries,
        "faq": faq,
        "calc_config_json": json.dumps(calc_config),
    }
    return render(request, "webapp/priority_date_calculator.html", context)

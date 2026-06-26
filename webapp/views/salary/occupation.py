"""{occupation} H-1B & PERM salary landing pages.

A curated pSEO page type that gives clean, head-term salary landing pages keyed
off the DOL SOC occupation code — capturing demand ("software engineer h1b
salary", "data scientist salary") that the cluster-derived /job-title/ pages miss
because clustering mangles common titles (see lib/business/salary/soc_occupations).

  /h1b-salary/                -> occupation index/hub
  /h1b-salary/<slug>/         -> one occupation's salary page
  /h1b-salary/<alias>/        -> 301 to the canonical occupation slug
"""

import json
from datetime import datetime

from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render

from django_config.cache_utils import cache_page_skip_bots
from lib.business.salary.market_overview import get_salary_explore_links
from lib.business.salary.occupation_stats import (
    get_occupation_stats,
    occupation_filing_count,
    occupation_qualifies,
    qualifying_occupation_slugs,
)
from lib.business.salary.soc_occupations import (
    Occupation,
    all_occupations,
    get_occupation,
    resolve_alias,
)
from lib.utils.location_utils import US_STATES

_STATE_CODE_TO_NAME = dict(US_STATES)


def _cache(timeout_seconds: int):
    """Cache the view unless running tests (test DB name starts with test_)."""
    db_name = settings.DATABASES.get("default", {}).get("NAME") or ""
    if db_name.startswith("test_"):

        def _decorator(view_func):
            return view_func

        return _decorator
    return cache_page_skip_bots(timeout_seconds)


def _build_faq(occ: Occupation, stats) -> list[dict]:
    """Q&A pairs rendered on-page AND emitted as FAQPage JSON-LD."""
    median = stats.percentiles.get("p50") or 0
    p10 = stats.percentiles.get("p10") or 0
    p90 = stats.percentiles.get("p90") or 0
    top_emp = (
        stats.top_employers[0]["employer__canonical_cluster__canonical_name"]
        if stats.top_employers
        else None
    )
    faq = [
        {
            "q": f"How much does a {occ.display} make on a visa-sponsored job in the US?",
            "a": (
                f"Across {stats.total_filings:,} H-1B and PERM filings, the median "
                f"certified salary for a {occ.display} is ${median:,.0f} per year, "
                f"with most offers between ${p10:,.0f} (10th percentile) and "
                f"${p90:,.0f} (90th percentile)."
            ),
        },
        {
            "q": f"What is the salary range for a {occ.display}?",
            "a": (
                f"The 25th–75th percentile range is "
                f"${stats.percentiles.get('p25', 0):,.0f}–"
                f"${stats.percentiles.get('p75', 0):,.0f}, based on U.S. Department "
                f"of Labor disclosure data for sponsored {occ.display} roles."
            ),
        },
    ]
    if top_emp:
        faq.append(
            {
                "q": f"Which companies sponsor the most {occ.display} visas?",
                "a": (
                    f"{top_emp} files the most {occ.display} sponsorship cases in the "
                    f"dataset. The page lists the top {len(stats.top_employers)} "
                    f"sponsoring employers with their filing counts and average wages."
                ),
            }
        )
    return faq


def _build_jsonld(occ: Occupation, stats, faq: list[dict], canonical: str) -> str:
    """Occupation + FAQPage schema.org JSON-LD for the page."""
    median = stats.percentiles.get("p50") or 0
    graph = [
        {
            "@type": "Occupation",
            "name": occ.display,
            "description": occ.blurb,
            "occupationLocation": {"@type": "Country", "name": "United States"},
            "estimatedSalary": {
                "@type": "MonetaryAmountDistribution",
                "name": "base",
                "currency": "USD",
                "duration": "P1Y",
                "percentile10": stats.percentiles.get("p10") or 0,
                "median": median,
                "percentile90": stats.percentiles.get("p90") or 0,
            },
        },
        {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
                }
                for item in faq
            ],
        },
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph})


@_cache(settings.CACHE_TIMEOUT)
def occupation_salary_view(request, slug: str):
    """One occupation's H-1B & PERM salary page (gated on a substantive dataset)."""
    occ = get_occupation(slug)
    if occ is None:
        # An alias slug (colloquial term / SOC-version spelling) -> canonical page.
        canonical = resolve_alias(slug)
        if canonical is not None:
            return redirect("occupation_salary", slug=canonical.slug, permanent=True)
        raise Http404(f"Occupation '{slug}' not found")

    filing_count = occupation_filing_count(occ)
    if not occupation_qualifies(filing_count):
        # Too thin to publish a non-duplicate page.
        raise Http404(f"Occupation '{slug}' has too few filings to publish")

    stats = get_occupation_stats(occ)

    # Decorate top states with full names for display.
    for row in stats.top_states:
        row["state_name"] = _STATE_CODE_TO_NAME.get(
            row["worksite_state"], row["worksite_state"]
        )

    median = stats.percentiles.get("p50") or 0
    year = datetime.now().year
    seo_title = (
        f"{occ.display} H-1B & PERM Salary {year}: "
        f"Median ${median:,.0f} ({stats.total_filings:,} filings)"
    )[:120]
    seo_desc = (
        f"{occ.display} visa-sponsored salary from U.S. DOL data: "
        f"${median:,.0f} median across {stats.total_filings:,} H-1B and PERM "
        f"filings. Percentiles, top sponsoring employers, states, and trends."
    )[:160]
    canonical = request.build_absolute_uri(request.path)

    faq = _build_faq(occ, stats)
    context = {
        "occ": occ,
        "stats": stats,
        "faq": faq,
        "jsonld": _build_jsonld(occ, stats, faq, canonical),
        "explore_links": get_salary_explore_links(),
        "current_year": year,
        "page_title": seo_title,
        "page_description": seo_desc,
        "canonical_url": canonical,
        "seo": {
            "title": seo_title,
            "description": seo_desc,
            "canonical_url": canonical,
        },
    }
    return render(request, "webapp/occupation_salary.html", context)


@_cache(settings.CACHE_TIMEOUT)
def occupation_index_view(request):
    """Hub listing every published occupation salary page (/h1b-salary/)."""
    published = set(qualifying_occupation_slugs())
    occupations = [o for o in all_occupations() if o.slug in published]
    canonical = request.build_absolute_uri(request.path)
    seo_title = "H-1B & PERM Salary by Occupation — DOL Salary Database"
    seo_desc = (
        "Browse median visa-sponsored salaries by occupation — software engineer, "
        "data scientist, financial analyst, and more — from U.S. DOL H-1B and PERM "
        "disclosure data."
    )[:160]
    context = {
        "occupations": occupations,
        "explore_links": get_salary_explore_links(),
        "page_title": seo_title,
        "page_description": seo_desc,
        "canonical_url": canonical,
        "seo": {
            "title": seo_title,
            "description": seo_desc,
            "canonical_url": canonical,
        },
    }
    return render(request, "webapp/occupation_index.html", context)

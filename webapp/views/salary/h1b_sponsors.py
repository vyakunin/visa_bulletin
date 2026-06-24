"""Top-H-1B-sponsors-per-role landing pages (``/h1b-sponsors/<job-title-slug>/``).

A dedicated ranked leaderboard answering the high-intent query the existing
pages don't: "top H-1B sponsors for {role}" / "which companies sponsor H-1B for
{role}". The ``/job-title/<slug>/`` profile is salary-stats-first and the
``/salaries/by-state/`` page is state-first; neither is a clean ranked
"companies that sponsor H-1B for X" answer, so this is a new page, not a
duplicate.

Deliberately cheap to render — a handful of indexed, single-cluster aggregates
(no live solver, no full scan). Roles without a substantive H-1B leaderboard
404 (no thin pages); the qualification gate is shared with the sitemap
(``lib/business/salary/h1b_sponsors.py``) so the sitemap never lists a 404.
"""

import json

from django.conf import settings
from django.db.models import Max
from django.http import Http404
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from lib.business.salary.common_stats import calculate_salary_percentiles
from lib.business.salary.h1b_sponsors import (
    _h1b_role_base,
    role_h1b_stats,
    role_qualifies,
    top_sponsors_for_cluster,
    top_states_for_cluster,
)
from lib.utils.location_utils import US_STATES
from models.job_title import JobTitleCluster

# 2-letter code -> display name, for the top-states block.
_STATE_NAMES = {code: name for code, name in US_STATES}


def _money(value) -> str | None:
    return f"${value:,.0f}" if value else None


def _faq(title: str, filings: int, sponsors: int, top_rows: list[dict],
         median: str | None, p25: str | None, p75: str | None,
         top_states: list[dict], fy: int | None) -> list[dict]:
    top_names = [r["employer__canonical_cluster__canonical_name"] for r in top_rows[:3]]
    top_names_str = ", ".join(top_names) if top_names else "a range of employers"
    fy_str = f"FY{fy}" if fy else "recent fiscal years"

    pay_a = (
        f"The median certified H-1B wage for {title} roles is {median}."
        if median else
        f"H-1B wages for {title} roles vary by employer and location."
    )
    if p25 and p75:
        pay_a += f" The middle 50% of offers fall between {p25} and {p75}."

    states = [
        f"{_STATE_NAMES.get(s['worksite_state'], s['worksite_state'])}"
        for s in top_states[:3]
    ]
    where_a = (
        f"Most H-1B {title} filings are concentrated in {', '.join(states)}."
        if states else
        f"H-1B {title} filings are spread across many U.S. states."
    )

    return [
        {
            "q": f"Which companies sponsor H-1B visas for {title}?",
            "a": (
                f"{sponsors:,} employers filed certified H-1B labor condition "
                f"applications for {title} roles ({fy_str}). The top sponsors by "
                f"filing volume include {top_names_str}. The full ranked list is "
                f"below."
            ),
        },
        {
            "q": f"What do H-1B {title} jobs pay?",
            "a": pay_a,
        },
        {
            "q": f"Where are H-1B {title} jobs located?",
            "a": where_a,
        },
        {
            "q": "How is this ranking calculated?",
            "a": (
                f"Employers are ranked by the number of certified H-1B Labor "
                f"Condition Applications (LCAs) they filed for {title} roles, "
                f"sourced from U.S. Department of Labor public disclosure data. "
                f"This page reflects {filings:,} H-1B filings for the role."
            ),
        },
    ]


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def h1b_sponsors_landing_view(request, slug: str):
    """Render the per-role 'Top H-1B sponsors' leaderboard page."""
    try:
        cluster = JobTitleCluster.objects.get(slug=slug)
    except JobTitleCluster.DoesNotExist:
        raise Http404("Unknown role")

    # Cheap 404-gate, shared with the sitemap: no thin/duplicate pages.
    filings, sponsors = role_h1b_stats(cluster.id)
    if not role_qualifies(filings, sponsors):
        raise Http404("Not enough H-1B data for this role")

    title = cluster.canonical_title
    top_rows = top_sponsors_for_cluster(cluster.id)
    top_states = top_states_for_cluster(cluster.id)

    base_qs = _h1b_role_base(cluster.id)
    percentiles = calculate_salary_percentiles(base_qs)
    fy = base_qs.aggregate(fy=Max("fiscal_year"))["fy"]

    median = _money(percentiles.get("p50") if percentiles else None)
    p25 = _money(percentiles.get("p25") if percentiles else None)
    p75 = _money(percentiles.get("p75") if percentiles else None)

    # Ranked rows for the template: rank, employer, filings, mean wage.
    sponsor_rows = [
        {
            "rank": i + 1,
            "name": r["employer__canonical_cluster__canonical_name"],
            "slug": r["employer__canonical_cluster__slug"],
            "filings": r["filings"],
            "avg_salary": _money(r["avg_salary"]),
        }
        for i, r in enumerate(top_rows)
    ]
    state_rows = [
        {
            "code": s["worksite_state"],
            "name": _STATE_NAMES.get(s["worksite_state"], s["worksite_state"]),
            "filings": s["filings"],
        }
        for s in top_states
    ]

    fy_str = f"FY{fy}" if fy else None
    page_heading = f"Top H-1B Sponsors for {title}"
    # <title> ≤60 chars: append the FY suffix only when it still fits.
    title_with_fy = f"{page_heading} ({fy_str})" if fy_str else page_heading
    page_title = title_with_fy if len(title_with_fy) <= 60 else page_heading

    median_clause = f" Median H-1B wage {median}." if median else ""
    page_description = (
        f"The {sponsors:,} companies that sponsor H-1B visas for {title}, ranked "
        f"by filing volume from U.S. DOL data ({filings:,} filings)."
        f"{median_clause}"
    )[:155]

    canonical_url = request.build_absolute_uri(request.path)
    faq = _faq(title, filings, sponsors, top_rows, median, p25, p75, top_states, fy)
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

    context = {
        "page_title": page_title,
        "page_heading": page_heading,
        "page_description": page_description,
        "canonical_url": canonical_url,
        "og_url": canonical_url,
        "structured_data": json.dumps(structured_data),
        "title": title,
        "slug": slug,
        "fy_str": fy_str,
        "total_filings": filings,
        "total_sponsors": sponsors,
        "median_salary": median,
        "p25_salary": p25,
        "p75_salary": p75,
        "sponsor_rows": sponsor_rows,
        "state_rows": state_rows,
        "faq": faq,
        "profile_url": f"/job-title/{slug}/",
    }
    return render(request, "webapp/h1b_sponsors_landing.html", context)

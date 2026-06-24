"""Per-(employer × role) H-1B salary pages (``/h1b-salary/<employer>/<role>/``).

Answers the high-intent query the employer-wide and role-wide profiles don't:
**"{role} salary at {employer}" / "does {employer} sponsor H-1B for {role}"**.
A dedicated page for one (employer cluster, job-title cluster) pair: salary
distribution, filing trend, worksite states, and how the pair's pay compares to
the role's market-wide median.

Deliberately cheap — a handful of indexed, single-pair aggregates (no live
solver, no full scan). Pairs without a substantive salary distribution 404 (no
thin pages); the gate is shared with the sitemap
(``lib/business/salary/h1b_salary_pair.py``) so the sitemap never lists a 404.
"""

import json

from django.conf import settings
from django.db.models import Max, Min
from django.http import Http404
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from lib.business.salary.common_stats import calculate_salary_percentiles
from lib.business.salary.h1b_salary_pair import (
    _h1b_pair_base,
    pair_filings_by_year,
    pair_h1b_filings,
    pair_qualifies,
    pair_top_states,
)
from lib.business.salary.h1b_sponsors import _h1b_role_base
from lib.utils.location_utils import US_STATES
from models.job_title import JobTitleCluster
from models.salary import EmployerCluster

_STATE_NAMES = {code: name for code, name in US_STATES}


def _money(value) -> str | None:
    return f"${value:,.0f}" if value else None


def _faq(employer: str, role: str, filings: int, median: str | None,
         p25: str | None, p75: str | None, fy: int | None,
         vs_role: str | None) -> list[dict]:
    fy_str = f"FY{fy}" if fy else "recent fiscal years"
    pay_a = (
        f"The median certified H-1B wage for {role} at {employer} is {median}."
        if median else
        f"H-1B wages for {role} at {employer} vary by level and location."
    )
    if p25 and p75:
        pay_a += f" The middle 50% of offers fall between {p25} and {p75}."
    if vs_role:
        pay_a += f" That is {vs_role} the market-wide median for {role}."

    return [
        {
            "q": f"Does {employer} sponsor H-1B visas for {role}?",
            "a": (
                f"Yes — {employer} filed {filings:,} certified H-1B labor "
                f"condition applications for {role} roles ({fy_str}), per U.S. "
                f"Department of Labor disclosure data."
            ),
        },
        {
            "q": f"What does {employer} pay {role} on an H-1B?",
            "a": pay_a,
        },
        {
            "q": "How is this data sourced?",
            "a": (
                f"From certified H-1B Labor Condition Applications (LCAs) filed by "
                f"{employer} for {role} roles, in U.S. Department of Labor public "
                f"disclosure files. Wages shown are the offered annual wage on the "
                f"filing, not a guarantee of pay. This page reflects {filings:,} "
                f"H-1B filings."
            ),
        },
    ]


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def h1b_salary_pair_view(request, employer: str, role: str):
    """Render the per-(employer × role) H-1B salary page."""
    try:
        emp = EmployerCluster.objects.get(slug=employer)
    except EmployerCluster.DoesNotExist:
        raise Http404("Unknown employer")
    try:
        jt = JobTitleCluster.objects.get(slug=role)
    except JobTitleCluster.DoesNotExist:
        raise Http404("Unknown role")

    # Cheap 404-gate, shared with the sitemap: no thin/duplicate pages.
    filings = pair_h1b_filings(emp.id, jt.id)
    if not pair_qualifies(filings):
        raise Http404("Not enough H-1B data for this employer/role pair")

    emp_name = emp.canonical_name
    role_title = jt.canonical_title

    base_qs = _h1b_pair_base(emp.id, jt.id)
    percentiles = calculate_salary_percentiles(base_qs)
    bounds = base_qs.aggregate(fy=Max("fiscal_year"), lo=Min("wage_annual"),
                               hi=Max("wage_annual"))
    fy = bounds["fy"]

    median_val = percentiles.get("p50") if percentiles else None
    median = _money(median_val)
    p25 = _money(percentiles.get("p25") if percentiles else None)
    p75 = _money(percentiles.get("p75") if percentiles else None)

    # Comparison: pair median vs the role's market-wide H-1B median (all
    # employers) — the non-duplicative insight ("pays X% above the market").
    role_pct = calculate_salary_percentiles(_h1b_role_base(jt.id))
    role_median_val = role_pct.get("p50") if role_pct else None
    vs_role = None
    role_median_label = _money(role_median_val)
    if median_val and role_median_val:
        diff = (median_val - role_median_val) / role_median_val
        if abs(diff) < 0.02:
            vs_role = "about the same as"
        else:
            vs_role = f"{abs(diff) * 100:.0f}% {'above' if diff > 0 else 'below'}"

    year_rows = [
        {"year": r["fiscal_year"], "filings": r["filings"]}
        for r in pair_filings_by_year(emp.id, jt.id)
        if r["fiscal_year"]
    ]
    state_rows = [
        {
            "code": s["worksite_state"],
            "name": _STATE_NAMES.get(s["worksite_state"], s["worksite_state"]),
            "filings": s["filings"],
            "avg_salary": _money(s["avg_salary"]),
        }
        for s in pair_top_states(emp.id, jt.id)
    ]

    fy_str = f"FY{fy}" if fy else None
    page_heading = f"{role_title} Salary at {emp_name} (H-1B)"
    # <title> ≤60 chars: fall back to a shorter form when the names are long.
    page_title = page_heading
    if len(page_title) > 60:
        page_title = f"{role_title} at {emp_name} — H-1B Salary"
    if len(page_title) > 60:
        page_title = f"H-1B Salary: {role_title} at {emp_name}"[:60]

    vs_clause = f" {vs_role} the {role_title} market median." if vs_role else ""
    page_description = (
        f"{emp_name} pays a median {median or 'competitive'} H-1B wage for "
        f"{role_title} ({filings:,} certified filings).{vs_clause}"
    )[:155]

    canonical_url = request.build_absolute_uri(request.path)
    faq = _faq(emp_name, role_title, filings, median, p25, p75, fy,
               vs_role + f" the market median" if vs_role else None)
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
        "employer_name": emp_name,
        "role_title": role_title,
        "fy_str": fy_str,
        "total_filings": filings,
        "median_salary": median,
        "p25_salary": p25,
        "p75_salary": p75,
        "min_salary": _money(bounds["lo"]),
        "max_salary": _money(bounds["hi"]),
        "percentiles": percentiles,
        "role_median": role_median_label,
        "vs_role": vs_role,
        "year_rows": year_rows,
        "state_rows": state_rows,
        "faq": faq,
        "employer_url": f"/employer/{employer}/",
        "role_url": f"/job-title/{role}/",
        "sponsors_url": f"/h1b-sponsors/{role}/",
    }
    return render(request, "webapp/h1b_salary_pair_landing.html", context)

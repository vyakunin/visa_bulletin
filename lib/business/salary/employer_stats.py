"""Employer-profile indexability gate.

The `/employer/<slug>/` surface is programmatic: every employer cluster with a
slug gets a page, so the long tail dwarfs the head. Measured on prod 2026-07-27
over the 233,445 slugged clusters:

    lifetime filings │ clusters
    ─────────────────┼──────────
    0                │    3,550
    1-4              │  197,675
    5-9              │   16,133
    10-49            │   12,462
    50-99            │    1,915
    100+             │    1,710

So ~93% of the surface carries fewer than 10 filings. Those pages render with
all-zero stats, a blank median and "Chart data not available" — nothing for a
searcher to do, and the scaled-content-abuse / "low value content" shape that
the sibling job-title gate (`job_title_stats.INDEXABLE_MIN_FILINGS`) has been
guarding on its own surface all along.

Two thin conditions matter, and they are NOT the same:

1. **Lifetime count below the threshold** — the cluster has almost no data in
   the first place. Filter-independent, so the sitemap can evaluate it too.
2. **Zero filings in the RENDERED window** — the profile defaults to the last 5
   fiscal years, so a cluster whose only filings are older renders a completely
   empty page even though its lifetime count is non-zero. This is why the
   original audit counted ~203k "zero-filing" pages while only 3,550 clusters
   have a lifetime count of 0.

`is_thin_employer_profile` covers both. The view uses it for `meta_robots` and
for the `data-vb-thin` body flag.

The sitemap can only evaluate condition 1: `EmployerCluster` stores the two
lifetime counters but no last-filing year, so nothing here can tell whether a
cluster's filings land inside the rendered window without scanning
`salary_record`. The two gates therefore disagree in one direction: a cluster
above the threshold whose filings are all older than the window is advertised
by the sitemap AND noindexed by the view. That wastes crawl budget on those
URLs; it does not leak a thin page into the index. Closing it needs a
denormalized last-filing year on the cluster — unmeasured, so the size of that
set is unknown.

`data-vb-thin` is the seam for suppressing ads on thin pages, and it is load
bearing: AdSense evaluates pages that SERVE ads, reached by Mediapartners-Google
via the ad request itself, so the Search-side noindex does not cover that
exposure. `ad_slot.html` — private ops repo, bind-mounted over
`webapp/templates/webapp/includes/` in prod — reads the attribute and returns
before the first `setupSlot()`, which withholds `adsbygoogle.js` from the page
entirely and so takes AUTO ADS down alongside the two manual slots. Source ORDER
is the whole property; the ops repo pins it with a static test. Removing the
attribute here silently re-enables ads on ~217k profiles.
"""

from models.salary import EmployerCluster

# Employer profiles with fewer lifetime filings than this are noindexed by the
# view and excluded from the sitemap. Shared by webapp/views/employers/profile.py
# and webapp/views/seo/sitemaps.py — change it in one place.
#
# 10 keeps the 16,087 clusters that carry real data (10+ filings) indexable and
# drops the 217,358-page thin tail. Tuning reference (prod 2026-07-27):
#   threshold 5   → 32,220 indexable
#   threshold 10  → 16,087 indexable   ← current
#   threshold 50  →  3,625 indexable
#   threshold 100 →  1,710 indexable (matches the job-title gate)
EMPLOYER_INDEXABLE_MIN_FILINGS = 10


def employer_lifetime_filings(cluster: EmployerCluster) -> int:
    """Lifetime filing count for a cluster, across BOTH visa programs.

    The stored per-program counters are the only filter-independent measure
    available to the sitemap. Summing them matters: a PERM-heavy employer has a
    low `total_lca_count` but plenty of data, and gating on LCA alone would
    noindex it (the pre-2026-07-27 sitemap filter did exactly that).
    """
    return (cluster.total_lca_count or 0) + (cluster.total_perm_count or 0)


def is_thin_employer_profile(cluster: EmployerCluster, rendered_filings: int) -> bool:
    """Whether this employer profile is too thin to index or to carry ads.

    `rendered_filings` is the count the page actually displays (post year /
    program / level filtering), so a cluster whose filings all fall outside the
    rendered window is thin even when its lifetime count clears the threshold.
    """
    if rendered_filings <= 0:
        return True
    return employer_lifetime_filings(cluster) < EMPLOYER_INDEXABLE_MIN_FILINGS


def indexable_employer_clusters(limit: int = 10000):
    """Sitemap-eligible clusters: slugged, above the gate, biggest first.

    Ordered by the same combined lifetime count the gate uses so the cap keeps
    the highest-value pages.
    """
    from django.db.models import F

    return (
        EmployerCluster.objects.filter(slug__isnull=False)
        .annotate(_lifetime_filings=F("total_lca_count") + F("total_perm_count"))
        .filter(_lifetime_filings__gte=EMPLOYER_INDEXABLE_MIN_FILINGS)
        .order_by("-_lifetime_filings")[:limit]
    )

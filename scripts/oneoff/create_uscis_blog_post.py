"""Create the 'USCIS visa bulletin filing dates explained' blog post.

Targets the GSC query "uscis visa bulletin" (~12k impressions/4w, CTR 0.23%,
pos 9.9 as of 2026-05-16). The angle is the recurring confusion about
*USCIS's monthly chart-selection determination* — people google "uscis visa
bulletin" expecting the bulletin to live at uscis.gov, but USCIS only
publishes the chart-selection note (Final Action Dates vs Dates for Filing)
that determines which chart AOS applicants must use to time their I-485.

Idempotent: uses update_or_create so re-running on staging or prod is safe.
Run with: bazel run //scripts/oneoff:create_uscis_blog_post

To delete and re-run from scratch (staging only):
  bazel run //scripts/oneoff:create_uscis_blog_post -- --delete-first
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Bootstrap Django (matches the pattern used in other scripts/oneoff/* scripts).
WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django  # noqa: E402

django.setup()

from models.blog import BlogPost  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SLUG = "uscis-visa-bulletin-filing-dates-explained"
TITLE = "USCIS Visa Bulletin: What the Monthly USCIS Notice Actually Decides for AOS Filers"
CATEGORY = "Guides"

# Kept deliberately short. The first 100 words answer the search intent; the
# CTA to the live tracker is above the fold; only two follow-up Q&As.
CONTENT = """\
<div class="blog-content">

<p class="lead">
There is no separate "USCIS visa bulletin." USCIS does not publish the bulletin —
the bulletin comes from the <a href="https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html" rel="noopener" target="_blank">State Department</a>.
What USCIS publishes is <strong>one short notice each month</strong> deciding which
of the bulletin&#39;s two charts I-485 (adjustment-of-status) filers may use that
month. That single decision shifts AOS filing windows by months.
</p>

<div class="alert alert-primary mt-3 mb-4">
    <p class="mb-2">
        <strong>Want to skip the explanation?</strong>
        Pick your category and country on the live tracker — both charts and a
        12-month projection are on one page.
    </p>
    <p class="mb-0">
        <a class="btn btn-primary" href="/employment-based/india/" style="white-space: nowrap;">
            <i class="bi bi-calendar-check"></i> India EB tracker
        </a>
        <a class="btn btn-outline-primary" href="/" style="white-space: nowrap;">
            All categories &rarr;
        </a>
    </p>
</div>

<h2 id="two-charts">The bulletin&#39;s two charts, in 30 seconds</h2>

<ul>
  <li><strong>Final Action Dates (Chart A)</strong> — cutoff for green-card
      <em>approval</em>. Visa number available; case can be adjudicated.</li>
  <li><strong>Dates for Filing (Chart B)</strong> — earlier cutoff for when USCIS
      may <em>accept</em> the I-485 paperwork, even though the number is not yet
      available.</li>
</ul>

<p>
Each month USCIS posts a one-paragraph notice at
<a href="https://www.uscis.gov/visabulletininfo" rel="noopener" target="_blank">uscis.gov/visabulletininfo</a>
saying, per category (EB or family), <em>"use Chart A"</em> or <em>"use Chart B."</em>
That is the entire content of the notice. The chart selection only affects AOS
filers inside the U.S. — consular processing always uses Final Action Dates.
</p>

<h2 id="why-it-matters">Why the chart choice matters</h2>

<p>
The gap between Chart A and Chart B can be a year or more in backlogged
categories (India EB-2, China EB-3, F2B Philippines). When USCIS allows Chart
B, an AOS filer can:
</p>

<ul>
  <li>File I-485 a year or more earlier than their visa number actually becomes available.</li>
  <li>File I-765 (EAD) and I-131 (Advance Parole) alongside — work authorization decoupled from H-1B/L-1, plus travel flexibility.</li>
  <li>Lock in CSPA age for derivative children before they turn 21.</li>
  <li>Use AC21 to change jobs once the I-485 has been pending 180 days.</li>
</ul>

<h2 id="how-to-tell">How to tell where you stand today</h2>

<p>
Reading the bulletin is two lookups: your category × your chargeability
country. The per-country pages on this site show both charts overlaid plus a
12-month projection — pick whichever applies:
</p>

<ul class="list-unstyled">
  <li><i class="bi bi-arrow-right-short"></i> <a href="/employment-based/india/">India — employment-based</a></li>
  <li><i class="bi bi-arrow-right-short"></i> <a href="/employment-based/china/">China — employment-based</a></li>
  <li><i class="bi bi-arrow-right-short"></i> <a href="/employment-based/philippines/">Philippines — employment-based</a></li>
  <li><i class="bi bi-arrow-right-short"></i> <a href="/employment-based/mexico/">Mexico — employment-based</a></li>
  <li><i class="bi bi-arrow-right-short"></i> <a href="/employment-based/all/">All other countries — employment-based</a></li>
  <li><i class="bi bi-arrow-right-short"></i> <a href="/family-sponsored/all/">Family-sponsored — all countries</a></li>
</ul>

<p>
On each page: switch <em>Action Type</em> between "Final Action" and "Filing"
to compare the two charts side by side. The projection table shows the model&#39;s
estimated cutoff at the next bulletin, 6 months, and 12 months out — which
answers <em>"when does my I-485 window open under each chart?"</em>
</p>

<p>
<a href="/predictions/employment_based/" class="btn btn-outline-secondary btn-sm">
    Historical prediction accuracy &rarr;
</a>
<a href="/analysis/how-my-prediction-model-works/" class="btn btn-outline-secondary btn-sm">
    How the model works &rarr;
</a>
</p>

<h2 id="faq">Two questions people ask</h2>

<h3>What if USCIS picks Chart A this month but I filed under Chart B last month?</h3>
<p>
Filings USCIS accepted in a prior month stay pending. The chart change only
affects <em>new</em> filings in the current month. Your pending I-485 still
waits for Final Action Dates to reach your priority date before it can be
approved — that part never changes.
</p>

<h3>Can I predict which chart USCIS will pick next month?</h3>
<p>
USCIS picks Chart B when their pending-I-485 inventory is low (to let more
cases in) and Chart A when it is full (to slow intake). Their inventory is
not published in real time, so chart selection is harder to predict than the
underlying cutoff movement. The projection on this site forecasts cutoffs,
not chart selection — but cutoff projections under both charts are usually
the more actionable number anyway, because once your priority date passes
either cutoff the chart selection is no longer a constraint.
</p>

</div>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete-first",
        action="store_true",
        help="Delete the existing post before creating (staging only)",
    )
    args = parser.parse_args()

    if args.delete_first:
        deleted, _ = BlogPost.objects.filter(slug=SLUG).delete()
        logger.info("Deleted %d existing post(s) with slug=%s", deleted, SLUG)

    post, created = BlogPost.objects.update_or_create(
        slug=SLUG,
        defaults={
            "title": TITLE,
            "content": CONTENT,
            "category": CATEGORY,
            "is_published": True,
        },
    )
    action = "Created" if created else "Updated"
    logger.info("%s post: %s (slug=%s, len=%d)", action, post.title, post.slug, len(post.content))
    logger.info("Live at: /analysis/%s/", post.slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())

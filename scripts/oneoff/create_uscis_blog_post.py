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
TITLE = "USCIS Visa Bulletin Filing Dates: What That Monthly USCIS Notice Actually Decides"
CATEGORY = "Guides"

# HTML content. Keeps the same shape as existing posts (h1/h2/h3/p/ul/li,
# Bootstrap classes where useful). Internal links to the dashboard + the
# methodology post create the topical funnel back into the prediction tool.
CONTENT = """\
<div class="blog-content">

<p class="lead">
If you searched <em>"USCIS visa bulletin"</em> expecting a bulletin published
<strong>by USCIS itself</strong>, you are not alone — but USCIS doesn&#39;t publish the bulletin.
USCIS publishes <strong>one short notice each month</strong> that decides whether
adjustment-of-status (I-485) applicants use the <strong>Final Action Dates</strong> chart
or the <strong>Dates for Filing</strong> chart in the State Department&#39;s visa bulletin.
That single sentence&#39;s worth of guidance changes when tens of thousands of people
can file I-485, and most of the confusion online comes from missing it.
</p>

<p>
This guide explains, in plain language, what USCIS&#39;s monthly determination is,
where to find it, why it matters for AOS filers, and how to read both charts
without getting them mixed up.
</p>

<h2 id="two-charts">Why the visa bulletin has two charts each month</h2>

<p>
Every month the U.S. Department of State (DOS) publishes the
<a href="https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html" rel="noopener" target="_blank">visa bulletin</a>
with <strong>two separate priority-date charts</strong> per category (employment-based
EB-1 through EB-5, and family-sponsored F1 through F4):
</p>

<ul>
  <li><strong>Final Action Dates (Chart A).</strong> The cutoff that controls when a
  green card can actually be <em>approved</em>. If your priority date is earlier than
  this cutoff, a visa number is available for your case to be adjudicated.</li>
  <li><strong>Dates for Filing (Chart B).</strong> A more permissive cutoff that
  signals when DOS expects to need filed cases in the near future. Filing on
  this chart does <em>not</em> mean approval — only that USCIS may accept the
  application and start work on it.</li>
</ul>

<p>
Both charts come from the State Department. <strong>USCIS</strong> — a separate
agency, part of DHS — adjudicates I-485 adjustment-of-status applications for
people already in the U.S. on a nonimmigrant visa. Each month, USCIS decides
which of the two charts I-485 applicants are allowed to use that month.
</p>

<h2 id="uscis-determination">What USCIS&#39;s monthly determination actually says</h2>

<p>
On the same day the State Department publishes the bulletin (typically
the 8th to 15th of the month before the bulletin&#39;s effective month), USCIS
publishes a notice at <a href="https://www.uscis.gov/visabulletininfo" rel="noopener" target="_blank">uscis.gov/visabulletininfo</a>
with the following per category:
</p>

<ul>
  <li><strong>For employment-based filings:</strong> use Chart A (Final Action) or Chart B (Dates for Filing).</li>
  <li><strong>For family-sponsored filings:</strong> use Chart A or Chart B.</li>
</ul>

<p>
The determination is binary per category — USCIS picks one chart for the
month for each category. The choice is driven by whether USCIS has enough
pending I-485 cases to keep adjudication moving. When USCIS&#39;s pipeline
runs low, they tend to choose Dates for Filing so more cases enter the
queue; when they have plenty, they choose Final Action.
</p>

<div class="alert alert-info">
<strong>Critical:</strong> the USCIS determination overrides the State Department
chart for <em>I-485 filing eligibility only</em>. Consular processing (people
applying from outside the U.S.) always uses Final Action Dates regardless of
what USCIS chose for AOS filers that month.
</div>

<h2 id="why-it-matters">Why the chart choice matters for AOS applicants</h2>

<p>
The gap between Final Action Dates and Dates for Filing can be large —
several months, sometimes a full year for backlogged categories like
India EB-2 or China EB-3. When USCIS allows the Dates for Filing chart:
</p>

<ul>
  <li><strong>You can file I-485 sooner.</strong> Sometimes a year or more earlier than the actual visa-availability date.</li>
  <li><strong>Dependents file at the same time.</strong> Children aging out of derivative status (CSPA) lock in their age at I-485 filing, so an earlier filing date can matter enormously.</li>
  <li><strong>You can apply for I-765 (EAD) and I-131 (Advance Parole)</strong> with the I-485, gaining work authorization independent of the underlying H-1B/L-1, and re-entry flexibility.</li>
  <li><strong>You can change jobs more easily under AC21</strong> once the I-485 has been pending 180 days.</li>
</ul>

<p>
Conversely, when USCIS picks Final Action Dates, AOS filers must wait — even
if Dates for Filing on the bulletin would otherwise suggest they could file.
This single chart-selection decision routinely shifts AOS filing windows by
months, which is why subscribing to the USCIS notice (or checking
visabulletininfo on the 8th–15th) matters as much as reading the bulletin
itself.
</p>

<h2 id="reading-bulletin">Reading the bulletin once you know the chart</h2>

<p>
With USCIS&#39;s determination in hand:
</p>

<ol>
  <li>Open the relevant State Department bulletin.</li>
  <li>Locate your <strong>visa category</strong> (e.g. EB-2) and <strong>chargeability country</strong> (India, China, Mexico, Philippines, or "All Chargeability Areas").</li>
  <li>Read the cell using the chart USCIS designated for your filing type (AOS) and category (EB or family).</li>
  <li>Compare to your priority date — the date your I-140 (EB) or I-130 (family) was filed. If your priority date is <em>earlier</em> than the cutoff in the cell, a number is available.</li>
</ol>

<p>
The bulletin uses <strong>C</strong> for "Current" (anyone with that
chargeability and category can file) and <strong>U</strong> for "Unavailable"
(no one can file that month).
</p>

<h2 id="predictions">Predicting next month&#39;s chart and cutoff</h2>

<p>
USCIS&#39;s monthly chart-selection notice and the State Department&#39;s cutoff
movements both follow patterns that can be modeled. The
<a href="/predictions/employment_based/">Bulletin Forecast Model</a> on this
site projects each category&#39;s cutoff six to twelve months ahead and tracks
the historical accuracy of those projections. The
<a href="/">live dashboard</a> shows where your priority date currently sits
relative to projected cutoffs, so you can estimate when your I-485 filing
window will open under each chart.
</p>

<p>
<a href="/analysis/how-my-prediction-model-works/" class="btn btn-outline-primary">Read how the prediction model works →</a>
</p>

<h2 id="checklist">Monthly checklist for AOS filers</h2>

<p>Every month, when the visa bulletin drops (typically the 8th–15th):</p>

<ol>
  <li><strong>Check the State Department bulletin</strong> for both Final Action Dates and Dates for Filing in your category + country.</li>
  <li><strong>Check uscis.gov/visabulletininfo</strong> for which chart USCIS designated for your category.</li>
  <li><strong>Compare the designated chart&#39;s cutoff</strong> to your priority date.</li>
  <li>If your date is current under the designated chart and you haven&#39;t filed I-485 yet, <strong>file it.</strong> The window can close again next month if cutoffs retrogress.</li>
  <li><strong>Subscribe to the USCIS visa bulletin information page</strong> or set a calendar reminder for the 10th of each month — the determination posts within a day or two of the State Department bulletin.</li>
</ol>

<h2 id="faq">Common questions</h2>

<h3>Does USCIS publish its own visa bulletin?</h3>
<p>
No. The visa bulletin is published by the U.S. Department of State,
which is responsible for visa-number allocation. USCIS publishes a
monthly chart-selection determination at
<a href="https://www.uscis.gov/visabulletininfo" rel="noopener" target="_blank">uscis.gov/visabulletininfo</a>
that decides which State Department chart I-485 (AOS) filers must use that
month. The chart-selection notice is much shorter than the bulletin itself —
typically one paragraph per category.
</p>

<h3>What if USCIS chooses Final Action Dates and I already filed under Dates for Filing in a previous month?</h3>
<p>
Filings that USCIS accepted in a previous month stay pending — the chart
change only affects <em>new</em> filings in the current month. Pending I-485s
continue to wait for the Final Action Date in their category to reach their
priority date before they can be approved.
</p>

<h3>Why does USCIS switch between charts month to month?</h3>
<p>
USCIS&#39;s stated factor is whether they have enough pending I-485 inventory
to keep up with visa-number availability. When their pending queue is low,
they pick Dates for Filing to let more cases in; when the queue is full,
they pick Final Action Dates to slow intake. In practice, predicting USCIS&#39;s
choice is harder than predicting the State Department&#39;s cutoff movements,
because USCIS doesn&#39;t publish its inventory in real time.
</p>

<h3>Does the chart selection apply to consular processing too?</h3>
<p>
No. People processing their immigrant visas at a U.S. consulate abroad
always use the <strong>Final Action Dates</strong> chart. The USCIS chart-selection
notice only affects I-485 adjustment-of-status applicants who are already
in the U.S.
</p>

<h2 id="bottom-line">Bottom line</h2>

<p>
"USCIS visa bulletin" usually refers to one of two things, and confusing
them costs people months of waiting:
</p>

<ol>
  <li><strong>The State Department visa bulletin</strong> — where the actual cutoffs live.</li>
  <li><strong>USCIS&#39;s monthly chart-selection notice</strong> — where AOS filers learn whether they can use the more permissive Dates for Filing chart that month.</li>
</ol>

<p>
Read both, every month. The
<a href="/">priority date tracker on this site</a>
shows your current position against both charts and the projected cutoffs
for the next 12 months, so you know when each filing window is likely
to open.
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

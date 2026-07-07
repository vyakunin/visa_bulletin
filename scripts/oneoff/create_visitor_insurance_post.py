"""Create the 'Visitor insurance for parents visiting the U.S.' blog post.

The first content piece of the monetization lever "visitor-insurance arm"
(visa_bulletin_platform monetization/PIPELINE.md, ticket 39362b8d, 2026-07-04):
the visiting-parents (B-2) travel-medical purchase is the canonical recurring
buy for the site's settled-immigrant audience, and insurance queries carry
high-CPC ad demand. The page runs AdSense-monetized from day one; a dedicated
visitor-insurance affiliate block is added once a program (VisitorsCoverage /
INSUBUY) approves — none of the currently-live brands fits this intent.

Deliberately brand-neutral and non-advisory: plan mechanics, what to check,
broad cost ranges only. No affiliate links, so no FTC disclosure needed yet.

Idempotent: uses update_or_create so re-running on staging or prod is safe.
Run with: bazel run //scripts/oneoff:create_visitor_insurance_post
Inside a deployed container (image predates this script — pipe it in):
  docker compose exec -T web python - < scripts/oneoff/create_visitor_insurance_post.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Bootstrap Django. When piped via stdin into a container (`python -`), __file__
# is missing or '<stdin>' (whose resolve() has too few parents) — fall back to
# the in-image app root.
try:
    WORKSPACE = Path(__file__).resolve().parents[2]
except (NameError, IndexError):
    WORKSPACE = Path("/app")
sys.path.insert(0, str(WORKSPACE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django  # noqa: E402

django.setup()

from models.blog import BlogPost  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SLUG = "visitor-insurance-parents-visiting-us"
TITLE = "Visitor Insurance for Parents Visiting the U.S.: What Green Card and H-1B Families Should Know"
CATEGORY = "Guides"

CONTENT = """\
<div class="blog-content">

<p class="lead">
If your parents are visiting you in the United States on a B-2 visitor visa, their
health coverage from home almost certainly stops at the border. U.S. hospitals bill
visitors at full private rates, Medicare never covers non-residents, and regular
U.S. health plans (ACA marketplace plans, your employer plan) are not available to
short-term visitors. Visitor medical insurance — a short-term travel-medical policy
bought per trip — is how immigrant families bridge that gap.
</p>

<h2>Why this matters more than most trip planning</h2>
<p>
American medical care is the one bill that can turn a family visit into a financial
emergency. An emergency-room visit routinely runs into the thousands of dollars, and
a hospital admission into tens of thousands. Older visitors are exactly the people
most likely to need unplanned care — and the least likely to have any U.S. coverage.
Most families who host parents every year treat visitor insurance the way they treat
the plane ticket: a fixed, expected cost of the trip.
</p>

<h2>The two plan types: fixed vs. comprehensive</h2>
<p>
Almost every visitor-insurance policy sold in the U.S. market is one of two designs:
</p>
<ul>
  <li>
    <strong>Fixed-benefit (scheduled) plans</strong> pay a set amount per line of
    treatment — say, a fixed sum for an ER visit or per hospital day — regardless of
    what the hospital actually bills. They are the cheapest option, but the gap
    between the fixed payout and a real U.S. hospital bill stays with you.
  </li>
  <li>
    <strong>Comprehensive plans</strong> work more like normal insurance: after a
    deductible, the plan pays a percentage of actual covered charges up to the policy
    maximum. They cost more, and they are what most experienced hosts buy for parents
    over 60 — because the point of the policy is the large, unlikely bill, not the
    small clinic visit.
  </li>
</ul>

<h2>Age and pre-existing conditions — read this part twice</h2>
<p>
Two things drive both the price and the fine print:
</p>
<ul>
  <li>
    <strong>Age bands.</strong> Premiums step up sharply at 60, 65, 70 and 80, and
    the maximum coverage amounts available shrink at higher ages. Insuring a
    45-year-old visitor costs a few dollars a day; insuring a 75-year-old costs
    several times that.
  </li>
  <li>
    <strong>Pre-existing conditions are excluded by default.</strong> Standard
    visitor policies do not cover conditions that existed before the trip —
    hypertension, diabetes, prior cardiac history. What some plans offer is
    <em>"acute onset of pre-existing conditions"</em> coverage: a sudden, unexpected
    flare-up (not routine care or a gradually worsening condition) is covered, usually
    with its own lower maximum and an age cutoff (often 70 or 80). If your parents
    have any chronic condition, the acute-onset terms are the single most important
    line in the policy.
  </li>
</ul>

<h2>What to check before you buy</h2>
<ul>
  <li><strong>Policy maximum:</strong> $50,000 is a common floor; for parents over 60,
      $100,000+ is the widely-recommended range because a single hospitalization can
      exhaust a low maximum.</li>
  <li><strong>Deductible:</strong> per-policy vs. per-incident, and how it interacts
      with the coinsurance split.</li>
  <li><strong>Acute-onset coverage:</strong> maximum, age limit, and exactly how the
      policy defines "acute onset."</li>
  <li><strong>Provider network and direct billing:</strong> plans that use a U.S. PPO
      network let the hospital bill the insurer directly instead of you paying and
      claiming back.</li>
  <li><strong>Emergency evacuation and repatriation:</strong> standard in most plans,
      but the limits vary widely.</li>
  <li><strong>Extendability:</strong> if the stay might stretch past six months, check
      that the policy can be renewed or extended without a new waiting period.</li>
</ul>

<h2>When to buy, and roughly what it costs</h2>
<p>
Buy before departure so coverage starts the moment they land (many plans can start
on any date you pick, and travel to and from the U.S. is typically included). Cover
the full planned stay — extending late or leaving gaps is where claims get denied.
As a broad range, expect roughly $2–$10 per person per day depending on age, plan
type, policy maximum and deductible; fixed plans sit at the bottom of that range,
comprehensive coverage for visitors over 70 at the top. For a typical six-month
parental visit, that is a few hundred to around a thousand dollars — small next to
one uninsured ER bill.
</p>

<h2>The bigger picture for sponsoring families</h2>
<p>
Frequent parental visits are usually a stage on the road to something more permanent
— many hosts eventually sponsor parents for a green card (immediate-relative IR-5,
no annual quota, no visa-bulletin queue for parents of U.S. citizens). Until then,
each B-2 visit is a fresh insurance decision. If you are tracking your own
employment-based or family-sponsored case in the meantime, our
<a href="/">live visa bulletin tracker</a> and
<a href="/family-sponsored/">family-sponsored category pages</a> show current
priority-date movement and 12-month projections.
</p>

<p class="text-muted small mt-4">
This article explains how visitor-insurance products are generally structured; it is
not insurance, legal, or medical advice. Policy terms differ — always read the plan
certificate before buying.
</p>

</div>
"""


def main() -> None:
    post, created = BlogPost.objects.update_or_create(
        slug=SLUG,
        defaults={
            "title": TITLE,
            "content": CONTENT,
            "category": CATEGORY,
            "is_published": True,
        },
    )
    logger.info("%s blog post id=%s slug=%s published=%s",
                "Created" if created else "Updated", post.id, post.slug, post.is_published)


if __name__ == "__main__":
    main()

"""Generate the three I-129 FOIA data-story /analysis/ pages as BlogPost rows.

Publication drafts + red-team live in docs/department_of_labor/i129_stories/
(story_a/b/c + RIGOR_REVIEW.md). Every figure was verified against live prod
`i129_petition` (372,841 rows, FY2021-2024, selected-and-filed cap-subject
lottery petitions) on 2026-07-13.

Category = "Data Story" (NOT "Analysis") so these are never in scope for the
monthly-narrator stale-post pruning in generate_initial_blog_posts.create_analysis_posts
(which deletes any category="Analysis" post outside its regenerated set).

Idempotent: update_or_create by slug. Run on staging first, verify the rendered
pages, then run the SAME on prod after approval (deployment.md "Regenerate stored
content"). Follow with Redis flush + CF purge + sitemap resubmit (seo_publish.md).

Usage (staging):
    docker exec -w /app vb_stg_web python3 -m scripts.oneoff.generate_i129_story_posts
Prod (after approval):
    docker exec -w /app vb_web python3 -m scripts.oneoff.generate_i129_story_posts
"""

import logging
import os

if os.environ.get("DB_HOST") == "host.docker.internal":
    os.environ["DB_HOST"] = "localhost"
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django  # noqa: E402

django.setup()

from dataclasses import dataclass  # noqa: E402

from django_config.logging_config import setup_logging  # noqa: E402
from lib.utils.logging_utils import log_context  # noqa: E402
from models.blog import BlogPost  # noqa: E402

setup_logging(debug=False)
logger = logging.getLogger(__name__)

CATEGORY = "Data Story"

# Shared provenance block appended to every story (E-E-A-T / GEO: name the source,
# the universe, and the redaction limits so the page is citable and defensible).
_ATTRIBUTION = """
<hr>
<h2>Source &amp; method</h2>
<p>The petition-level figures come from the <strong>I-129 microdata released under
the Freedom of Information Act</strong> — "sourced from USCIS, obtained by Bloomberg"
(<em>Bloomberg&nbsp;v.&nbsp;DHS</em>), the same dataset behind
<a href="https://www.nber.org/papers/w34793">Borjas's H-1B wage-gap paper (NBER
w34793)</a>. Registration-pool figures (eligible registrations, selections, the FY2025
rule effects) are from USCIS's own published H-1B Electronic Registration statistics and
its <a href="https://www.federalregister.gov/documents/2024/02/02/2024-01770/improving-the-h-1b-registration-selection-process-and-program-integrity">FY2025
selection-rule rulemaking</a>.</p>
<p><strong>Universe:</strong> fiscal years 2021&ndash;2024, cap-subject H-1B lottery
petitions that were <strong>selected and filed</strong> (372,841 rows) &mdash; not the
full registration pool. A frozen FOIA snapshot; per-beneficiary identifiers are
redacted, so figures are aggregates only. Every number on this page was checked against
the live database on 2026-07-13.</p>
<p><strong>Custom data slices for research or reporting.</strong> If you're a researcher,
academic or journalist and want a specific cut of this data &mdash; a breakdown by
employer, occupation, country of birth, fiscal year, or any combination not shown here
&mdash; <a href="/contact/">get in touch</a> and I'll put it together. Attribution to
visa-bulletin.us is appreciated.</p>
<p class="small text-muted mt-3"><a href="/analysis/">More data analysis</a>.</p>
"""


@dataclass
class Story:
    title: str
    slug: str
    content: str


def _story_a() -> Story:
    body = """
<p class="lead">Among <strong>filed</strong> H-1B petitions, the share tied to a
beneficiary that multiple employers had registered in the lottery <strong>tripled in
four years &mdash; 8.2% (FY2021) to 25.5% (FY2024)</strong>. USCIS's own registration
data shows the underlying pool went further: over half of FY2024 lottery registrations
were multi-entries. And the concentration is the opposite of the common assumption
&mdash; it lives in the long tail of small staffing firms, not Infosys, TCS, or
Amazon.</p>

<p class="text-muted"><em>Lottery gaming isn't a new finding.
<a href="https://www.bloomberg.com/graphics/2024-staffing-firms-game-h1b-visa-lottery-system/">Bloomberg's
2024 investigation</a> first showed staffing firms flooding the lottery, and
<a href="https://www.federalregister.gov/documents/2024/02/02/2024-01770/improving-the-h-1b-registration-selection-process-and-program-integrity">USCIS's
own rulemaking</a> published the registration-pool counts and rewrote the selection
process because of it. This page is the companion view from the
<strong>selected-and-filed petitions</strong>: a conservative rate over time, an employer
size-gradient, and an India&times;IT-services cut &mdash; all reproducible from the public
microdata.</em></p>

<h2>The trend, among selected-and-filed petitions</h2>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Fiscal year</th><th class="text-end">Filed petitions</th>
<th class="text-end">Multi-registered</th><th class="text-end">Rate</th></tr></thead>
<tbody>
<tr><td>2021</td><td class="text-end">99,610</td><td class="text-end">8,148</td><td class="text-end fw-bold">8.2%</td></tr>
<tr><td>2022</td><td class="text-end">89,535</td><td class="text-end">15,159</td><td class="text-end fw-bold">16.9%</td></tr>
<tr><td>2023</td><td class="text-end">91,832</td><td class="text-end">20,892</td><td class="text-end fw-bold">22.8%</td></tr>
<tr><td>2024</td><td class="text-end">91,864</td><td class="text-end">23,401</td><td class="text-end fw-bold">25.5%</td></tr>
</tbody></table>
</div>
<p>USCIS flags a beneficiary as multi-registered (<code>ben_multi_reg_ind = 1</code>)
when the person appeared in more than one employer's registration that lottery year.
It is USCIS's marker for <em>potential</em> abuse &mdash; not an adjudication of fraud,
and the employer that ultimately filed is not necessarily the party that
multi-registered the person.</p>

<h2>A behavioral change, not a composition shift</h2>
<p>India's share of filings was essentially flat (64% &rarr; 67% &rarr; 70% &rarr; 67%),
so the rise isn't a country-mix effect. The rate rose <em>within</em> every origin group:</p>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Multi-reg rate among filed petitions</th><th class="text-end">FY21</th>
<th class="text-end">FY22</th><th class="text-end">FY23</th><th class="text-end">FY24</th></tr></thead>
<tbody>
<tr><td>India-born</td><td class="text-end">10.5%</td><td class="text-end">23.4%</td><td class="text-end">30.0%</td><td class="text-end fw-bold">34.9%</td></tr>
<tr><td>China-born</td><td class="text-end">5.4%</td><td class="text-end">4.6%</td><td class="text-end">8.1%</td><td class="text-end fw-bold">10.1%</td></tr>
<tr><td>All other</td><td class="text-end">2.9%</td><td class="text-end">2.9%</td><td class="text-end">3.9%</td><td class="text-end fw-bold">4.2%</td></tr>
</tbody></table>
</div>

<h2>The real cut: India &times; IT-services staffing</h2>
<p>A bare "India 24.6% vs China 6.9%" is true but under-specified. The phenomenon is an
India &times; IT-staffing interaction (NAICS 5415, computer-systems-design services),
pooled FY21&ndash;24:</p>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th></th><th class="text-end">IT services (NAICS 5415)</th><th class="text-end">Other industries</th></tr></thead>
<tbody>
<tr><td>India-born</td><td class="text-end fw-bold">33.5% <span class="text-muted small">(n=156,643)</span></td><td class="text-end">9.7% <span class="text-muted small">(n=93,082)</span></td></tr>
<tr><td>Other-born</td><td class="text-end">6.9% <span class="text-muted small">(n=20,543)</span></td><td class="text-end">4.6% <span class="text-muted small">(n=102,573)</span></td></tr>
</tbody></table>
</div>
<p>India-born beneficiaries <em>outside</em> IT services run ~10% (still double other
countries); India&nbsp;&times;&nbsp;IT-services reaches <strong>45.4% by FY2024</strong>.
The sector is half the story.</p>

<h2>The inversion: small staffing shops, not Big Tech</h2>
<p>The reflex is to blame the large outsourcers. The data says the opposite.
Multi-registration rates among the biggest filers are low &mdash; Amazon 3.6%,
Infosys 3.1%, TCS 4.7%, Cognizant 4.5%, Microsoft 3.3%, IBM 3.1%.</p>
<p>The extreme rates are tiny staffing firms: Aclat Inc. 88 of 88 petitions (100%),
Snowstack LLC 96.8%, R2 Technologies 91.9%. A clean size gradient, employers bucketed
by total FY21&ndash;24 filings:</p>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Employer size (filings)</th><th class="text-end">Employers</th>
<th class="text-end">Petitions</th><th class="text-end">Multi-reg rate</th></tr></thead>
<tbody>
<tr><td>1&ndash;9</td><td class="text-end">54,807</td><td class="text-end">105,504</td><td class="text-end">20.4%</td></tr>
<tr><td>10&ndash;49</td><td class="text-end">4,656</td><td class="text-end">91,430</td><td class="text-end fw-bold">35.2%</td></tr>
<tr><td>50&ndash;199</td><td class="text-end">551</td><td class="text-end">46,972</td><td class="text-end">19.8%</td></tr>
<tr><td>200&ndash;999</td><td class="text-end">98</td><td class="text-end">38,537</td><td class="text-end">4.4%</td></tr>
<tr><td>1,000+</td><td class="text-end">29</td><td class="text-end">90,398</td><td class="text-end fw-bold">3.2%</td></tr>
</tbody></table>
</div>
<p><strong>1,815 employers with at least 10 filings and a 50%-or-higher multi-reg rate
account for 46% of all multi-registered petitions.</strong> Employers filing fewer than
50 petitions hold 79% of them. The gaming lived in thousands of small staffing firms,
not the household-name outsourcers.</p>

<h2>The pool was worse than the filings show</h2>
<p>Our number counts <em>filed</em> petitions, which understates the lottery pool: many
multi-registered beneficiaries were selected but never filed. USCIS's registration-level
statistics:</p>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Cap FY</th><th class="text-end">Eligible registrations</th>
<th class="text-end">Multi-reg share of registrations</th></tr></thead>
<tbody>
<tr><td>2021</td><td class="text-end">269,424</td><td class="text-end">10.4%</td></tr>
<tr><td>2022</td><td class="text-end">301,447</td><td class="text-end">29.9%</td></tr>
<tr><td>2023</td><td class="text-end">474,421</td><td class="text-end">34.8%</td></tr>
<tr><td>2024</td><td class="text-end">758,994</td><td class="text-end fw-bold">53.9%</td></tr>
</tbody></table>
</div>
<p>The pool share rose <em>faster</em> (10.4% &rarr; 53.9%, 5.2&times;) than our
filed-petition rate (8.2% &rarr; 25.5%, 3.1&times;) &mdash; so selection bias makes our
figure <strong>conservative</strong>, not inflated.</p>

<h2>What changed next: the FY2025 beneficiary-centric rule</h2>
<p>This is the "before" picture. Starting with the FY2025 lottery, USCIS switched to
<strong>beneficiary-centric</strong> selection &mdash; each person is entered once no
matter how many employers register them, so running one beneficiary through several
shells no longer improves their odds. In the first year under the rule, multi-registered
registrations fell <strong>408,891 &rarr; 47,314 (&minus;88%)</strong> and total eligible
registrations dropped from 759k to 470k.</p>
<p><strong>How much of that is the rule?</strong> The <em>multi-registration</em> collapse
tracks the rule's mechanism closely: once duplicate entries stop paying off, the reason
to file them is gone. But the overall pool didn't shrink in a vacuum, and the raw
before/after is not a clean natural experiment. Several things moved at once in
2024&ndash;25: the per-registration fee later jumped from $10 to $215 (FY2026), the
tech-hiring market cooled, and enforcement scrutiny rose &mdash; and the pool kept
falling the next year (470k &rarr; 344k) well after the counting change. So the
defensible read is narrow: the rule removed the specific incentive this story documents
and multi-registration cratered right after; the broader decline in <em>how many people
register</em> reflects several 2025 changes together, not this one measure.</p>

<h2>How to read these numbers</h2>
<ul>
<li>Every rate is "among selected-and-filed petitions" unless labeled as the
registration pool.</li>
<li>Aggregate only &mdash; individual "one person &rarr; N shell companies" chains
cannot be reconstructed (FOIA-redacted keys).</li>
<li>"Multi-registered" is USCIS's flag for <em>potential</em> abuse, not proven fraud.
The named high-rate employers are shown with their petition counts for that reason.</li>
<li>Coverage: FY2021&ndash;2024, cap-subject lottery petitions, frozen snapshot.</li>
</ul>

<h2>Explore the employers yourself</h2>
<p>Look up any H-1B filer in the <a href="/employers/">employer directory</a> or the
<a href="/employers/rankings/">sponsor rankings</a> &mdash; each employer profile shows
that company's I-129 approval rate and how its reported pay compares to the posted wage.
You can also <a href="/salaries/">search the certified-wage records</a> by employer, role
and state.</p>
"""
    return Story(
        title="H-1B multi-registration tripled to 25% — and it wasn't the big outsourcers",
        slug="h1b-multi-registration-lottery-gaming",
        content=body + _ATTRIBUTION,
    )


def _story_b() -> Story:
    body = """
<p class="lead">A widely-quoted statistic says H-1B women earn less than men &mdash; a
raw gap of roughly 4%, and much larger (16&ndash;25%) among Chinese- and other-born
workers. Taken at face value it reads as unequal pay for equal work. In the FOIA'd
petition data it is almost entirely <strong>occupational sorting</strong>, not unequal
pay: compare men and women in the <strong>same job title</strong> and the gap all but
disappears &mdash; an adjusted <strong>+0.3% at the mean, &minus;0.9% at the median</strong>
across 388 title&times;year strata (107,000 petitions). The story is <em>which jobs</em>
men and women hold, not different pay for the same job.</p>

<p class="text-muted"><em>The best-known study of this dataset,
<a href="https://www.nber.org/papers/w34793">Borjas's H-1B wage-gap paper (NBER
w34793)</a>, asks a different question: how H-1B pay compares to <strong>U.S.-born</strong>
workers (it finds a large gap, and the finding is contested). This page instead holds
nationality and visa status fixed and looks <strong>within</strong> the H-1B workforce, at
the gap between men and women &mdash; a cut that paper doesn't report.</em></p>

<h2>What the raw numbers look like (and why they mislead)</h2>
<p>Trimmed to $20k&ndash;$1M (raw values run from $0.01 to $169M, so trimming is
mandatory):</p>
<ul>
<li>Men: mean $102,766 / median $94,000 (n = 244,503)</li>
<li>Women: mean $98,014 / median $90,057 (n = 119,682)</li>
<li>Raw gap: <strong>+4.8% mean, +4.4% median</strong> &mdash; and narrowing over time
(+6.9% FY21 &rarr; +3.9% FY24).</li>
</ul>
<p>Taken alone, that looks like a pay-equity problem. But H-1B base pay is anchored to
the Labor Condition Application position wage, so within a given role there is little
room for two workers to be paid differently &mdash; the aggregate gap has to come from
<em>composition</em> (who holds which job), not from unequal pay inside a job.</p>

<h2>The decomposition</h2>
<p>Comparing men and women <strong>within the same job title</strong> (title&times;fiscal
year strata, at least 20 of each gender, weighted by stratum size):</p>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Comparison</th><th class="text-end">Strata</th>
<th class="text-end">Petitions</th><th class="text-end">Adjusted gap</th></tr></thead>
<tbody>
<tr><td>Within job title</td><td class="text-end">388</td><td class="text-end">107,068</td><td class="text-end fw-bold">+0.29% mean / &minus;0.85% median</td></tr>
<tr><td>Within employer</td><td class="text-end">275</td><td class="text-end">93,245</td><td class="text-end">+5.3% mean</td></tr>
<tr><td>Within title &times; employer</td><td class="text-end">401</td><td class="text-end">50,121</td><td class="text-end">+1.0% mean</td></tr>
</tbody></table>
</div>
<p>The 4% raw gap essentially disappears within identical titles. Within an employer it
<em>widens</em> &mdash; because at a given company men and women hold different,
differently-leveled titles; hold the title fixed too and it collapses back to ~1%.</p>

<h2>The most striking result: the 25% "Chinese-born gap" vanishes</h2>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Origin</th><th class="text-end">Raw mean gap</th>
<th class="text-end">Raw median gap</th><th class="text-end">Adjusted (within title)</th></tr></thead>
<tbody>
<tr><td>India-born <span class="text-muted small">(n=244,517)</span></td><td class="text-end">+0.9%</td><td class="text-end">+0.5%</td><td class="text-end fw-bold">&minus;0.2%</td></tr>
<tr><td>China-born <span class="text-muted small">(n=53,075)</span></td><td class="text-end fw-bold">+16.4%</td><td class="text-end fw-bold">+25.4%</td><td class="text-end fw-bold">+0.7%</td></tr>
<tr><td>Other-born <span class="text-muted small">(n=66,593)</span></td><td class="text-end">+15.4%</td><td class="text-end">&mdash;</td><td class="text-end">+2.9%</td></tr>
</tbody></table>
</div>
<p>India-born workers &mdash; two-thirds of the sample &mdash; show ~0 gap even before
controls, which is what drags the overall figure down to 4%. The eye-catching
16&ndash;25% raw gaps among Chinese- and other-born beneficiaries collapse to 3% or less
once you compare the same job. Occupational sorting, not unequal pay.</p>
<p>Education explains nothing (the raw gap persists within Bachelor's / Master's /
Doctorate), and age composition works <em>against</em> the raw gap (men are older, and
older bands show the <em>smallest</em> gaps).</p>

<h2>What this comparison does and doesn't show</h2>
<ul>
<li><strong>Titles encode seniority.</strong> "Senior Software Engineer" is a title, so
equal pay <em>within</em> a title does not rule out gendered differences in
<em>reaching</em> the senior title in the first place. This method controls for the job
someone holds, not the path to it &mdash; the same limitation that applies to any
controlled pay-gap number.</li>
<li><strong>Base pay only.</strong> The I-129 reports prospective base compensation
&mdash; no equity or bonus, which is exactly where tech-sector gender gaps tend to
concentrate. This is a floor-wage comparison, not total comp.</li>
<li><strong>Employer-reported, prospective.</strong> <code>BEN_COMP_PAID</code> is the
rate of pay stated on the petition, not verified payroll.</li>
<li><strong>Sample.</strong> New-hire cap-lottery petitions, FY21&ndash;24. 33.5% of
rows have a blank job title (a redaction-era source artifact); the decomposition uses
only the rows with a title, and the raw gap is nearly identical in the blank (+5.5%) and
non-blank (+4.5%) halves, so dropping them doesn't skew the result. (Treating the
blank-title rows as their own occupational group would instead manufacture a spurious
+3.1% "within-occupation" gap, which is why they're excluded rather than pooled.)</li>
</ul>

<h2>A related figure: reported pay vs the posted wage</h2>
<p>The same data lets you compare each worker's reported pay to the wage posted on the
Labor Condition Application. The median tells the honest story: the ratio is
<strong>exactly 1.000</strong> &mdash; the typical H-1B worker's reported pay equals the
posted wage, and 71.8% are within &plusmn;1% of it. The often-cited "+19&ndash;24%" is a
<strong>mean</strong> effect driven entirely by the upper quartile. So "H-1B workers are
paid ~20% above the posted wage" is not a defensible summary; "the typical worker is paid
the posted wage, and about one in four is paid above it, sometimes well above" is.</p>

<h2>Explore the pay data yourself</h2>
<p>The <a href="/h1b-salary/">H-1B salary explorer</a> shows reported-vs-posted pay for
each occupation &mdash; for example
<a href="/h1b-salary/software-engineer/">software engineers</a> &mdash; and
<a href="/salaries/">the wage search</a> lets you filter certified H-1B and PERM wages by
employer, role and state. Individual <a href="/employers/">employer profiles</a> break
the same comparison down company by company.</p>
"""
    return Story(
        title="The H-1B “gender pay gap” is a sorting story, not an unequal-pay story",
        slug="h1b-gender-pay-gap-decomposition",
        content=body + _ATTRIBUTION,
    )


def _story_c() -> Story:
    body = """
<p class="lead">Before the 2024 rule change, your H-1B lottery odds weren't a single
number &mdash; they depended on how many employers registered you. In FY2024, a
single-registration beneficiary had about a <strong>25%</strong> chance of selection;
the average multi-registered beneficiary (~4.3 registrations) had about
<strong>70% &mdash; a 2.8&times; advantage</strong>. The FY2025 beneficiary-centric rule
deleted that asymmetry &mdash; <strong>the same odds for everyone</strong> &mdash; and the
multi-registered entries that had skewed the lottery collapsed
(408,891 &rarr; 47,314 in a year).</p>

<p class="text-muted"><em>The headline per-year selection rates here are USCIS's own,
widely republished; the mechanics of the FY2025 change trace to
<a href="https://www.federalregister.gov/documents/2024/02/02/2024-01770/improving-the-h-1b-registration-selection-process-and-program-integrity">its
rulemaking</a> (and the market design of lottery reforms to
<a href="https://www.nber.org/papers/w26767">NBER w26767</a>). What this page adds is one
step those numbers usually skip: conditioning the odds on <strong>how many times a person
was registered</strong> &mdash; which, before FY2025, is what actually set them.</em></p>

<h2>Layer 1 &mdash; the per-registration selection rate</h2>
<p>Selections &divide; eligible registrations, from USCIS:</p>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Cap FY</th><th class="text-end">Eligible registrations</th>
<th class="text-end">Selected</th><th class="text-end">Per-registration rate</th></tr></thead>
<tbody>
<tr><td>2021</td><td class="text-end">269,424</td><td class="text-end">124,415</td><td class="text-end">46.2%</td></tr>
<tr><td>2022</td><td class="text-end">301,447</td><td class="text-end">131,924</td><td class="text-end">43.8%</td></tr>
<tr><td>2023</td><td class="text-end">474,421</td><td class="text-end">127,600</td><td class="text-end">26.9%</td></tr>
<tr><td>2024</td><td class="text-end">758,994</td><td class="text-end">188,400</td><td class="text-end">24.8%</td></tr>
<tr><td>2025</td><td class="text-end">470,342</td><td class="text-end">~135,137</td><td class="text-end">~28.7% per reg <span class="text-muted small">(28.9% per beneficiary)</span></td></tr>
<tr><td>2026</td><td class="text-end">343,981</td><td class="text-end">120,141</td><td class="text-end">~34.9%</td></tr>
</tbody></table>
</div>
<p><strong>Caveat that rides this table:</strong> FY2021&ndash;22 rates are inflated
because USCIS ran multiple selection rounds when many selectees never filed. "Selected"
is not "got an H-1B."</p>

<h2>Layer 2 &mdash; odds per beneficiary, by registration count (pre-FY25)</h2>
<p>Selection was uniform across registrations, so a beneficiary with <em>k</em>
registrations had roughly 1 &minus; (1 &minus; p)<sup>k</sup> odds:</p>
<div class="table-responsive">
<table class="table table-sm table-striped align-middle">
<thead><tr><th>Cap FY</th><th class="text-end">p (per reg)</th><th class="text-end">k = 1</th>
<th class="text-end">k = 2</th><th class="text-end">k = 3</th><th class="text-end">k = 5</th></tr></thead>
<tbody>
<tr><td>2023</td><td class="text-end">26.9%</td><td class="text-end">26.9%</td><td class="text-end">46.6%</td><td class="text-end">61.0%</td><td class="text-end">79.2%</td></tr>
<tr><td>2024</td><td class="text-end">24.8%</td><td class="text-end">24.8%</td><td class="text-end">43.5%</td><td class="text-end">57.5%</td><td class="text-end">76.0%</td></tr>
</tbody></table>
</div>
<p>FY2024 concretely: the average multi-registered beneficiary held ~4.3 registrations
(408,891 multi-reg registrations &divide; ~95,897 multi-reg beneficiaries, using USCIS's
~446,000 unique-beneficiary figure), for <strong>~70% odds vs 24.8% for a single
registration &mdash; a 2.8&times; advantage</strong>. That asymmetry is exactly what the
FY2025 rule removed: every beneficiary now has identical odds regardless of employer
count &mdash; 28.9% in FY25, ~35% in FY26. The odds rose because the pool got smaller,
but that shrinkage isn't all the counting rule: the FY2026 registration fee jumped from
$10 to $215 and the tech-hiring market cooled, both of which cut registrations
independently of the beneficiary-centric change.</p>

<h2>Layer 3 &mdash; corroboration from the FOIA microdata</h2>
<p>Our selected-and-filed petitions show the multi-registration share rising
8.2% &rarr; 25.5% (FY21&rarr;24) while the registration-pool share rose
10.4% &rarr; 53.9% &mdash; demonstrating both the over-selection advantage and the lower
filing propensity of speculative multi-registrations. (See
<a href="/analysis/h1b-multi-registration-lottery-gaming/">the multi-registration
story</a>.)</p>

<h2>How to read these numbers</h2>
<ul>
<li>These are odds of <strong>selection</strong>, never "odds of a visa" &mdash; selected
registrations still must be filed and approved.</li>
<li>FY21/22 per-registration rates are inflated by multiple non-filing rounds.</li>
<li>The k-conditional table uses the binomial identity 1 &minus; (1 &minus; p)<sup>k</sup>
(an independence approximation; the finite-population correction is negligible at
k &le; 10 out of 759k). The only estimated input &mdash; the ~4.3 average registrations
&mdash; traces to USCIS's own published ~446k unique-beneficiary count.</li>
<li>A bare "your odds were X% in FY2024" is misleading without the single-vs-multi
conditioning; the unconditional number was practically meaningless pre-FY25, which is
the whole point.</li>
</ul>

<h2>Explore the data yourself</h2>
<p>The multi-registration behavior behind these odds is broken down in
<a href="/analysis/h1b-multi-registration-lottery-gaming/">the multi-registration
story</a>, and the pay side in
<a href="/analysis/h1b-gender-pay-gap-decomposition/">the H-1B pay decomposition</a>.
For the workers who were selected and filed, <a href="/salaries/">the wage search</a>
shows certified pay by employer, role and state.</p>
"""
    return Story(
        title="H-1B lottery odds depended on how many times you were registered",
        slug="h1b-lottery-odds-by-year",
        content=body + _ATTRIBUTION,
    )


def create_i129_story_posts() -> list[BlogPost]:
    posts = []
    for story in (_story_a(), _story_b(), _story_c()):
        post, created = BlogPost.objects.update_or_create(
            slug=story.slug,
            defaults={
                "title": story.title,
                "content": _TABLE_STYLE + story.content,
                "is_published": True,
                "category": CATEGORY,
                "related_bulletin": None,
            },
        )
        logger.info(
            "%s data-story post: '%s' (slug: %s)",
            "Created" if created else "Updated",
            post.title,
            post.slug,
        )
        posts.append(post)
    return posts


# The site wraps blog bodies in Bootstrap's .text-break
# (word-break: break-word !important), which breaks tokens mid-character inside
# narrow table columns: "34.9%" -> "34." / "9%", "FY21" -> "FY2" / "1". Reset table
# cells to normal word-breaking so single tokens (numbers, %, FY-codes) stay whole
# while multi-word headers still wrap between words. !important beats .text-break's.
_TABLE_STYLE = (
    "<style>.blog-content table td,.blog-content table th"
    "{overflow-wrap:normal!important;word-break:normal!important;}</style>\n"
)


def main() -> None:
    log_context("Generating I-129 FOIA data-story /analysis/ pages (a/b/c)")
    logger.info("=== Generating I-129 data-story posts ===")
    posts = create_i129_story_posts()
    logger.info("Done. %d posts published at /analysis/:", len(posts))
    for p in posts:
        logger.info("  /analysis/%s/", p.slug)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Failed to generate I-129 data-story posts")

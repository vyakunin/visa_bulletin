"""Tests for the view-facing demographic actual-pay panel.

The stats layer (test_i129_demographic_pay.py) already locks the arithmetic. This file
locks the publishing decisions layered on top — the ones that keep the rendered
component honest and keep it off the request path:

1. Field of study is not publishable. It is excluded for a measured reason recorded in
   the module docstring, so a future session that adds it back trips a test and reads
   the reason first.
2. A value whose within-occupation figure was suppressed becomes a COUNT, never a row.
   Listing it would rank groups by exactly the raw gap our methodology page corrects.
3. A dimension with only one comparable value is dropped: one row is not a comparison.
4. The "explained by job mix" share is withheld unless it reads sanely (0-100%).
5. The site-wide panel is READ FROM CACHE ONLY. A cold cache must issue no queries and
   render nothing — that is the guarantee that the section cannot add ~9s to a page.
"""

from decimal import Decimal

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import TestCase

from lib.business.i129.demographic_pay import DemographicPayCell, PayDimension
from lib.business.i129.demographic_pay_panel import (
    PUBLISHED_DIMENSIONS,
    PanelRow,
    _row_label,
    build_demographic_pay_panel,
    get_employer_demographic_pay,
    get_sitewide_demographic_pay,
    warm_sitewide_demographic_pay,
)
from models.i129 import I129Petition
from models.salary import EmployerCluster


def _petitions(country, job_title, pay, count, *, cluster=None, start=0):
    """`count` petitions sharing a country / title / pay, with unique case numbers."""
    I129Petition.objects.bulk_create(
        [
            I129Petition(
                dol_eta_case_number=f"I-200-{country}-{job_title[:4]}-{start + i:06d}",
                fiscal_year=2023,
                country_of_birth=country,
                job_title=job_title,
                pay_annual=Decimal(pay),
                employer_cluster=cluster,
            )
            for i in range(count)
        ]
    )


def _cell(**kwargs) -> DemographicPayCell:
    defaults = dict(
        value="AAA",
        n=1000,
        median_pay=100_000,
        mean_pay=100_000,
        raw_gap=10_000,
        within_occupation_gap=5_000,
        adjusted_n=1000,
        strata_count=4,
    )
    return DemographicPayCell(**{**defaults, **kwargs})


class PublishedDimensionsTests(TestCase):
    def test_field_of_study_is_not_published(self):
        """Measured 2026-08-09: field_of_study survives adjustment but its values are
        un-normalized free text (40,975 distinct strings; the same degree spelled seven
        ways among the 21 publishable, with contradictory adjusted gaps). Publishing it
        needs a normalization layer that does not exist — see the module docstring."""
        self.assertNotIn(PayDimension.FIELD_OF_STUDY, PUBLISHED_DIMENSIONS)

    def test_gender_is_published_as_the_control(self):
        """Gender is the dimension whose gap vanishes; it is what shows the method is
        not manufacturing the gaps the other dimensions report."""
        self.assertIn(PayDimension.GENDER, PUBLISHED_DIMENSIONS)

    def test_published_dimensions_are_all_valid(self):
        self.assertNotIn(PayDimension.INVALID, PUBLISHED_DIMENSIONS)


class PanelRowTests(TestCase):
    def test_sorting_share_withheld_when_it_reads_as_nonsense(self):
        """A gap the adjustment flips past zero scores over 100%; one it widens scores
        negative. Both are real, and both read as a bug in a percentage column."""
        overshot = PanelRow(label="Women", cell=_cell(raw_gap=-2685, within_occupation_gap=469))
        self.assertGreater(overshot.cell.sorting_share_pct, 100.0)
        self.assertIsNone(overshot.sorting_share_pct, "over 100% must not be rendered")

        widened = PanelRow(label="X", cell=_cell(raw_gap=7468, within_occupation_gap=14169))
        self.assertLess(widened.cell.sorting_share_pct, 0.0)
        self.assertIsNone(widened.sorting_share_pct, "negative must not be rendered")

    def test_sorting_share_passes_through_when_sane(self):
        row = PanelRow(label="China", cell=_cell(raw_gap=17315, within_occupation_gap=8896))
        self.assertAlmostEqual(row.sorting_share_pct, 48.6, places=1)

    def test_gaps_render_with_an_explicit_sign(self):
        row = PanelRow(label="India", cell=_cell(raw_gap=-2288, within_occupation_gap=8896))
        self.assertEqual(row.raw_gap_display, "-$2,288")
        self.assertEqual(row.within_occupation_gap_display, "+$8,896")

    def test_country_codes_become_names_and_unknown_codes_survive(self):
        panel_rows = {
            r.label
            for r in _country_panel_rows(["IND", "CHN"])
        }
        self.assertEqual(panel_rows, {"India", "China"})
        self.assertEqual({r.label for r in _country_panel_rows(["ZZZ"])}, {"ZZZ"})


def _country_panel_rows(codes):
    return [
        PanelRow(label=_row_label(PayDimension.COUNTRY_OF_BIRTH, c), cell=_cell(value=c))
        for c in codes
    ]


class PanelAssemblyTests(TestCase):
    def test_suppressed_values_are_counted_never_listed(self):
        """The TWN/KOR case: enough petitions to list, too little overlap to adjust.

        Such a value must not appear as a row — its raw gap is the sorting artifact the
        table exists to correct, so ranking it beside corrected figures misleads.
        """
        _petitions("AAA", "Engineer", 120_000, 2_000)
        _petitions("BBB", "Engineer", 100_000, 2_000, start=10_000)
        # Listed (over the value floor) but its only job title is too small to be a
        # comparison stratum, so nothing of it enters the adjusted figure.
        _petitions("THN", "Rare Job", 200_000, 110, start=90_000)

        panel = build_demographic_pay_panel()
        section = panel.sections[0]

        self.assertEqual({r.cell.value for r in section.rows}, {"AAA", "BBB"})
        self.assertEqual(section.withheld_values, 1)
        self.assertEqual(section.withheld_petitions, 110)
        for row in section.rows:
            self.assertIsNotNone(row.cell.within_occupation_gap)

    def test_dimension_with_one_comparable_value_is_dropped(self):
        """One row is a number with nothing to compare it to; the table claims a
        comparison, so the whole section goes rather than render a lone row."""
        _petitions("AAA", "Engineer", 120_000, 2_000)
        _petitions("THN", "Rare Job", 200_000, 110, start=90_000)

        self.assertIsNone(build_demographic_pay_panel())

    def test_dimensions_with_no_data_are_skipped_not_rendered_empty(self):
        """The fixture carries no gender or education, so only country survives."""
        _petitions("AAA", "Engineer", 120_000, 2_000)
        _petitions("BBB", "Engineer", 100_000, 2_000, start=10_000)

        panel = build_demographic_pay_panel()
        labels = [s.dimension_label for s in panel.sections]
        self.assertEqual(labels, [PayDimension.COUNTRY_OF_BIRTH.label])

    def test_employer_scope_restricts_the_population(self):
        cluster = EmployerCluster.objects.create(canonical_name="Test Co")
        _petitions("AAA", "Engineer", 200_000, 1_000, cluster=cluster)
        _petitions("BBB", "Engineer", 180_000, 1_000, cluster=cluster, start=10_000)
        _petitions("AAA", "Engineer", 100_000, 1_000, start=20_000)

        panel = get_employer_demographic_pay(cluster)
        self.assertEqual(panel.overall_n, 2_000)
        self.assertEqual({r.cell.median_pay for r in panel.sections[0].rows},
                         {200_000, 180_000})

    def test_employer_scope_without_an_id_returns_none(self):
        self.assertIsNone(get_employer_demographic_pay(object()))


class SitewideCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_cold_cache_returns_none_and_runs_no_queries(self):
        """The perf guarantee. Each dimension costs ~3s against the real table, so a
        request must never be the thing that computes them."""
        _petitions("AAA", "Engineer", 120_000, 2_000)
        _petitions("BBB", "Engineer", 100_000, 2_000, start=10_000)

        with self.assertNumQueries(0):
            self.assertIsNone(get_sitewide_demographic_pay())

    def test_warmer_populates_what_the_reader_returns(self):
        _petitions("AAA", "Engineer", 120_000, 2_000)
        _petitions("BBB", "Engineer", 100_000, 2_000, start=10_000)

        warmed = warm_sitewide_demographic_pay()
        self.assertIsNotNone(warmed)

        with self.assertNumQueries(0):
            served = get_sitewide_demographic_pay()
        self.assertEqual(
            [r.cell.value for r in served.sections[0].rows],
            [r.cell.value for r in warmed.sections[0].rows],
        )

    def test_a_warmed_empty_result_is_not_mistaken_for_a_cold_cache(self):
        """Nothing publishable is a legitimate outcome; caching it stops every request
        re-deciding that, and it must not look like the warmer never ran."""
        self.assertIsNone(warm_sitewide_demographic_pay())
        with self.assertNumQueries(0):
            self.assertIsNone(get_sitewide_demographic_pay())


class TemplateTests(TestCase):
    """The component's contract with the reader, asserted on rendered HTML."""

    TEMPLATE = "webapp/_i129_demographic_pay.html"

    def _render(self, **extra):
        _petitions("AAA", "Engineer", 120_000, 2_000)
        _petitions("BBB", "Engineer", 100_000, 2_000, start=10_000)
        context = {
            "demographic_pay": build_demographic_pay_panel(),
            "scope_label": "every H-1B lottery petition we hold",
        }
        context.update(extra)
        return render_to_string(self.TEMPLATE, context)

    def test_renders_nothing_without_a_panel(self):
        html = render_to_string(self.TEMPLATE, {"demographic_pay": None})
        self.assertEqual(html.strip(), "")

    def test_leads_with_the_within_occupation_figure_and_labels_the_raw_one(self):
        """Showing raw medians as pay differences would contradict our own published
        decomposition, so the corrected column is the headline and the raw one is
        explicitly the thing being corrected."""
        html = self._render()
        self.assertIn("Within the same job title", html)
        self.assertIn("Raw gap", html)
        self.assertLess(
            html.index("within the same job title"),
            html.index("<table"),
            "the correction must be explained before the table, not under it",
        )

    def test_carries_the_binding_caveats_where_a_reader_sees_them(self):
        html = self._render()
        self.assertIn("base pay only", html.lower())
        self.assertIn("FY2021", html)
        self.assertIn("cap-subject", html)
        self.assertIn("sourced from USCIS, obtained by Bloomberg", html)

    def test_links_the_methodology_page_it_must_not_contradict(self):
        html = self._render(sitewide=True)
        self.assertIn("/analysis/h1b-gender-pay-gap-decomposition/", html)

    def test_the_sitewide_finding_is_withheld_from_an_employer_scope(self):
        """An employer's own numbers need not follow the site-wide pattern, so the
        claim about which dimensions survive adjustment is only made site-wide."""
        self.assertNotIn("Gender is here as the control", self._render())

    def test_pay_figures_cannot_wrap_mid_number(self):
        """These are dollar amounts; `$17,315` broken across lines is the content
        failing. Every numeric cell pins itself (blog_content_html.md)."""
        html = self._render()
        for fragment in html.split("<td")[1:]:
            cell = fragment.split("</td>")[0]
            if "$" in cell or "%" in cell:
                self.assertIn("text-nowrap", cell, f"unpinned numeric cell: {cell[:80]}")

    def test_uses_h2_h3_without_introducing_a_second_h1(self):
        html = self._render()
        self.assertNotIn("<h1", html)
        self.assertIn("<h2", html)
        self.assertIn("<h3", html)

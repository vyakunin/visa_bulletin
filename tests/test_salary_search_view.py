"""Tests for salary search landing page behavior."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from models.enums.visa_program import CaseStatus, VisaProgram
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster, SalaryRecord


class SalarySearchLandingViewTest(TestCase):
    """Test salary search landing page overview behavior."""

    def setUp(self):
        self.client = Client()
        cache.clear()

        employer_cluster = EmployerCluster.objects.create(
            canonical_name="Landing Test Co",
            slug="landing-test-co",
        )
        employer = Employer.objects.create(
            name="Landing Test Co",
            name_normalized="landing test co",
            canonical_cluster=employer_cluster,
        )
        job_cluster = JobTitleCluster.objects.create(
            canonical_title="Landing Engineer",
            slug="landing-engineer",
        )
        job_title = JobTitle.objects.create(
            title="Landing Engineer",
            title_normalized="landing engineer",
            canonical_cluster=job_cluster,
        )

        SalaryRecord.objects.create(
            case_number="LANDING-TEST-1",
            employer=employer,
            employer_name="Landing Test Co",
            job_title="Landing Engineer",
            job_title_entity=job_title,
            wage_annual=120000,
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2023,
            worksite_state="CA",
            is_worksite=False,
        )
        SalaryRecord.objects.create(
            case_number="LANDING-TEST-2",
            employer=employer,
            employer_name="Landing Test Co",
            job_title="Landing Engineer",
            job_title_entity=job_title,
            wage_annual=135000,
            visa_program=VisaProgram.PERM,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2024,
            worksite_state="NY",
            is_worksite=False,
        )

    def test_landing_shows_market_overview(self):
        response = self.client.get(reverse("salary_search"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("market_stats", response.context)
        self.assertIsNotNone(response.context["market_stats"])
        self.assertIn("salary_percentiles", response.context["market_stats"])
        self.assertIn("market_chart_data", response.context)
        market_chart_data = response.context["market_chart_data"]
        self.assertIn("state_filings", market_chart_data)
        self.assertIn("filing_volume", market_chart_data)

    def test_filtered_view_hides_market_overview(self):
        response = self.client.get(reverse("salary_search"), {"q": "Landing"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_filters"])
        self.assertIsNone(response.context["market_stats"])
        self.assertEqual(response.context["market_chart_data"], {})


class SalarySearchSEOTest(TestCase):
    """SERP / on-page SEO: dynamic title, description, H1, JSON-LD."""

    def setUp(self):
        self.client = Client()
        cache.clear()

        self.cluster = EmployerCluster.objects.create(
            canonical_name="Landing Test Co",
            slug="landing-test-co",
            search_record_count=2,
            search_avg_salary=127500,
            search_min_salary=120000,
            search_max_salary=135000,
        )
        employer = Employer.objects.create(
            name="Landing Test Co",
            name_normalized="landing test co",
            canonical_cluster=self.cluster,
        )
        job_cluster = JobTitleCluster.objects.create(
            canonical_title="Landing Engineer",
            slug="landing-engineer",
        )
        job_title = JobTitle.objects.create(
            title="Landing Engineer",
            title_normalized="landing engineer",
            canonical_cluster=job_cluster,
        )
        for case_number, wage, fy, state in [
            ("SEO-1", 120000, 2023, "CA"),
            ("SEO-2", 135000, 2024, "NY"),
        ]:
            SalaryRecord.objects.create(
                case_number=case_number,
                employer=employer,
                employer_name="Landing Test Co",
                job_title="Landing Engineer",
                job_title_entity=job_title,
                wage_annual=wage,
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=fy,
                worksite_state=state,
                is_worksite=False,
            )

    def test_bare_landing_keeps_static_title(self):
        response = self.client.get(reverse("salary_search"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["page_title"],
            "H-1B & PERM Salary Database — 1.5M+ Real DOL Filings",
        )
        # Title must stay short enough to avoid SERP truncation (~60 chars).
        self.assertLessEqual(len(response.context["page_title"]), 60)
        # Bare landing still emits no intro paragraph.
        self.assertIsNone(response.context["page_intro"])

    def test_bare_landing_emits_corpus_dataset_jsonld(self):
        # Regression: the bare /salaries/ landing ranks for "h1b salary
        # database" et al., so it must carry a corpus-level Dataset rich
        # result (previously it emitted no structured data at all).
        response = self.client.get(reverse("salary_search"))

        payload = response.context["structured_data"]
        self.assertIsNotNone(payload)
        self.assertIn('"@type": "Dataset"', payload)
        self.assertIn("Salary Database", payload)
        # Embedded payload must be safe for <script> context (no raw < / >).
        self.assertNotIn("</script>", payload)

    def test_dynamic_title_for_employer_slug(self):
        response = self.client.get(
            reverse("salary_search"),
            {"employer_slug": "landing-test-co", "employer": "Landing Test Co"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Landing Test Co", response.context["page_title"])
        self.assertIn("H-1B & PERM", response.context["page_title"])
        self.assertIn("Landing Test Co", response.context["page_heading"])
        self.assertIn("Landing Test Co", response.context["page_description"])
        self.assertIn("Landing Test Co", response.content.decode("utf-8"))

    def test_dynamic_title_for_employer_plus_query(self):
        response = self.client.get(
            reverse("salary_search"),
            {
                "employer_slug": "landing-test-co",
                "employer": "Landing Test Co",
                "q": "Engineer",
            },
        )

        self.assertEqual(response.status_code, 200)
        title = response.context["page_title"]
        self.assertIn("Engineer", title)
        self.assertIn("Landing Test Co", title)
        self.assertIn("at", title)

    def test_dynamic_title_for_state(self):
        response = self.client.get(reverse("salary_search"), {"state": "CA"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("California", response.context["page_title"])
        self.assertIn("H-1B & PERM", response.context["page_title"])

    def test_dynamic_title_for_query_only(self):
        response = self.client.get(reverse("salary_search"), {"q": "Engineer"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Engineer", response.context["page_title"])
        self.assertIn("Salaries", response.context["page_title"])

    def test_dynamic_intro_renders_in_body(self):
        response = self.client.get(
            reverse("salary_search"),
            {"employer_slug": "landing-test-co", "employer": "Landing Test Co"},
        )

        body = response.content.decode("utf-8")
        self.assertIsNotNone(response.context["page_intro"])
        self.assertIn(response.context["page_intro"], body)
        # H1 carries the dynamic heading.
        self.assertIn(f"<h1 class=\"h3 mb-2\">{response.context['page_heading']}</h1>", body)

    def test_jsonld_dataset_present_when_employer_active(self):
        response = self.client.get(
            reverse("salary_search"),
            {"employer_slug": "landing-test-co", "employer": "Landing Test Co"},
        )

        payload = response.context["structured_data"]
        self.assertIsNotNone(payload)
        self.assertIn('"@type": "Dataset"', payload)
        self.assertIn("Landing Test Co", payload)
        # Embedded payload must be safe for <script> context (no raw < / >).
        self.assertNotIn("</script>", payload)

    def test_jsonld_dataset_absent_for_query_only(self):
        response = self.client.get(reverse("salary_search"), {"q": "Engineer"})

        self.assertIsNone(response.context["structured_data"])

    def test_meta_description_within_cap(self):
        # Worst case: every filter active. Description should still respect
        # the SERP-snippet cap (165 chars) so Google doesn't truncate keywords.
        response = self.client.get(
            reverse("salary_search"),
            {
                "employer_slug": "landing-test-co",
                "employer": "Landing Test Co",
                "q": "Engineer",
                "state": "CA",
                "program": "h1b",
                "year": "2024",
            },
        )

        description = response.context["page_description"]
        self.assertLessEqual(len(description), 165, description)


class SalarySearchPageCapTest(TestCase):
    """Deep-OFFSET cap: bots that crawl /salaries/?page=1263 used to drive
    Postgres to materialize 63k+ sorted rows per request, exhausting shared
    memory. Past page=100 we return 410 Gone instead.
    """

    def setUp(self):
        self.client = Client()
        cache.clear()

    def test_page_100_still_renders(self):
        # The cap is inclusive: page=100 is the last allowed listing page.
        response = self.client.get(reverse("salary_search"), {"page": "100"})
        self.assertEqual(response.status_code, 200)

    def test_page_101_returns_410(self):
        response = self.client.get(reverse("salary_search"), {"page": "101"})
        self.assertEqual(response.status_code, 410)

    def test_bot_crawl_page_1263_returns_410(self):
        # Real-world bot-crawl pattern that triggered shm exhaustion.
        response = self.client.get(reverse("salary_search"), {"page": "1263"})
        self.assertEqual(response.status_code, 410)

    def test_page_cap_with_filters_returns_410(self):
        response = self.client.get(
            reverse("salary_search"),
            {"page": "500", "q": "Engineer", "state": "CA"},
        )
        self.assertEqual(response.status_code, 410)

    def test_worksite_page_cap_returns_410(self):
        response = self.client.get(reverse("worksite_search"), {"page": "1263"})
        self.assertEqual(response.status_code, 410)

    def test_worksite_page_100_still_renders(self):
        response = self.client.get(reverse("worksite_search"), {"page": "100"})
        self.assertEqual(response.status_code, 200)


class SalarySearchNoindexTest(TestCase):
    """Crawl-budget hygiene: the free-text ?q= keyword space is unbounded
    (every distinct query = a new URL), so those pages emit
    `<meta name="robots" content="noindex, follow">`. Bare landings, curated
    filter combos (employer/state/program, no q), and slug pages stay
    indexable (no robots meta = default index, follow).
    """

    def setUp(self):
        self.client = Client()
        cache.clear()
        self.cluster = EmployerCluster.objects.create(
            canonical_name="Noindex Test Co",
            slug="noindex-test-co",
            search_record_count=1,
            search_avg_salary=120000,
            search_min_salary=120000,
            search_max_salary=120000,
        )

    def _robots_meta_present(self, response) -> bool:
        return (
            b'<meta name="robots" content="noindex, follow">'
            in response.content
        )

    def test_freetext_q_search_is_noindex(self):
        response = self.client.get(reverse("salary_search"), {"q": "Engineer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["meta_robots"], "noindex, follow")
        self.assertTrue(self._robots_meta_present(response))

    def test_bare_landing_stays_indexable(self):
        response = self.client.get(reverse("salary_search"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["meta_robots"])
        self.assertFalse(self._robots_meta_present(response))

    def test_curated_filter_without_q_stays_indexable(self):
        # An employer-slug or state filter (no free-text q) is a bounded,
        # curated page the dynamic-SEO design wants indexed.
        for params in (
            {"state": "CA"},
            {"employer_slug": "noindex-test-co", "employer": "Noindex Test Co"},
            {"program": "h1b"},
        ):
            with self.subTest(params=params):
                response = self.client.get(reverse("salary_search"), params)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context["meta_robots"])
                self.assertFalse(self._robots_meta_present(response))

    def test_employer_plus_q_is_noindex(self):
        # Any request carrying ?q= is noindex, even alongside a curated filter.
        response = self.client.get(
            reverse("salary_search"),
            {"employer_slug": "noindex-test-co", "q": "Engineer"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["meta_robots"], "noindex, follow")
        self.assertTrue(self._robots_meta_present(response))

    def test_worksite_freetext_q_search_is_noindex(self):
        response = self.client.get(reverse("worksite_search"), {"q": "Engineer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["meta_robots"], "noindex, follow")
        self.assertTrue(self._robots_meta_present(response))

    def test_worksite_bare_landing_stays_indexable(self):
        response = self.client.get(reverse("worksite_search"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["meta_robots"])
        self.assertFalse(self._robots_meta_present(response))

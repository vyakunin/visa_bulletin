"""Precomputed default renders of job-title, sponsor and employer pages."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.core.cache import cache, caches
from django.test import TestCase

from lib.business.salary import h1b_salary_pair, h1b_sponsors
from lib.business.salary.common_stats import calculate_salary_percentiles
from lib.business.salary.job_title_stats import (
    _precomputed_profile_key,
    get_job_title_statistics,
)
from lib.business.salary.precomputed_profiles import (
    clear_precomputed_profiles,
    stored_profile_keys,
)
from models.enums.visa_program import CaseStatus, VisaProgram, WageUnit
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster, SalaryRecord
from scripts.cache import warm_profiles
from webapp.views.employers import profile as employer_profile

AGGREGATES = caches[settings.AGGREGATES_CACHE_ALIAS]


class PrecomputedProfilesTest(TestCase):
    def setUp(self):
        cache.clear()
        AGGREGATES.clear()
        self.emp_cluster = EmployerCluster.objects.create(
            canonical_name="Precomp Corp", slug="precomp-corp", total_lca_count=40
        )
        self.employers = [
            Employer.objects.create(
                name=f"Precomp Corp {i}",
                name_normalized=f"precomp corp {i}",
                state="CA",
                canonical_cluster=self.emp_cluster,
            )
            for i in range(2)
        ]
        self.cluster = JobTitleCluster.objects.create(
            canonical_title="Precomp Engineer", slug="precomp-engineer", total_filings=40
        )
        self.titles = [
            JobTitle.objects.create(
                title=f"Precomp Engineer {level}",
                title_normalized="precomp engineer",
                experience_level=level,
                canonical_cluster=self.cluster,
            )
            for level in ("", "senior")
        ]
        for i in range(40):
            SalaryRecord.objects.create(
                case_number=f"PRECOMP-{i}",
                employer_name="Precomp Corp",
                employer=self.employers[i % 2],
                job_title="Precomp Engineer",
                job_title_entity=self.titles[i % 2],
                worksite_city="San Jose",
                worksite_state=("CA", "WA")[i % 2],
                wage_unit=WageUnit.YEAR,
                wage_annual=Decimal(100000 + 1000 * i),
                visa_program=VisaProgram.H1B,
                case_status=CaseStatus.CERTIFIED,
                fiscal_year=2025,
                source_file="test.xlsx",
                is_worksite=False,
            )

    def test_ids_in_cluster_lists_the_members(self):
        self.assertEqual(
            sorted(JobTitle.ids_in_cluster(self.cluster.id)), sorted(t.id for t in self.titles)
        )
        self.assertEqual(
            sorted(Employer.ids_in_cluster(self.emp_cluster.id)),
            sorted(e.id for e in self.employers),
        )

    def test_default_job_title_render_reads_the_stored_profile(self):
        AGGREGATES.set(_precomputed_profile_key(self.cluster.id), {"stored": True})
        with self.assertNumQueries(1):  # the store lookup, no salary_record aggregate
            self.assertEqual(get_job_title_statistics(self.cluster, 5, "all"), {"stored": True})

    def test_filtered_job_title_render_ignores_the_stored_profile(self):
        AGGREGATES.set(_precomputed_profile_key(self.cluster.id), {"stored": True})
        stats = get_job_title_statistics(self.cluster, 5, "h1b")
        self.assertEqual(stats["basic"]["total_filings"], 40)

    def test_sponsor_page_and_counts_read_the_stored_page(self):
        AGGREGATES.set(h1b_sponsors._sponsor_page_key(self.cluster.id), {"filings": 7, "sponsors": 3})
        with mock.patch.object(h1b_sponsors, "role_h1b_stats") as live:
            self.assertEqual(h1b_sponsors.role_sponsor_page(self.cluster.id)["filings"], 7)
            self.assertEqual(h1b_sponsors.role_sponsor_counts(self.cluster.id), (7, 3))
        live.assert_not_called()

    def test_employer_default_render_reads_the_stored_payload_and_others_do_not(self):
        start = employer_profile.employer_profile_window_start(5)
        AGGREGATES.set(
            employer_profile._precomputed_payload_key(self.emp_cluster.id, start),
            {"stats": "S", "chart_data": "C"},
        )
        params = {"years": 5, "program_filter": "all", "start_year": start}
        records = employer_profile._get_employer_records_queryset(self.emp_cluster, params)
        got = employer_profile._get_or_compute_page_payload(
            self.emp_cluster, records, "precomp-corp", "k-default", params
        )
        self.assertEqual(got, ("S", "C", True))
        h1b = {**params, "program_filter": "h1b"}
        stats, _, hit = employer_profile._get_or_compute_page_payload(
            self.emp_cluster, records.filter(visa_program=VisaProgram.H1B), "precomp-corp", "k-h1b", h1b
        )
        self.assertFalse(hit)
        self.assertEqual(stats["basic"]["total_filings"], 40)

    def test_warmer_stores_what_a_live_render_computes(self):
        live = get_job_title_statistics(self.cluster, 5, "all")
        cache.clear()
        rc = warm_profiles.main(
            ["--job-title-min", "1", "--sponsors-min", "1", "--employer-min", "1", "--pair-min", "1"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(
            AGGREGATES.get(_precomputed_profile_key(self.cluster.id))["basic"], live["basic"]
        )
        page = AGGREGATES.get(h1b_sponsors._sponsor_page_key(self.cluster.id))
        # One sponsor is below MIN_SPONSORS: the page 404s, so only the gate counts are kept.
        self.assertEqual(page, {"filings": 40, "sponsors": 1})
        start = employer_profile.employer_profile_window_start(5)
        payload = AGGREGATES.get(employer_profile._precomputed_payload_key(self.emp_cluster.id, start))
        self.assertEqual(payload["stats"]["basic"]["total_filings"], 40)
        pair = AGGREGATES.get(h1b_salary_pair._pair_page_key(self.emp_cluster.id, self.cluster.id))
        self.assertEqual(pair["filings"], 40)
        self.assertEqual(pair["states"][0]["filings"], 20)

    def test_warmer_skips_entities_below_the_size_floor(self):
        warm_profiles.main([
            "--kinds", "job_title,sponsors,employer,pair",
            "--job-title-min", "41", "--sponsors-min", "41", "--employer-min", "41", "--pair-min", "41",
        ])
        self.assertEqual(stored_profile_keys(), set())

    def test_missing_only_keeps_stored_entries_and_rebuild_clears_them(self):
        key = _precomputed_profile_key(self.cluster.id)
        AGGREGATES.set(key, {"stored": True})
        warm_profiles.main(["--kinds", "job_title", "--job-title-min", "1", "--missing-only"])
        self.assertEqual(AGGREGATES.get(key), {"stored": True})
        warm_profiles.main(["--kinds", "job_title", "--job-title-min", "41", "--rebuild"])
        self.assertIsNone(AGGREGATES.get(key))

    def test_clear_touches_only_profiles(self):
        AGGREGATES.set("salary_market_overview:5:all", {"kept": True})
        AGGREGATES.set(_precomputed_profile_key(self.cluster.id), {"stored": True})
        self.assertEqual(clear_precomputed_profiles(), 1)
        self.assertEqual(AGGREGATES.get("salary_market_overview:5:all"), {"kept": True})

    def test_store_keeps_more_than_three_hundred_entries(self):
        # DatabaseCache's default MAX_ENTRIES (300) would delete a third of them.
        AGGREGATES.set_many({f"profile.bulk.{i}": i for i in range(400)})
        AGGREGATES.set("profile.bulk.last", 1)
        self.assertEqual(len(stored_profile_keys()), 401)

    def test_cluster_without_members_renders_empty_stats(self):
        empty = JobTitleCluster.objects.create(canonical_title="Nobody", slug="nobody", total_filings=0)
        stats = get_job_title_statistics(empty, 5, "h1b")
        self.assertEqual(stats["basic"]["total_filings"], 0)
        self.assertEqual(
            calculate_salary_percentiles(SalaryRecord.objects.filter(job_title_entity_id__in=[]))["p50"], 0
        )

    def test_pair_page_and_role_percentiles_read_the_stored_copies(self):
        AGGREGATES.set(h1b_salary_pair._pair_page_key(self.emp_cluster.id, self.cluster.id), {"filings": 3})
        AGGREGATES.set(
            h1b_sponsors._sponsor_page_key(self.cluster.id),
            {"filings": 9, "sponsors": 9, "percentiles": {"p50": 1}},
        )
        with mock.patch.object(h1b_salary_pair, "pair_h1b_filings") as live_pair, mock.patch.object(
            h1b_sponsors, "calculate_salary_percentiles"
        ) as live_pct:
            self.assertEqual(h1b_salary_pair.pair_page(self.emp_cluster.id, self.cluster.id), {"filings": 3})
            self.assertEqual(h1b_sponsors.role_h1b_percentiles(self.cluster.id), {"p50": 1})
        live_pair.assert_not_called()
        live_pct.assert_not_called()

    def test_role_percentiles_compute_when_the_stored_page_has_none(self):
        AGGREGATES.set(h1b_sponsors._sponsor_page_key(self.cluster.id), {"filings": 40, "sponsors": 1})
        self.assertGreater(h1b_sponsors.role_h1b_percentiles(self.cluster.id)["p50"], 0)

    def test_qualifying_sets_are_none_until_warmed(self):
        self.assertIsNone(h1b_sponsors.qualifying_slugs())
        self.assertIsNone(h1b_sponsors.qualifying_state_codes())
        h1b_sponsors.warm_qualifying_state_codes()
        self.assertEqual(h1b_sponsors.qualifying_state_codes(), [])  # one sponsor: below the floor

    def test_state_pages_read_the_stored_copies(self):
        from webapp.views.salary import by_state

        AGGREGATES.set(h1b_sponsors._state_sponsor_page_key("CA"), {"filings": 1, "sponsors": 1})
        AGGREGATES.set(by_state._state_salary_page_key("CA"), {"stored": True})
        with mock.patch.object(h1b_sponsors, "state_h1b_stats") as live:
            self.assertEqual(h1b_sponsors.state_sponsor_page("CA"), {"filings": 1, "sponsors": 1})
        live.assert_not_called()
        self.assertEqual(by_state.state_salary_page("CA"), {"stored": True})

    def test_warmer_stores_both_pages_for_every_state(self):
        from lib.utils.location_utils import US_STATES
        from webapp.views.salary import by_state

        self.assertEqual(warm_profiles.main(["--kinds", "state"]), 0)
        self.assertEqual(len(stored_profile_keys()), 2 * len(US_STATES))
        ca = AGGREGATES.get(by_state._state_salary_page_key("CA"))
        self.assertEqual(ca["agg"]["total_filings"], 20)

    def test_min_max_aggregate_returns_only_the_requested_values(self):
        from django.db.models import Max, Min

        from lib.business.salary.common_stats import min_max_aggregate

        got = min_max_aggregate(SalaryRecord.objects.all(), lo=Min("wage_annual"), fy=Max("fiscal_year"))
        self.assertEqual(got, {"lo": Decimal(100000), "fy": 2025})

    def test_database_summary_reads_the_stored_copy_and_warms_the_live_one(self):
        from lib.business.salary import market_overview

        self.assertEqual(market_overview.get_salary_database_summary()["total_records"], 40)
        AGGREGATES.set("salary_database_summary", {"total_records": 7})
        self.assertEqual(market_overview.get_salary_database_summary(), {"total_records": 7})
        self.assertEqual(market_overview.warm_salary_database_summary()["total_records"], 40)

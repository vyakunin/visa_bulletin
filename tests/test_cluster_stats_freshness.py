"""Regression tests for the sitemap-freshness lever (Notion: sitemap-lastmod Part 2).

The stats-refresh path writes EmployerCluster / JobTitleCluster aggregates with
raw SQL / bulk_update, both of which BYPASS Django's ``auto_now`` on
``updated_at``. The sitemap uses ``cluster.updated_at`` as ``lastmod``, so it
would be frozen forever without an explicit bump. These tests pin the contract:

  - a cluster whose headline filing counts CHANGED this run gets a fresh
    ``updated_at`` (Google sees a real recrawl signal), and
  - a cluster whose data is UNCHANGED is left untouched (never a cosmetic
    date-bump — the failure that makes Google distrust the whole sitemap).

The transaction wrapping each TestCase freezes ``NOW()`` / ``transaction_timestamp()``,
so we cannot assert "run 2 timestamp > run 1 timestamp". Instead we force
``updated_at`` to a known PAST value via ``.update()`` (which bypasses auto_now),
mutate one cluster's inputs, re-run, and assert the changed cluster moved off
the past value while the unchanged one stayed on it.
"""

import sys
from datetime import timedelta
from unittest import mock

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase
from django.utils import timezone

from models.enums.visa_program import CaseStatus, VisaProgram
from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster, SalaryRecord
from scripts.salary.cluster_existing_employers import _update_cluster_statistics


class EmployerClusterFreshnessTest(TestCase):
    """`_update_cluster_statistics` (raw-SQL CASE path) bumps updated_at only on real change."""

    def setUp(self):
        self.cluster_a = EmployerCluster.objects.create(
            canonical_name="Alpha Corp", slug="alpha-corp"
        )
        Employer.objects.create(
            name="Alpha Corp",
            name_normalized="alpha corp",
            canonical_cluster=self.cluster_a,
            total_lca_count=10,
            total_perm_count=2,
            avg_salary=100000,
        )
        self.cluster_b = EmployerCluster.objects.create(
            canonical_name="Beta Inc", slug="beta-inc"
        )
        Employer.objects.create(
            name="Beta Inc",
            name_normalized="beta inc",
            canonical_cluster=self.cluster_b,
            total_lca_count=5,
            total_perm_count=5,
            avg_salary=90000,
        )

    def _baseline_then_freeze(self):
        """Roll up stats once, then stamp all clusters with a known past updated_at."""
        _update_cluster_statistics(batch_size=500, dry_run=False)
        self.old = timezone.now() - timedelta(days=400)
        EmployerCluster.objects.all().update(updated_at=self.old)

    def test_only_changed_cluster_is_bumped(self):
        self._baseline_then_freeze()
        # New filings land for Alpha only.
        Employer.objects.filter(canonical_cluster=self.cluster_a).update(
            total_lca_count=20
        )

        _update_cluster_statistics(batch_size=500, dry_run=False)

        self.cluster_a.refresh_from_db()
        self.cluster_b.refresh_from_db()
        self.assertGreater(
            self.cluster_a.updated_at, self.old, "changed cluster must be bumped"
        )
        self.assertEqual(
            self.cluster_b.updated_at, self.old, "unchanged cluster must NOT be bumped"
        )

    def test_no_change_bumps_nothing(self):
        self._baseline_then_freeze()

        # Re-run with identical inputs — the pure 'never cosmetic' guarantee.
        _update_cluster_statistics(batch_size=500, dry_run=False)

        self.cluster_a.refresh_from_db()
        self.cluster_b.refresh_from_db()
        self.assertEqual(self.cluster_a.updated_at, self.old)
        self.assertEqual(self.cluster_b.updated_at, self.old)


class JobTitleClusterFreshnessTest(TestCase):
    """update_job_title_cluster_stats.main() (Python bulk_update path) bumps only on real change."""

    def setUp(self):
        self.emp_cluster = EmployerCluster.objects.create(
            canonical_name="JT Test Co", slug="jt-test-co"
        )
        self.employer = Employer.objects.create(
            name="JT Test Co",
            name_normalized="jt test co",
            canonical_cluster=self.emp_cluster,
        )
        self.cluster_x = JobTitleCluster.objects.create(
            canonical_title="Engineer X", slug="engineer-x"
        )
        self.jt_x = JobTitle.objects.create(
            title="Engineer X",
            title_normalized="engineer x",
            canonical_cluster=self.cluster_x,
        )
        self.cluster_y = JobTitleCluster.objects.create(
            canonical_title="Analyst Y", slug="analyst-y"
        )
        self.jt_y = JobTitle.objects.create(
            title="Analyst Y",
            title_normalized="analyst y",
            canonical_cluster=self.cluster_y,
        )
        self._add_record("JT-X-1", self.jt_x, "Engineer X", 2023)
        self._add_record("JT-Y-1", self.jt_y, "Analyst Y", 2023)

    def _add_record(self, case_number, job_title_entity, raw_title, fiscal_year):
        SalaryRecord.objects.create(
            case_number=case_number,
            employer=self.employer,
            employer_name="JT Test Co",
            job_title=raw_title,
            job_title_entity=job_title_entity,
            wage_annual=120000,
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=fiscal_year,
            worksite_state="CA",
            is_worksite=False,
        )

    def _run_stats(self):
        # main() parses sys.argv; neutralize pytest's argv so only --dry-run (off) is seen.
        from scripts.salary import update_job_title_cluster_stats as mod

        with mock.patch.object(sys, "argv", ["update_job_title_cluster_stats"]):
            mod.main()

    def test_only_changed_cluster_is_bumped(self):
        self._run_stats()  # baseline
        old = timezone.now() - timedelta(days=400)
        JobTitleCluster.objects.all().update(updated_at=old)

        # A new filing lands for Engineer X only.
        self._add_record("JT-X-2", self.jt_x, "Engineer X", 2024)
        self._run_stats()

        self.cluster_x.refresh_from_db()
        self.cluster_y.refresh_from_db()
        self.assertGreater(
            self.cluster_x.updated_at, old, "cluster with a new filing must be bumped"
        )
        self.assertEqual(
            self.cluster_y.updated_at, old, "untouched cluster must NOT be bumped"
        )

    def test_no_change_bumps_nothing(self):
        self._run_stats()  # baseline
        old = timezone.now() - timedelta(days=400)
        JobTitleCluster.objects.all().update(updated_at=old)

        self._run_stats()  # identical inputs

        self.cluster_x.refresh_from_db()
        self.cluster_y.refresh_from_db()
        self.assertEqual(self.cluster_x.updated_at, old)
        self.assertEqual(self.cluster_y.updated_at, old)

"""Tests for the USCIS Data Hub employer approval-rate aggregation.

Locks: initial vs overall rates computed correctly over a cluster's rows; other
clusters excluded; thin cells (< MIN_INITIAL_DECISIONS) suppressed; FY coverage.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.business.i129.approval_stats import (
    MIN_INITIAL_DECISIONS,
    get_employer_approval_stats,
)
from models.salary import EmployerCluster
from models.uscis_employer import UscisEmployerApproval


def _row(cluster, fy, ia, idn, ca=0, cdn=0):
    return UscisEmployerApproval.objects.create(
        fiscal_year=fy,
        employer_name="X",
        employer_cluster=cluster,
        initial_approval=ia,
        initial_denial=idn,
        continuing_approval=ca,
        continuing_denial=cdn,
    )


class TestApprovalStats(TestCase):
    def test_rates_and_coverage(self):
        c = EmployerCluster.objects.create(canonical_name="Acme", slug="acme")
        # FY2022: 80 approved / 20 denied initial; FY2023: 100 approved / 0 denied.
        _row(c, 2022, ia=80, idn=20, ca=50, cdn=0)
        _row(c, 2023, ia=100, idn=0, ca=150, cdn=0)

        s = get_employer_approval_stats(c)
        assert s is not None
        assert s.initial_approvals == 180
        assert s.initial_denials == 20
        assert s.initial_decisions == 200
        assert s.initial_approval_rate == 90.0  # 180/200
        # overall: (180 + 200) approvals / (200 + 200 continuing) = 380/400
        assert s.overall_approval_rate == 95.0
        assert s.fy_coverage == "FY2022–FY2023"

    def test_scopes_to_cluster(self):
        a = EmployerCluster.objects.create(canonical_name="A", slug="a")
        b = EmployerCluster.objects.create(canonical_name="B", slug="b")
        _row(a, 2023, ia=150, idn=50)
        _row(b, 2023, ia=999, idn=0)  # noise for another cluster
        s = get_employer_approval_stats(a)
        assert s.initial_decisions == 200
        assert s.initial_approval_rate == 75.0

    def test_thin_suppressed(self):
        c = EmployerCluster.objects.create(canonical_name="Tiny", slug="tiny")
        _row(c, 2023, ia=MIN_INITIAL_DECISIONS - 1, idn=0)
        assert get_employer_approval_stats(c) is None

    def test_none_cluster(self):
        assert get_employer_approval_stats(None) is None

    def test_single_year_coverage(self):
        c = EmployerCluster.objects.create(canonical_name="One", slug="one")
        _row(c, 2024, ia=200, idn=0)
        assert get_employer_approval_stats(c).fy_coverage == "FY2024"

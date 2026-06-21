"""Regression tests for transitive-closure cluster merges (split-cluster bug fix).

Before the fix, matching an already-clustered employer reassigned just that one
employer, orphaning its old cluster-mates (A~B then C~B left A and C split). The
BatchedUpdates cluster union-find merges whole clusters instead.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.utils.db_utils import BatchedUpdates
from models.salary import Employer, EmployerCluster


def _cluster(name: str) -> EmployerCluster:
    return EmployerCluster.objects.create(canonical_name=name)


def _emp(name: str, cluster: EmployerCluster) -> Employer:
    return Employer.objects.create(
        name=name,
        name_normalized=Employer.normalize_name(name),
        canonical_cluster=cluster,
    )


class TestClusterMergeResolution(TestCase):
    def test_union_merges_all_members_into_lowest_id_survivor(self):
        a = _cluster("Acme A")  # lowest id -> survivor
        b = _cluster("Acme B")
        ea = _emp("Acme A1", a)
        eb1 = _emp("Acme B1", b)  # b's existing members must come along, not be orphaned
        eb2 = _emp("Acme B2", b)

        bu = BatchedUpdates(dry_run=False)
        bu.union_clusters(a, b)
        merged = bu.resolve_cluster_merges()

        self.assertEqual(merged, 1)
        for e in (ea, eb1, eb2):
            e.refresh_from_db()
            self.assertEqual(e.canonical_cluster_id, a.id)
        self.assertFalse(EmployerCluster.objects.filter(id=b.id).exists())

    def test_transitive_closure_three_clusters(self):
        a, b, c = _cluster("Co A"), _cluster("Co B"), _cluster("Co C")
        ea, eb, ec = _emp("A1", a), _emp("B1", b), _emp("C1", c)

        bu = BatchedUpdates(dry_run=False)
        bu.union_clusters(a, b)  # A~B
        bu.union_clusters(b, c)  # B~C  => A, B, C must all collapse to one
        merged = bu.resolve_cluster_merges()

        self.assertEqual(merged, 2)
        for e in (ea, eb, ec):
            e.refresh_from_db()
            self.assertEqual(e.canonical_cluster_id, a.id)  # survivor = lowest id
        self.assertEqual(EmployerCluster.objects.filter(id__in=[b.id, c.id]).count(), 0)

    def test_union_is_order_independent(self):
        # Unioning in the reverse order still keeps the lowest id as survivor.
        a, b = _cluster("X A"), _cluster("X B")
        ea, eb = _emp("XA1", a), _emp("XB1", b)
        bu = BatchedUpdates(dry_run=False)
        bu.union_clusters(b, a)  # higher-first
        bu.resolve_cluster_merges()
        ea.refresh_from_db()
        eb.refresh_from_db()
        self.assertEqual(ea.canonical_cluster_id, a.id)
        self.assertEqual(eb.canonical_cluster_id, a.id)

    def test_dry_run_does_not_merge(self):
        a, b = _cluster("Dry A"), _cluster("Dry B")
        _emp("DA1", a)
        _emp("DB1", b)
        bu = BatchedUpdates(dry_run=True)
        bu.union_clusters(a, b)
        self.assertEqual(bu.resolve_cluster_merges(), 0)
        self.assertTrue(EmployerCluster.objects.filter(id=b.id).exists())  # untouched

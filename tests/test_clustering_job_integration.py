"""Integration test for the cluster_existing_employers JOB (phased run -> merge resolution).

Complements the unit-level test_cluster_merge (the BatchedUpdates merge primitive):
this drives the full job end-to-end on a fixture that reproduces the split-cluster
corruption (same company pre-assigned to multiple clusters) and asserts the run
collapses them to ONE cluster with no orphaned FKs.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.salary import Employer, EmployerCluster
from scripts.salary.cluster_existing_employers import cluster_existing_employers


def _orphaned_fk_count() -> int:
    """Employers whose canonical_cluster_id points to a now-deleted cluster."""
    return (
        Employer.objects.filter(canonical_cluster_id__isnull=False)
        .exclude(canonical_cluster_id__in=EmployerCluster.objects.values("id"))
        .count()
    )


class TestClusteringJobMergesSplitClusters(TestCase):
    def test_full_job_merges_presplit_same_company_into_one_cluster(self):
        # Same company, three name variants that normalize identically — but
        # pre-assigned to THREE DIFFERENT clusters (the split-cluster corruption
        # the greedy per-pair overwrite used to leave behind).
        ca = EmployerCluster.objects.create(canonical_name="Zorptech Dynamics")
        cb = EmployerCluster.objects.create(canonical_name="Zorptech Dynamics (B)")
        cc = EmployerCluster.objects.create(canonical_name="Zorptech Dynamics (C)")
        # Distinct city/state per row to satisfy the (name_normalized, city, state)
        # unique constraint; the name is non-generic so phase-1 groups them by
        # normalized name regardless of location.
        e1 = Employer.objects.create(
            name="Zorptech Dynamics",
            name_normalized=Employer.normalize_name("Zorptech Dynamics"),
            city="Townsville", state="CA",
            canonical_cluster=ca,
        )
        e2 = Employer.objects.create(
            name="ZORPTECH DYNAMICS",
            name_normalized=Employer.normalize_name("ZORPTECH DYNAMICS"),
            city="Cityburg", state="WA",
            canonical_cluster=cb,
        )
        e3 = Employer.objects.create(
            name="zorptech dynamics",
            name_normalized=Employer.normalize_name("zorptech dynamics"),
            city="Villageton", state="NY",
            canonical_cluster=cc,
        )
        # Precondition: the three variants share a normalized form (phase-1 grouping).
        self.assertEqual(e1.name_normalized, e2.name_normalized)
        self.assertEqual(e1.name_normalized, e3.name_normalized)

        clusters_before = EmployerCluster.objects.count()
        cluster_existing_employers(dry_run=False)

        for e in (e1, e2, e3):
            e.refresh_from_db()
        # All three collapse into ONE surviving cluster.
        self.assertEqual(e1.canonical_cluster_id, e2.canonical_cluster_id)
        self.assertEqual(e1.canonical_cluster_id, e3.canonical_cluster_id)
        self.assertIsNotNone(e1.canonical_cluster_id)
        # The two loser clusters are gone (merged away), none orphaned.
        self.assertEqual(EmployerCluster.objects.count(), clusters_before - 2)
        self.assertEqual(_orphaned_fk_count(), 0)

    def test_dry_run_leaves_clusters_untouched(self):
        ca = EmployerCluster.objects.create(canonical_name="Quibble Foods")
        cb = EmployerCluster.objects.create(canonical_name="Quibble Foods (B)")
        Employer.objects.create(
            name="Quibble Foods",
            name_normalized=Employer.normalize_name("Quibble Foods"),
            city="Townsville", state="CA",
            canonical_cluster=ca,
        )
        Employer.objects.create(
            name="QUIBBLE FOODS",
            name_normalized=Employer.normalize_name("QUIBBLE FOODS"),
            city="Cityburg", state="WA",
            canonical_cluster=cb,
        )
        before = EmployerCluster.objects.count()
        cluster_existing_employers(dry_run=True)
        self.assertEqual(EmployerCluster.objects.count(), before)  # no merges in dry-run
        self.assertEqual(_orphaned_fk_count(), 0)

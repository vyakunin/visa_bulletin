"""Integration tests for BatchedUpdates case-insensitive cluster lookups"""

import unittest

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from lib.utils.db_utils import BatchedUpdates
from models.salary import Employer, EmployerCluster


class TestBatchedUpdatesCaseInsensitive(TestCase):
    """Test that BatchedUpdates handles case-insensitive cluster lookups"""

    def setUp(self):
        """Set up test data"""
        # Create test employers with case variations
        # Use different cities to avoid unique constraint violation on (name_normalized, city, state)
        self.emp1 = Employer.objects.create(
            name='BBC RETAIL AND INTERNET LLC',
            name_normalized='bbc retail and internet',
            city='Seattle',
            state='WA'
        )
        self.emp2 = Employer.objects.create(
            name='BBC Retail and Internet LLC',
            name_normalized='bbc retail and internet',
            city='Portland',
            state='OR'
        )
        self.emp3 = Employer.objects.create(
            name='bbc retail and internet llc',
            name_normalized='bbc retail and internet',
            city='San Francisco',
            state='CA'
        )

    def test_get_or_queue_cluster_case_insensitive_new(self):
        """Test that get_or_queue_cluster returns same cluster for case variations (new clusters)"""
        batched = BatchedUpdates(batch_size=1000, dry_run=False)

        # Get clusters for case variations
        cluster1 = batched.get_or_queue_cluster('BBC RETAIL AND INTERNET LLC')
        cluster2 = batched.get_or_queue_cluster('BBC Retail and Internet LLC')
        cluster3 = batched.get_or_queue_cluster('bbc retail and internet llc')

        # All should return the same cluster instance
        self.assertIs(cluster1, cluster2)
        self.assertIs(cluster2, cluster3)

        # First case wins for canonical_name (preserves original casing)
        self.assertEqual(cluster1.canonical_name, 'BBC RETAIL AND INTERNET LLC')

    def test_get_or_queue_cluster_case_insensitive_existing(self):
        """Test that get_or_queue_cluster finds existing cluster regardless of case"""
        # Create a unique cluster name to avoid conflicts with production data
        unique_name = f'TEST_COMPANY_UNIQUE_{id(self)}'

        # Create an existing cluster with one case
        existing_cluster = EmployerCluster.objects.create(
            canonical_name=unique_name
        )

        # Create new BatchedUpdates (will load existing clusters)
        batched = BatchedUpdates(batch_size=1000, dry_run=False)

        # Try to get clusters with different casing
        cluster1 = batched.get_or_queue_cluster(unique_name)
        cluster2 = batched.get_or_queue_cluster(unique_name.lower())
        cluster3 = batched.get_or_queue_cluster(unique_name.title())

        # All should return the existing cluster
        self.assertEqual(cluster1.id, existing_cluster.id)
        self.assertEqual(cluster2.id, existing_cluster.id)
        self.assertEqual(cluster3.id, existing_cluster.id)

        # Canonical name should match existing cluster
        self.assertEqual(cluster1.canonical_name, unique_name)

    def test_prevents_duplicate_clusters_different_case(self):
        """Test that BatchedUpdates prevents creating duplicate clusters with different casing"""
        batched = BatchedUpdates(batch_size=1000, dry_run=False)

        # Assign employers to clusters with case variations
        self.emp1.canonical_cluster = batched.get_or_queue_cluster('BBC RETAIL AND INTERNET LLC')
        batched.add_employer_update(self.emp1)

        self.emp2.canonical_cluster = batched.get_or_queue_cluster('BBC Retail and Internet LLC')
        batched.add_employer_update(self.emp2)

        self.emp3.canonical_cluster = batched.get_or_queue_cluster('bbc retail and internet llc')
        batched.add_employer_update(self.emp3)

        # Flush all updates
        batched.flush_all(employer_fields=['canonical_cluster'])

        # Reload employers
        self.emp1.refresh_from_db()
        self.emp2.refresh_from_db()
        self.emp3.refresh_from_db()

        # All should be in the same cluster
        self.assertIsNotNone(self.emp1.canonical_cluster)
        self.assertEqual(self.emp1.canonical_cluster_id, self.emp2.canonical_cluster_id)
        self.assertEqual(self.emp2.canonical_cluster_id, self.emp3.canonical_cluster_id)

        # Only one cluster should have been created
        cluster_count = EmployerCluster.objects.filter(
            canonical_name__iexact='BBC RETAIL AND INTERNET LLC'
        ).count()
        self.assertEqual(cluster_count, 1)


if __name__ == '__main__':
    unittest.main()


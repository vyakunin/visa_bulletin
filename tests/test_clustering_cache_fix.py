"""
Test for employer clustering cache consistency bug fix (2026-01-21).

Bug: BatchedUpdates.flush_clusters() used original canonical_name as cache key
but get_or_queue_cluster() used normalized key, causing cache misses for
different casing variations and returning unsaved cluster instances.

Fix: Use normalized keys consistently in both lookups and cache updates.
"""

import os
import django
from django.conf import settings

# Setup Django before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
if not settings.configured:
    django.setup()

import unittest
from django.test import TestCase
from models.salary import Employer, EmployerCluster
from lib.utils.db_utils import BatchedUpdates


class TestClusteringCacheBugFix(TestCase):
    """
    Test that clustering cache bug is fixed.
    
    Before fix: get_or_queue_cluster("BBC RETAIL") would return unsaved cluster
    instance when looked up with different casing after flush_clusters().
    
    After fix: Cache uses normalized keys consistently, returns saved cluster.
    """
    
    def test_cache_returns_saved_cluster_after_flush(self):
        """
        Regression test for clustering cache bug.
        
        Reproduces the bug:
        1. Queue cluster with one casing ("BBC RETAIL")
        2. Flush clusters (saves to DB)
        3. Lookup with different casing ("bbc retail")
        4. Should return SAVED cluster (with pk), not unsaved instance
        
        Before fix: Step 4 returned unsaved cluster (pk=None)
        After fix: Step 4 returns saved cluster (pk is not None)
        """
        batched = BatchedUpdates(batch_size=1000, dry_run=False)
        
        # Step 1: Queue cluster with uppercase
        cluster1 = batched.get_or_queue_cluster("BBC RETAIL")
        self.assertIsNotNone(cluster1)
        
        # Step 2: Flush to save cluster to database
        batched.flush_clusters()
        
        # Step 3: Lookup with lowercase (different casing)
        cluster2 = batched.get_or_queue_cluster("bbc retail")
        
        # Step 4: Verify it's the SAME SAVED cluster (has pk)
        self.assertIsNotNone(cluster2.pk, 
            "BUG: Cache returned unsaved cluster instance. "
            "This indicates cache is using non-normalized keys.")
        self.assertEqual(cluster1.pk, cluster2.pk,
            "BUG: Different cluster instances returned for same normalized name")
    
    def test_bulk_update_with_queued_clusters_different_casing(self):
        """
        Integration test: bulk_update should work with clusters queued via different casings.
        
        This is the real-world scenario that triggered the bug:
        - Multiple employers assigned to clusters with different casing variations
        - bulk_update failed with "unsaved related object" error
        
        After fix: bulk_update should succeed because all clusters are saved.
        """
        # Create test employers
        emp1 = Employer.objects.create(
            name='BBC RETAIL LLC',
            name_normalized='bbc retail',
            city='Seattle',
            state='WA'
        )
        emp2 = Employer.objects.create(
            name='BBC Retail LLC',
            name_normalized='bbc retail',
            city='Portland', 
            state='OR'
        )
        emp3 = Employer.objects.create(
            name='bbc retail llc',
            name_normalized='bbc retail',
            city='San Francisco',
            state='CA'
        )
        
        batched = BatchedUpdates(batch_size=1000, dry_run=False)
        
        # Assign employers to clusters with different casings
        emp1.canonical_cluster = batched.get_or_queue_cluster('BBC RETAIL LLC')
        batched.add_employer_update(emp1)
        
        emp2.canonical_cluster = batched.get_or_queue_cluster('BBC Retail LLC')
        batched.add_employer_update(emp2)
        
        emp3.canonical_cluster = batched.get_or_queue_cluster('bbc retail llc')
        batched.add_employer_update(emp3)
        
        # This should NOT raise "unsaved related object" error
        # Before fix: Would fail with ValueError
        # After fix: Should succeed
        try:
            batched.flush_all(employer_fields=['canonical_cluster'])
        except ValueError as e:
            if "unsaved related object" in str(e):
                self.fail(
                    f"BUG REPRODUCED: bulk_update failed with unsaved cluster error. "
                    f"Cache is returning unsaved cluster instances. Error: {e}"
                )
            else:
                raise
        
        # Verify all employers assigned to same cluster
        emp1.refresh_from_db()
        emp2.refresh_from_db()
        emp3.refresh_from_db()
        
        self.assertIsNotNone(emp1.canonical_cluster_id)
        self.assertEqual(emp1.canonical_cluster_id, emp2.canonical_cluster_id)
        self.assertEqual(emp2.canonical_cluster_id, emp3.canonical_cluster_id)
    
    def test_cache_consistency_across_multiple_flushes(self):
        """
        Test cache remains consistent across multiple flush cycles.
        
        This ensures the fix doesn't break when clusters are created
        in multiple batches (realistic production scenario).
        """
        batched = BatchedUpdates(batch_size=1000, dry_run=False)
        
        # First batch: uppercase
        cluster1 = batched.get_or_queue_cluster("COMPANY A")
        batched.flush_clusters()
        
        # Second batch: lowercase (should find existing)
        cluster2 = batched.get_or_queue_cluster("company a")
        self.assertIsNotNone(cluster2.pk, "Should find existing cluster")
        self.assertEqual(cluster1.pk, cluster2.pk, "Should be same cluster")
        
        # Third batch: title case (should find existing)
        cluster3 = batched.get_or_queue_cluster("Company A")
        self.assertIsNotNone(cluster3.pk, "Should find existing cluster")
        self.assertEqual(cluster1.pk, cluster3.pk, "Should be same cluster")
        
        # Only one cluster should exist
        cluster_count = EmployerCluster.objects.filter(
            canonical_name__iexact="COMPANY A"
        ).count()
        self.assertEqual(cluster_count, 1, 
            "Should have created only one cluster despite different casings")


if __name__ == '__main__':
    unittest.main()

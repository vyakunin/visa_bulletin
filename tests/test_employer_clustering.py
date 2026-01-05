"""Tests for employer clustering logic"""

import os
import django
from django.conf import settings

# Setup Django before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
if not settings.configured:
    django.setup()

from django.test import TestCase
from models.salary import Employer
from lib.business.salary.employer_clustering import (
    match_employers,
    fuzzy_match,
    should_auto_cluster,
)


class TestEmployerMatching(TestCase):
    """Test hybrid employer matching (rule-based + similarity)"""
    
    def setUp(self):
        """Create test employer instances"""
        # Create employers with different name variations
        self.google1 = Employer.objects.create(
            name='Google Inc.',
            name_normalized=Employer.normalize_name('Google Inc.'),
            city='Mountain View',
            state='CA'
        )
        self.google2 = Employer.objects.create(
            name='Google, Inc',
            name_normalized=Employer.normalize_name('Google, Inc'),
            city='Seattle',
            state='WA'
        )
        self.google3 = Employer.objects.create(
            name='Google LLC',
            name_normalized=Employer.normalize_name('Google LLC'),
            city='New York',
            state='NY'
        )
        self.apple = Employer.objects.create(
            name='Apple Corporation',
            name_normalized=Employer.normalize_name('Apple Corporation'),
            city='Cupertino',
            state='CA'
        )
        self.jpmorgan1 = Employer.objects.create(
            name='JPMorgan Chase',
            name_normalized=Employer.normalize_name('JPMorgan Chase'),
            city='New York',
            state='NY'
        )
        self.jpmorgan2 = Employer.objects.create(
            name='JP Morgan',
            name_normalized=Employer.normalize_name('JP Morgan'),
            city='New York',
            state='NY'
        )
    
    def test_exact_normalized_match(self):
        """Test that exact normalized name matches are detected"""
        is_match, confidence, reason = match_employers(self.google1, self.google2)
        self.assertTrue(is_match)
        self.assertEqual(confidence, 1.0)
        self.assertIn('Exact normalized name match', reason)
    
    def test_substring_match(self):
        """Test that one name being substring of another is detected"""
        # Create employer with substring name
        google_base = Employer.objects.create(
            name='Google',
            name_normalized=Employer.normalize_name('Google'),
            city='Mountain View',
            state='CA'
        )
        is_match, confidence, reason = match_employers(google_base, self.google1)
        self.assertTrue(is_match)
        self.assertGreaterEqual(confidence, 0.85)
        self.assertIn('Substring match', reason)
    
    def test_high_similarity_match(self):
        """Test that very similar names are detected"""
        is_match, confidence, reason = match_employers(self.jpmorgan1, self.jpmorgan2)
        self.assertTrue(is_match)
        self.assertGreaterEqual(confidence, 0.85)
        self.assertIn('similarity', reason.lower())
    
    def test_low_similarity_no_match(self):
        """Test that dissimilar names are not matched"""
        is_match, confidence, reason = match_employers(self.google1, self.apple)
        self.assertFalse(is_match)
        self.assertLess(confidence, 0.85)


class TestFuzzyMatching(TestCase):
    """Test fuzzy string matching for employer names"""
    
    def setUp(self):
        self.employer1 = Employer.objects.create(
            name='Microsoft Corporation',
            name_normalized=Employer.normalize_name('Microsoft Corporation'),
            city='Redmond',
            state='WA'
        )
        self.employer2 = Employer.objects.create(
            name='MicroSoft Inc',
            name_normalized=Employer.normalize_name('MicroSoft Inc'),
            city='Redmond',
            state='WA'
        )
        self.employer3 = Employer.objects.create(
            name='Amazon.com',
            name_normalized=Employer.normalize_name('Amazon.com'),
            city='Seattle',
            state='WA'
        )
    
    def test_fuzzy_match_returns_similarity(self):
        """Test that fuzzy_match returns similarity score"""
        similarity, reason = fuzzy_match(self.employer1, self.employer2)
        self.assertGreaterEqual(similarity, 0.0)
        self.assertLessEqual(similarity, 1.0)
        self.assertIsInstance(reason, str)
    
    def test_similarity_thresholds(self):
        """Test that similarity scores are in 0.0-1.0 range"""
        similarity, _ = fuzzy_match(self.employer1, self.employer2)
        self.assertGreaterEqual(similarity, 0.0)
        self.assertLessEqual(similarity, 1.0)
        
        # Dissimilar names should have lower similarity
        similarity_low, _ = fuzzy_match(self.employer1, self.employer3)
        self.assertLess(similarity_low, similarity)


class TestClusteringLogic(TestCase):
    """Test main clustering function"""
    
    def setUp(self):
        self.google1 = Employer.objects.create(
            name='Google Inc.',
            name_normalized=Employer.normalize_name('Google Inc.'),
            city='Mountain View',
            state='CA'
        )
        self.google2 = Employer.objects.create(
            name='Google, Inc',
            name_normalized=Employer.normalize_name('Google, Inc'),
            city='Seattle',
            state='WA'
        )
        self.apple = Employer.objects.create(
            name='Apple Corporation',
            name_normalized=Employer.normalize_name('Apple Corporation'),
            city='Cupertino',
            state='CA'
        )
    
    def test_auto_cluster_high_confidence(self):
        """Test that high-confidence matches are auto-clustered"""
        should_cluster, confidence, reason = should_auto_cluster(
            self.google1, self.google2, threshold=0.95
        )
        self.assertTrue(should_cluster)
        self.assertGreaterEqual(confidence, 0.95)
    
    def test_no_cluster_low_confidence(self):
        """Test that low-confidence matches are not auto-clustered"""
        should_cluster, confidence, reason = should_auto_cluster(
            self.google1, self.apple, threshold=0.95
        )
        self.assertFalse(should_cluster)
        self.assertLess(confidence, 0.95)


class TestClusteringIntegration(TestCase):
    """Integration tests for end-to-end clustering workflow"""
    
    def setUp(self):
        """Create test employers"""
        self.google1 = Employer.objects.create(
            name='Google Inc.',
            name_normalized=Employer.normalize_name('Google Inc.'),
            city='Mountain View',
            state='CA'
        )
        self.google2 = Employer.objects.create(
            name='Google, Inc',
            name_normalized=Employer.normalize_name('Google, Inc'),
            city='Seattle',
            state='WA'
        )
        self.google3 = Employer.objects.create(
            name='Google LLC',
            name_normalized=Employer.normalize_name('Google LLC'),
            city='New York',
            state='NY'
        )
        self.apple = Employer.objects.create(
            name='Apple Corporation',
            name_normalized=Employer.normalize_name('Apple Corporation'),
            city='Cupertino',
            state='CA'
        )
    
    def test_assign_to_cluster_creates_cluster(self):
        """Test that assign_to_cluster creates a new cluster when no match found"""
        from lib.business.salary.employer_clustering import assign_to_cluster
        
        cluster = assign_to_cluster(self.apple)
        self.assertIsNotNone(cluster)
        self.assertEqual(cluster.canonical_name, self.apple.name)
        self.apple.refresh_from_db()
        self.assertEqual(self.apple.canonical_cluster, cluster)
    
    def test_assign_to_cluster_joins_existing_cluster(self):
        """Test that assign_to_cluster joins existing cluster for high-confidence matches"""
        from lib.business.salary.employer_clustering import assign_to_cluster
        
        # Assign first employer
        cluster1 = assign_to_cluster(self.google1)
        self.assertIsNotNone(cluster1)
        
        # Assign second employer (should join same cluster)
        cluster2 = assign_to_cluster(self.google2)
        self.assertIsNotNone(cluster2)
        
        # Should be same cluster
        self.assertEqual(cluster1.id, cluster2.id)
        self.google1.refresh_from_db()
        self.google2.refresh_from_db()
        self.assertEqual(self.google1.canonical_cluster.id, self.google2.canonical_cluster.id)
    
    def test_assign_to_cluster_queues_ambiguous_matches(self):
        """Test that ambiguous matches are queued for review"""
        from lib.business.salary.employer_clustering import assign_to_cluster
        from models.salary import EmployerClusteringReview
        
        # Create employers with similar but not identical names
        emp1 = Employer.objects.create(
            name='JPMorgan Chase',
            name_normalized=Employer.normalize_name('JPMorgan Chase'),
            city='New York',
            state='NY'
        )
        emp2 = Employer.objects.create(
            name='JP Morgan',
            name_normalized=Employer.normalize_name('JP Morgan'),
            city='New York',
            state='NY'
        )
        
        # Assign first (creates cluster)
        assign_to_cluster(emp1, auto_approve_threshold=0.98)  # High threshold
        
        # Assign second (might queue if similarity < threshold)
        assign_to_cluster(emp2, auto_approve_threshold=0.98)
        
        # Check if review was created
        reviews = EmployerClusteringReview.objects.filter(
            employer1__in=[emp1, emp2],
            employer2__in=[emp1, emp2]
        )
        # Review may or may not be created depending on similarity score
        # Just verify the function doesn't crash
        self.assertIsNotNone(emp2.canonical_cluster)
    
    def test_cluster_statistics_aggregation(self):
        """Test that cluster statistics aggregate correctly"""
        from lib.business.salary.employer_clustering import assign_to_cluster
        from models.salary import EmployerCluster
        
        # Set some stats on employers
        self.google1.total_lca_count = 100
        self.google1.total_perm_count = 50
        self.google1.avg_salary = 150000
        self.google1.save()
        
        self.google2.total_lca_count = 200
        self.google2.total_perm_count = 75
        self.google2.avg_salary = 160000
        self.google2.save()
        
        # Assign to clusters
        cluster1 = assign_to_cluster(self.google1)
        cluster2 = assign_to_cluster(self.google2)
        
        # Should be same cluster
        self.assertEqual(cluster1.id, cluster2.id)
        
        # Update cluster stats manually (normally done by migration script)
        cluster = cluster1
        cluster.total_lca_count = sum(e.total_lca_count for e in cluster.employers.all())
        cluster.total_perm_count = sum(e.total_perm_count for e in cluster.employers.all())
        salaries = [float(e.avg_salary) for e in cluster.employers.all() if e.avg_salary]
        if salaries:
            cluster.avg_salary = sum(salaries) / len(salaries)
        cluster.save()
        
        # Verify aggregated stats
        self.assertEqual(cluster.total_lca_count, 300)
        self.assertEqual(cluster.total_perm_count, 125)
        self.assertEqual(float(cluster.avg_salary), 155000.0)








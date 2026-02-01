"""
Tests for clustering metrics calculation.

Tests that precision, recall, and F1 metrics are calculated correctly.
"""

from tests.django_setup import setup_django_for_tests
setup_django_for_tests()

import unittest
from lib.business.salary.clustering_evaluator import (
    ClusteringEvaluator,
    EvaluationOutcome,
    EmployerPair,
    PairEvaluationStats,
)


class TestClusteringMetrics(unittest.TestCase):
    """Test clustering metrics calculation."""
    
    def test_precision_calculation(self):
        """Test precision calculation: TP / (TP + FP)"""
        # Mock validator: 2 TP, 1 FP
        outcomes = iter([
            EvaluationOutcome.same("YES"),   # TP 1
            EvaluationOutcome.same("YES"),   # TP 2
            EvaluationOutcome.different("NO"),  # FP 1
        ])
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return next(outcomes)
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {'emp1_name': 'A', 'emp1_city': 'NY', 'emp1_state': 'NY',
             'emp2_name': 'A Inc', 'emp2_city': 'NY', 'emp2_state': 'NY', 'similarity': 0.95},
            {'emp1_name': 'B', 'emp1_city': 'CA', 'emp1_state': 'CA',
             'emp2_name': 'B Corp', 'emp2_city': 'CA', 'emp2_state': 'CA', 'similarity': 0.93},
            {'emp1_name': 'C', 'emp1_city': 'TX', 'emp1_state': 'TX',
             'emp2_name': 'D', 'emp2_city': 'TX', 'emp2_state': 'TX', 'similarity': 0.91},
        ]
        queue_sample = []
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        
        # Precision = TP / (TP + FP) = 2 / (2 + 1) = 0.667
        self.assertEqual(metrics['auto_clustered']['true_positives'], 2)
        self.assertEqual(metrics['auto_clustered']['false_positives'], 1)
        self.assertAlmostEqual(metrics['auto_clustered']['precision'], 2/3, places=3)
        self.assertAlmostEqual(metrics['overall']['precision'], 2/3, places=3)
    
    def test_recall_calculation(self):
        """Test recall calculation: TP / (TP + FN)"""
        # Mock validator: 1 TP (auto), 1 FN (queued)
        outcomes = iter([
            EvaluationOutcome.same("YES"),   # Auto-clustered: TP
            EvaluationOutcome.same("YES"),  # Queued: FN (should have been clustered)
        ])
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return next(outcomes)
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {'emp1_name': 'A', 'emp1_city': 'NY', 'emp1_state': 'NY',
             'emp2_name': 'A Inc', 'emp2_city': 'NY', 'emp2_state': 'NY', 'similarity': 0.95},
        ]
        queue_sample = [
            {'emp1_name': 'B', 'emp1_city': 'CA', 'emp1_state': 'CA',
             'emp2_name': 'B Corp', 'emp2_city': 'CA', 'emp2_state': 'CA', 'similarity': 0.88},
        ]
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        
        # Recall = TP / (TP + FN) = 1 / (1 + 1) = 0.5
        self.assertEqual(metrics['auto_clustered']['true_positives'], 1)
        self.assertEqual(metrics['queued_for_review']['false_negatives'], 1)
        self.assertAlmostEqual(metrics['overall']['recall'], 0.5, places=3)
    
    def test_f1_calculation(self):
        """Test F1 score calculation: 2 * (precision * recall) / (precision + recall)"""
        # Mock validator: 2 TP (auto), 1 FP (auto), 1 FN (queued)
        outcomes = iter([
            EvaluationOutcome.same("YES"),   # TP 1 (auto)
            EvaluationOutcome.same("YES"),   # TP 2 (auto)
            EvaluationOutcome.different("NO"),  # FP 1 (auto)
            EvaluationOutcome.same("YES"),  # FN 1 (queued - should have been clustered)
        ])
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return next(outcomes)
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {'emp1_name': 'A', 'emp1_city': 'NY', 'emp1_state': 'NY',
             'emp2_name': 'A Inc', 'emp2_city': 'NY', 'emp2_state': 'NY', 'similarity': 0.95},
            {'emp1_name': 'B', 'emp1_city': 'CA', 'emp1_state': 'CA',
             'emp2_name': 'B Corp', 'emp2_city': 'CA', 'emp2_state': 'CA', 'similarity': 0.93},
            {'emp1_name': 'C', 'emp1_city': 'TX', 'emp1_state': 'TX',
             'emp2_name': 'D', 'emp2_city': 'TX', 'emp2_state': 'TX', 'similarity': 0.91},
        ]
        queue_sample = [
            {'emp1_name': 'E', 'emp1_city': 'FL', 'emp1_state': 'FL',
             'emp2_name': 'E LLC', 'emp2_city': 'FL', 'emp2_state': 'FL', 'similarity': 0.88},
        ]
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        
        # Overall precision = (TP_auto + TP_queue) / (TP_auto + TP_queue + FP_auto + FP_queue)
        # But TP_queue is actually FN (false negatives), and FP_queue is actually TN (true negatives)
        # So: total_tp = 2 + 1 = 3, total_fp = 1 + 0 = 1
        # Precision = 3 / (3 + 1) = 0.75
        # Recall = TP_auto / (TP_auto + FN_queue) = 2 / (2 + 1) = 0.667
        # F1 = 2 * (0.75 * 0.667) / (0.75 + 0.667) = 0.706
        self.assertAlmostEqual(metrics['overall']['precision'], 0.75, places=3)
        self.assertAlmostEqual(metrics['overall']['recall'], 2/3, places=3)
        self.assertAlmostEqual(metrics['overall']['f1_score'], 0.706, places=3)
    
    def test_precision_with_zero_false_positives(self):
        """Test precision when there are no false positives (perfect precision)."""
        # Mock validator: all TP, no FP
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return EvaluationOutcome.same("YES")
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {'emp1_name': 'A', 'emp1_city': 'NY', 'emp1_state': 'NY',
             'emp2_name': 'A Inc', 'emp2_city': 'NY', 'emp2_state': 'NY', 'similarity': 0.95},
            {'emp1_name': 'B', 'emp1_city': 'CA', 'emp1_state': 'CA',
             'emp2_name': 'B Corp', 'emp2_city': 'CA', 'emp2_state': 'CA', 'similarity': 0.93},
        ]
        queue_sample = []
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        
        # Precision = 2 / (2 + 0) = 1.0
        self.assertEqual(metrics['auto_clustered']['true_positives'], 2)
        self.assertEqual(metrics['auto_clustered']['false_positives'], 0)
        self.assertEqual(metrics['overall']['precision'], 1.0)
    
    def test_recall_with_zero_false_negatives(self):
        """Test recall when there are no false negatives (perfect recall)."""
        # Mock validator: all TP (auto), all TN (queued)
        outcomes = iter([
            EvaluationOutcome.same("YES"),   # Auto: TP
            EvaluationOutcome.different("NO"),  # Queued: TN (correctly not clustered)
        ])
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return next(outcomes)
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {'emp1_name': 'A', 'emp1_city': 'NY', 'emp1_state': 'NY',
             'emp2_name': 'A Inc', 'emp2_city': 'NY', 'emp2_state': 'NY', 'similarity': 0.95},
        ]
        queue_sample = [
            {'emp1_name': 'B', 'emp1_city': 'CA', 'emp1_state': 'CA',
             'emp2_name': 'C', 'emp2_city': 'CA', 'emp2_state': 'CA', 'similarity': 0.60},
        ]
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        
        # Recall = 1 / (1 + 0) = 1.0
        self.assertEqual(metrics['auto_clustered']['true_positives'], 1)
        self.assertEqual(metrics['queued_for_review']['false_negatives'], 0)
        self.assertEqual(metrics['overall']['recall'], 1.0)
    
    def test_metrics_with_known_false_positive_example(self):
        """Test metrics calculation with a known false positive case."""
        # Mock validator: returns different (false positive)
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return EvaluationOutcome.different("NO - Different companies")
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        # Example: Two different companies that might be incorrectly matched
        auto_sample = [
            {'emp1_name': 'GRAHAM CAPITAL MANAGEMENT', 'emp1_city': 'NY', 'emp1_state': 'NY',
             'emp2_name': 'GRAHAM HOLDINGS COMPANY', 'emp2_city': 'NY', 'emp2_state': 'NY', 'similarity': 0.92},
        ]
        queue_sample = []
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        false_positives = results.false_positives
        
        # Should be identified as false positive
        self.assertEqual(metrics['auto_clustered']['true_positives'], 0)
        self.assertEqual(metrics['auto_clustered']['false_positives'], 1)
        self.assertEqual(len(false_positives), 1)
        self.assertEqual(false_positives[0]['emp1_name'], 'GRAHAM CAPITAL MANAGEMENT')
    
    def test_metrics_with_known_false_negative_example(self):
        """Test metrics calculation with a known false negative case."""
        # Mock validator: returns same (false negative - should have been clustered)
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return EvaluationOutcome.same("YES - Same company")
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        # Example: Same company that was queued instead of auto-clustered
        auto_sample = []
        queue_sample = [
            {'emp1_name': 'Echo IT Solutions Inc', 'emp1_city': 'CA', 'emp1_state': 'CA',
             'emp2_name': 'ECHO IT SOLUTION INC', 'emp2_city': 'CA', 'emp2_state': 'CA', 'similarity': 0.88},
        ]
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        false_negatives = results.false_negatives
        
        # Should be identified as false negative
        self.assertEqual(metrics['auto_clustered']['true_positives'], 0)
        self.assertEqual(metrics['queued_for_review']['false_negatives'], 1)
        self.assertEqual(len(false_negatives), 1)
        self.assertEqual(false_negatives[0]['emp1_name'], 'Echo IT Solutions Inc')


if __name__ == '__main__':
    unittest.main()


"""
Tests for clustering evaluator.

Tests the ClusteringEvaluator class that evaluates clustering pairs using LLM validation.
"""

from tests.django_setup import setup_django_for_tests
setup_django_for_tests()

from unittest.mock import Mock, patch
from lib.business.salary.clustering_evaluator import (
    ClusteringEvaluator, 
    EvaluationOutcome,
    EmployerPair,
    EvaluationResults
)


class TestClusteringEvaluator:
    """Test ClusteringEvaluator class."""
    
    def test_evaluate_samples_all_true_positives(self):
        """Test evaluation when all auto-clustered pairs are true positives."""
        # Mock LLM validator that always returns True
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return EvaluationOutcome.same("YES - Same company")
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {
                'emp1_name': 'Google Inc',
                'emp1_city': 'Mountain View',
                'emp1_state': 'CA',
                'emp2_name': 'Google LLC',
                'emp2_city': 'Mountain View',
                'emp2_state': 'CA',
                'similarity': 0.95,
            }
        ]
        queue_sample = [
            {
                'emp1_name': 'Apple Inc',
                'emp1_city': 'Cupertino',
                'emp1_state': 'CA',
                'emp2_name': 'Microsoft Corp',
                'emp2_city': 'Redmond',
                'emp2_state': 'WA',
                'similarity': 0.60,
            }
        ]
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        false_positives = results.false_positives
        false_negatives = results.false_negatives
        
        assert metrics['auto_clustered']['true_positives'] == 1
        assert metrics['auto_clustered']['false_positives'] == 0
        assert metrics['auto_clustered']['skipped'] == 0
        assert metrics['queued_for_review']['true_negatives'] == 1
        assert metrics['queued_for_review']['false_negatives'] == 0
        assert metrics['overall']['precision'] == 1.0
        assert len(false_positives) == 0
        assert len(false_negatives) == 0
    
    def test_evaluate_samples_false_positive(self):
        """Test evaluation when auto-clustered pair is false positive."""
        # Mock LLM validator: first call returns False (false positive)
        outcomes = iter([
            EvaluationOutcome.different("NO - Different companies"),  # Auto-clustered pair
            EvaluationOutcome.different("NO - Different companies"),  # Queued pair
        ])
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return next(outcomes)
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {
                'emp1_name': 'ABC Corp',
                'emp1_city': 'New York',
                'emp1_state': 'NY',
                'emp2_name': 'XYZ Corp',
                'emp2_city': 'Boston',
                'emp2_state': 'MA',
                'similarity': 0.92,
            }
        ]
        queue_sample = []
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        false_positives = results.false_positives
        false_negatives = results.false_negatives
        
        assert metrics['auto_clustered']['true_positives'] == 0
        assert metrics['auto_clustered']['false_positives'] == 1
        assert len(false_positives) == 1
        assert false_positives[0]['emp1_name'] == 'ABC Corp'
        assert false_positives[0]['reason'] == 'False positive - should not be clustered'
    
    def test_evaluate_samples_false_negative(self):
        """Test evaluation when queued pair is false negative."""
        # Mock LLM validator: queued pair returns True (false negative)
        outcomes = iter([
            EvaluationOutcome.same("YES - Same company"),  # Auto-clustered pair
            EvaluationOutcome.same("YES - Same company"),  # Queued pair (false negative)
        ])
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return next(outcomes)
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {
                'emp1_name': 'Google Inc',
                'emp1_city': 'Mountain View',
                'emp1_state': 'CA',
                'emp2_name': 'Google LLC',
                'emp2_city': 'Mountain View',
                'emp2_state': 'CA',
                'similarity': 0.95,
            }
        ]
        queue_sample = [
            {
                'emp1_name': 'Apple Inc',
                'emp1_city': 'Cupertino',
                'emp1_state': 'CA',
                'emp2_name': 'Apple Computer',
                'emp2_city': 'Cupertino',
                'emp2_state': 'CA',
                'similarity': 0.88,
            }
        ]
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        false_positives = results.false_positives
        false_negatives = results.false_negatives
        
        assert metrics['auto_clustered']['true_positives'] == 1
        assert metrics['queued_for_review']['false_negatives'] == 1
        assert metrics['queued_for_review']['true_negatives'] == 0
        assert len(false_negatives) == 1
        assert false_negatives[0]['emp1_name'] == 'Apple Inc'
        assert false_negatives[0]['reason'] == 'False negative - should be clustered'
    
    def test_evaluate_samples_skipped(self):
        """Test evaluation when LLM validation fails (returns None)."""
        # Mock LLM validator that returns None (validation failed)
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            return EvaluationOutcome.failed()
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        auto_sample = [
            {
                'emp1_name': 'Test Corp',
                'emp1_city': 'Test City',
                'emp1_state': 'CA',
                'emp2_name': 'Test Inc',
                'emp2_city': 'Test City',
                'emp2_state': 'CA',
                'similarity': 0.90,
            }
        ]
        queue_sample = []
        
        results = evaluator.evaluate_samples(auto_sample, queue_sample)
        metrics = results.metrics
        false_positives = results.false_positives
        false_negatives = results.false_negatives
        
        assert metrics['auto_clustered']['skipped'] == 1
        assert metrics['auto_clustered']['true_positives'] == 0
        assert metrics['auto_clustered']['false_positives'] == 0
        assert len(false_positives) == 0
    
    def test_evaluate_samples_precision_calculation(self):
        """Test precision calculation with mixed results."""
        # Mock LLM validator: 2 TP, 1 FP
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
        false_positives = results.false_positives
        false_negatives = results.false_negatives
        
        # Precision = TP / (TP + FP) = 2 / (2 + 1) = 0.667
        assert metrics['auto_clustered']['true_positives'] == 2
        assert metrics['auto_clustered']['false_positives'] == 1
        assert abs(metrics['auto_clustered']['precision'] - 2/3) < 0.001
        assert abs(metrics['overall']['precision'] - 2/3) < 0.001
    
    def test_evaluate_samples_recall_calculation(self):
        """Test recall calculation with false negatives."""
        # Mock LLM validator: 1 TP (auto), 1 FN (queued)
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
        false_positives = results.false_positives
        false_negatives = results.false_negatives
        
        # Recall = TP / (TP + FN) = 1 / (1 + 1) = 0.5
        assert metrics['auto_clustered']['true_positives'] == 1
        assert metrics['queued_for_review']['false_negatives'] == 1
        assert abs(metrics['overall']['recall'] - 0.5) < 0.001
    
    def test_evaluate_samples_empty_samples(self):
        """Test evaluation with empty samples."""
        call_count = [0]  # Use list to allow modification in nested function
        def mock_validator(pair: EmployerPair) -> EvaluationOutcome:
            call_count[0] += 1
            return EvaluationOutcome.same("YES")
        
        evaluator = ClusteringEvaluator(mock_validator)
        
        metrics, false_positives, false_negatives = evaluator.evaluate_samples([], [])
        
        assert metrics['auto_clustered']['true_positives'] == 0
        assert metrics['auto_clustered']['false_positives'] == 0
        assert metrics['queued_for_review']['false_negatives'] == 0
        assert metrics['overall']['precision'] == 0.0
        assert len(false_positives) == 0
        assert len(false_negatives) == 0
        # Validator should not be called
        assert call_count[0] == 0

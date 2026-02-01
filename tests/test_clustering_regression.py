"""
Regression tests for employer clustering.

Prevents regressions in known good cases from clustering_examples.jsonl.
Tests that true positives remain matched and true negatives remain unmatched.
"""

from tests.django_setup import setup_django_for_tests
setup_django_for_tests()

import json
import unittest
from pathlib import Path
from models.salary import Employer
from lib.business.salary.employer_clustering import match_employers, should_auto_cluster


class TestClusteringRegression(unittest.TestCase):
    """Regression tests to prevent breaking known good cases."""
    
    @classmethod
    def setUpClass(cls):
        """Load examples from clustering_examples.jsonl."""
        # Try multiple paths to find the file (works in both Bazel and local execution)
        possible_paths = [
            Path(__file__).parent.parent / "data" / "clustering_examples.jsonl",  # Local execution
            Path("data/clustering_examples.jsonl"),  # Bazel runfiles (workspace root)
        ]
        
        examples_file = None
        for path in possible_paths:
            if path.exists():
                examples_file = path
                break
        
        cls.examples = []
        
        if examples_file and examples_file.exists():
            with open(examples_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        example = json.loads(line)
                        # Only use reviewed examples for regression tests
                        if example.get('type') == 'reviewed':
                            cls.examples.append(example)
                    except json.JSONDecodeError:
                        continue
        
        # Separate examples by ground truth
        cls.true_positives = [ex for ex in cls.examples if ex.get('ground_truth') == 'same']
        cls.true_negatives = [ex for ex in cls.examples if ex.get('ground_truth') == 'different']
    
    def test_known_true_positives_remain_matched(self):
        """Test that known true positive pairs remain matched."""
        # Test a sample of true positives (first 20 to keep test fast)
        test_cases = self.true_positives[:20]
        
        for example in test_cases:
            with self.subTest(emp1=example['emp1_name'], emp2=example['emp2_name']):
                emp1 = Employer(
                    name=example['emp1_name'],
                    name_normalized=Employer.normalize_name(example['emp1_name']),
                    city=example.get('emp1_city', '') or '',
                    state=example.get('emp1_state', '') or ''
                )
                emp2 = Employer(
                    name=example['emp2_name'],
                    name_normalized=Employer.normalize_name(example['emp2_name']),
                    city=example.get('emp2_city', '') or '',
                    state=example.get('emp2_state', '') or ''
                )
                
                is_match, confidence, reason = match_employers(emp1, emp2)
                
                # Should match (true positive)
                self.assertTrue(
                    is_match,
                    f"Should match: '{example['emp1_name']}' vs '{example['emp2_name']}' "
                    f"(reason: {reason}, confidence: {confidence:.3f})"
                )
    
    def test_known_true_negatives_remain_unmatched(self):
        """Test that known true negative pairs remain unmatched."""
        # Test a sample of true negatives (first 20 to keep test fast)
        test_cases = self.true_negatives[:20]
        
        for example in test_cases:
            with self.subTest(emp1=example['emp1_name'], emp2=example['emp2_name']):
                emp1 = Employer(
                    name=example['emp1_name'],
                    name_normalized=Employer.normalize_name(example['emp1_name']),
                    city=example.get('emp1_city', '') or '',
                    state=example.get('emp1_state', '') or ''
                )
                emp2 = Employer(
                    name=example['emp2_name'],
                    name_normalized=Employer.normalize_name(example['emp2_name']),
                    city=example.get('emp2_city', '') or '',
                    state=example.get('emp2_state', '') or ''
                )
                
                is_match, confidence, reason = match_employers(emp1, emp2)
                
                # Should NOT match (true negative)
                self.assertFalse(
                    is_match,
                    f"Should NOT match: '{example['emp1_name']}' vs '{example['emp2_name']}' "
                    f"(reason: {reason}, confidence: {confidence:.3f})"
                )
    
    def test_precision_critical_cases_remain_unmatched(self):
        """Test known false positive cases that should NOT match (precision-critical)."""
        # Known false positive cases from the codebase
        precision_critical_cases = [
            {
                'emp1_name': 'GRAHAM CAPITAL MANAGEMENT, L.P.',
                'emp1_city': 'New York',
                'emp1_state': 'NY',
                'emp2_name': 'GRAHAM HOLDINGS COMPANY',
                'emp2_city': 'New York',
                'emp2_state': 'NY',
            },
            {
                'emp1_name': 'ASPEN TECHNOLOGY, INC',
                'emp1_city': 'Bedford',
                'emp1_state': 'MA',
                'emp2_name': 'ASPEN CONSULTING, INC.',
                'emp2_city': 'Bedford',
                'emp2_state': 'MA',
            },
            {
                'emp1_name': 'SERVICE MANAGEMENT GROUP, LLC',
                'emp1_city': 'Kansas City',
                'emp1_state': 'MO',
                'emp2_name': 'CORPORATION SERVICE COMPANY',
                'emp2_city': 'Wilmington',
                'emp2_state': 'DE',
            },
            {
                'emp1_name': 'TRINITY TECHNOLOGIES CORPORATION',
                'emp1_city': 'Boston',
                'emp1_state': 'MA',
                'emp2_name': 'TRINITY PARTNERS, LLC',
                'emp2_city': 'Boston',
                'emp2_state': 'MA',
            },
        ]
        
        for case in precision_critical_cases:
            with self.subTest(emp1=case['emp1_name'], emp2=case['emp2_name']):
                emp1 = Employer(
                    name=case['emp1_name'],
                    name_normalized=Employer.normalize_name(case['emp1_name']),
                    city=case.get('emp1_city', '') or '',
                    state=case.get('emp1_state', '') or ''
                )
                emp2 = Employer(
                    name=case['emp2_name'],
                    name_normalized=Employer.normalize_name(case['emp2_name']),
                    city=case.get('emp2_city', '') or '',
                    state=case.get('emp2_state', '') or ''
                )
                
                is_match, confidence, reason = match_employers(emp1, emp2)
                
                # Should NOT match (false positive prevention)
                self.assertFalse(
                    is_match,
                    f"Precision regression: Should NOT match '{case['emp1_name']}' vs '{case['emp2_name']}' "
                    f"(reason: {reason}, confidence: {confidence:.3f})"
                )
    
    def test_recall_critical_cases_remain_matched(self):
        """Test known false negative cases that SHOULD match (recall-critical)."""
        # Known false negative cases (same company, different name variations)
        recall_critical_cases = [
            {
                'emp1_name': 'Echo IT Solutions Inc',
                'emp1_city': 'San Francisco',
                'emp1_state': 'CA',
                'emp2_name': 'ECHO IT SOLUTION INC',
                'emp2_city': 'San Francisco',
                'emp2_state': 'CA',
            },
            {
                'emp1_name': 'GB Gems LLC',
                'emp1_city': 'New York',
                'emp1_state': 'NY',
                'emp2_name': 'G.B. Gems LLC',
                'emp2_city': 'New York',
                'emp2_state': 'NY',
            },
        ]
        
        for case in recall_critical_cases:
            with self.subTest(emp1=case['emp1_name'], emp2=case['emp2_name']):
                emp1 = Employer(
                    name=case['emp1_name'],
                    name_normalized=Employer.normalize_name(case['emp1_name']),
                    city=case.get('emp1_city', '') or '',
                    state=case.get('emp1_state', '') or ''
                )
                emp2 = Employer(
                    name=case['emp2_name'],
                    name_normalized=Employer.normalize_name(case['emp2_name']),
                    city=case.get('emp2_city', '') or '',
                    state=case.get('emp2_state', '') or ''
                )
                
                is_match, confidence, reason = match_employers(emp1, emp2)
                
                # Should match (false negative prevention)
                self.assertTrue(
                    is_match,
                    f"Recall regression: Should match '{case['emp1_name']}' vs '{case['emp2_name']}' "
                    f"(reason: {reason}, confidence: {confidence:.3f})"
                )
    
    def test_auto_cluster_threshold_consistency(self):
        """Test that auto-cluster threshold (0.95) works consistently."""
        # Test that high-confidence matches are auto-clustered
        high_confidence_cases = [
            {
                'emp1_name': 'Google Inc',
                'emp1_city': 'Mountain View',
                'emp1_state': 'CA',
                'emp2_name': 'Google LLC',
                'emp2_city': 'Mountain View',
                'emp2_state': 'CA',
            },
        ]
        
        for case in high_confidence_cases:
            with self.subTest(emp1=case['emp1_name'], emp2=case['emp2_name']):
                emp1 = Employer(
                    name=case['emp1_name'],
                    name_normalized=Employer.normalize_name(case['emp1_name']),
                    city=case.get('emp1_city', '') or '',
                    state=case.get('emp1_state', '') or ''
                )
                emp2 = Employer(
                    name=case['emp2_name'],
                    name_normalized=Employer.normalize_name(case['emp2_name']),
                    city=case.get('emp2_city', '') or '',
                    state=case.get('emp2_state', '') or ''
                )
                
                should_cluster, confidence, reason = should_auto_cluster(emp1, emp2, threshold=0.95)
                
                # Should auto-cluster if confidence >= 0.95
                if confidence >= 0.95:
                    self.assertTrue(
                        should_cluster,
                        f"Should auto-cluster: '{case['emp1_name']}' vs '{case['emp2_name']}' "
                        f"(confidence: {confidence:.3f} >= 0.95, reason: {reason})"
                    )
    
    def test_non_generic_exact_matches_across_states(self):
        """Test that non-generic exact matches work across different states (recall maintenance)."""
        # Non-generic company names should match across states (same company, different locations)
        non_generic_cases = [
            {
                'emp1': Employer(name='EMC CORPORATION', city='HOPKINTON', state='MA'),
                'emp2': Employer(name='EMC CORPORATION', city='ROUND ROCK', state='TEXAS'),
                'should_match': True,
                'reason': 'Non-generic company name should match across states'
            },
            {
                'emp1': Employer(name='ABB INC.', city='NORWALK', state='CT'),
                'emp2': Employer(name='ABB INC.', city='CARY', state='NORTH CAROLINA'),
                'should_match': True,
                'reason': 'Non-generic company name should match across states'
            },
            {
                'emp1': Employer(name='COVIDIEN', city='MANSFIELD', state='MA'),
                'emp2': Employer(name='COVIDIEN', city='FRIDLEY', state='MINNESOTA'),
                'should_match': True,
                'reason': 'Non-generic company name should match across states'
            },
        ]
        
        for case in non_generic_cases:
            with self.subTest(emp1=case['emp1'].name, emp2=case['emp2'].name):
                emp1 = Employer(
                    name=case['emp1'].name,
                    name_normalized=Employer.normalize_name(case['emp1'].name),
                    city=case['emp1'].city,
                    state=case['emp1'].state
                )
                emp2 = Employer(
                    name=case['emp2'].name,
                    name_normalized=Employer.normalize_name(case['emp2'].name),
                    city=case['emp2'].city,
                    state=case['emp2'].state
                )
                
                is_match, confidence, reason = match_employers(emp1, emp2)
                
                self.assertTrue(
                    is_match,
                    f"Recall: Should match non-generic name across states: "
                    f"'{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']}) - "
                    f"reason: {reason}, confidence: {confidence:.3f}"
                )
                
                # Should auto-cluster (high confidence)
                should_cluster, cluster_confidence, cluster_reason = should_auto_cluster(
                    emp1, emp2, threshold=0.95
                )
                self.assertTrue(
                    should_cluster,
                    f"Should auto-cluster non-generic name across states: "
                    f"confidence: {cluster_confidence:.3f} should be >= 0.95"
                )
    
    def test_hyphen_variations_with_same_location_should_match(self):
        """Test that hyphen variations with same location should match (recall maintenance)."""
        # Hyphen variations in same location are likely same company
        hyphen_cases = [
            {
                'emp1': Employer(name='E-KO Image Inc.', city='Chino', state='CA'),
                'emp2': Employer(name='EKO Image Inc.', city='Chino', state='CA'),
                'should_match': True,
                'reason': 'Hyphen variation with same location'
            },
            {
                'emp1': Employer(name='HI-TEK PROFESSIONALS, INC.', city='MEDIA', state='PA'),
                'emp2': Employer(name='HITEK PROFESSIONALS, INC.', city='MEDIA', state='PA'),
                'should_match': True,
                'reason': 'Hyphen variation with exact location match'
            },
        ]
        
        for case in hyphen_cases:
            with self.subTest(emp1=case['emp1'].name, emp2=case['emp2'].name):
                emp1 = Employer(
                    name=case['emp1'].name,
                    name_normalized=Employer.normalize_name(case['emp1'].name),
                    city=case['emp1'].city,
                    state=case['emp1'].state
                )
                emp2 = Employer(
                    name=case['emp2'].name,
                    name_normalized=Employer.normalize_name(case['emp2'].name),
                    city=case['emp2'].city,
                    state=case['emp2'].state
                )
                
                is_match, confidence, reason = match_employers(emp1, emp2)
                
                self.assertTrue(
                    is_match,
                    f"Recall: Should match hyphen variation with same location: "
                    f"'{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']}) - "
                    f"reason: {reason}, confidence: {confidence:.3f}"
                )
    
    def test_case_variations_should_match(self):
        """Test that case variations (uppercase vs mixed case) of the same name should match."""
        case_variation_cases = [
            {
                'emp1': Employer(name='BBC RETAIL AND INTERNET LLC', city='Seattle', state='WA'),
                'emp2': Employer(name='BBC Retail and Internet LLC', city='Seattle', state='WA'),
                'should_match': True,
                'reason': 'Case variation of same company name'
            },
            {
                'emp1': Employer(name='GOOGLE INC', city='Mountain View', state='CA'),
                'emp2': Employer(name='Google Inc', city='Mountain View', state='CA'),
                'should_match': True,
                'reason': 'Case variation of same company name'
            },
            {
                'emp1': Employer(name='JP MORGAN CHASE & CO', city='New York', state='NY'),
                'emp2': Employer(name='JP Morgan Chase & Co', city='New York', state='NY'),
                'should_match': True,
                'reason': 'Case variation of same company name'
            },
        ]
        
        for case in case_variation_cases:
            with self.subTest(emp1=case['emp1'].name, emp2=case['emp2'].name):
                emp1 = Employer(
                    name=case['emp1'].name,
                    name_normalized=Employer.normalize_name(case['emp1'].name),
                    city=case['emp1'].city,
                    state=case['emp1'].state
                )
                emp2 = Employer(
                    name=case['emp2'].name,
                    name_normalized=Employer.normalize_name(case['emp2'].name),
                    city=case['emp2'].city,
                    state=case['emp2'].state
                )
                
                is_match, confidence, reason = match_employers(emp1, emp2)
                
                self.assertTrue(
                    is_match,
                    f"Should match case variation: "
                    f"'{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']}) - "
                    f"reason: {reason}, confidence: {confidence:.3f}"
                )
                
                # Case variations should have exact match confidence
                self.assertEqual(
                    confidence, 1.0,
                    f"Case variations should have exact match confidence (1.0): "
                    f"'{case['emp1'].name}' vs '{case['emp2'].name}' - "
                    f"got confidence: {confidence:.3f}"
                )
    
    def test_no_fully_identical_examples(self):
        """Test that the golden set doesn't contain fully identical examples.
        
        Fully identical examples (same name, same city, same state) don't test
        the clustering algorithm and should be removed from the golden set.
        """
        identical_examples = []
        
        for example in self.examples:
            name1 = example.get('emp1_name', '').upper().strip()
            name2 = example.get('emp2_name', '').upper().strip()
            city1 = example.get('emp1_city', '').upper().strip()
            city2 = example.get('emp2_city', '').upper().strip()
            state1 = example.get('emp1_state', '').upper().strip()
            state2 = example.get('emp2_state', '').upper().strip()
            
            # Check if fully identical
            if name1 == name2 and city1 == city2 and state1 == state2:
                identical_examples.append({
                    'name': example.get('emp1_name'),
                    'city': city1,
                    'state': state1,
                    'ground_truth': example.get('ground_truth')
                })
        
        self.assertEqual(
            len(identical_examples), 0,
            f"Found {len(identical_examples)} fully identical examples in golden set. "
            f"These should be removed as they don't test clustering behavior. "
            f"Examples: {identical_examples[:5]}"
        )


if __name__ == '__main__':
    unittest.main()


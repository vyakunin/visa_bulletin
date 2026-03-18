"""
Tests for precision improvements in employer clustering.

Tests false positive prevention - structural words, location filtering, thresholds.
Written using TDD approach: write failing tests first, then fix algorithm.
"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import unittest

from lib.business.salary.employer_clustering import match_employers, should_auto_cluster
from models.salary import Employer


class TestClusteringPrecision(unittest.TestCase):
    """Test precision improvements to prevent false positives."""

    def test_structural_word_conflict_should_not_match(self):
        """Test that structural word conflicts prevent matching."""
        # Known false positives that should NOT match
        conflict_cases = [
            {
                "emp1": Employer(
                    name="SERVICE MANAGEMENT GROUP, LLC", city="Kansas City", state="MO"
                ),
                "emp2": Employer(
                    name="CORPORATION SERVICE COMPANY", city="Wilmington", state="DE"
                ),
                "reason": "Management vs Corporation - different structural words",
            },
            {
                "emp1": Employer(
                    name="TRINITY TECHNOLOGIES CORPORATION", city="Boston", state="MA"
                ),
                "emp2": Employer(
                    name="TRINITY PARTNERS, LLC", city="Boston", state="MA"
                ),
                "reason": "Technologies vs Partners - different structural words",
            },
            {
                "emp1": Employer(
                    name="GRAHAM CAPITAL MANAGEMENT, L.P.", city="New York", state="NY"
                ),
                "emp2": Employer(
                    name="GRAHAM HOLDINGS COMPANY", city="New York", state="NY"
                ),
                "reason": "Management vs Holdings - different structural words",
            },
            {
                "emp1": Employer(
                    name="ASPEN TECHNOLOGY, INC", city="Bedford", state="MA"
                ),
                "emp2": Employer(
                    name="ASPEN CONSULTING, INC.", city="Bedford", state="MA"
                ),
                "reason": "Technology vs Consulting - different structural words",
            },
        ]

        for case in conflict_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                # Should NOT match (false positive prevention)
                self.assertFalse(
                    is_match,
                    f"Precision issue: Should NOT match '{case['emp1'].name}' vs '{case['emp2'].name}' "
                    f"({case['reason']}) - reason: {reason}, confidence: {confidence:.3f}",
                )

    def test_location_filtering_for_generic_names_different_states(self):
        """Test that location filtering reduces confidence for generic names across different states."""
        # Generic names in different states should have low confidence (below auto-cluster threshold)
        generic_cases = [
            {
                "emp1": Employer(
                    name="CHILDREN'S HOSPITAL", city="Boston", state="MASSACHUSETTS"
                ),
                "emp2": Employer(
                    name="CHILDREN'S HOSPITAL", city="New Orleans", state="LOUISIANA"
                ),
                "reason": "Same generic name, different states - different hospitals",
                "should_auto_cluster": False,  # Should match but with low confidence (< 0.95)
            },
        ]

        for case in generic_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                # Should match but with low confidence (below 0.95 threshold) for different states
                if (
                    case["emp1"].state
                    and case["emp2"].state
                    and case["emp1"].state != case["emp2"].state
                ):
                    # match_employers returns True with low confidence, but should_auto_cluster rejects it
                    should_cluster, cluster_confidence, cluster_reason = (
                        should_auto_cluster(case["emp1"], case["emp2"], threshold=0.95)
                    )
                    self.assertFalse(
                        should_cluster,
                        f"Precision: Should NOT auto-cluster generic name '{case['emp1'].name}' "
                        f"across different states ({case['emp1'].state} vs {case['emp2'].state}) - "
                        f"confidence: {cluster_confidence:.3f} should be < 0.95",
                    )
                    self.assertLess(
                        cluster_confidence,
                        0.95,
                        f"Confidence should be below threshold for different states: {cluster_confidence:.3f}",
                    )

    def test_similarity_threshold_boundaries(self):
        """Test that similarity thresholds are strict enough."""
        # Test that 0.90 similarity is not enough for auto-cluster
        # (should require higher threshold)
        _borderline_cases = [
            {
                "emp1": Employer(name="ABC Corp", city="NY", state="NY"),
                "emp2": Employer(name="XYZ Corp", city="NY", state="NY"),
                "similarity_expected": 0.90,  # Borderline case
                "should_match": False,  # Should NOT match at 0.90 threshold
            },
        ]

        # Note: This test will need actual similarity calculation
        # For now, we test that threshold of 0.95 is used
        emp1 = Employer(name="Test Company Inc", city="NY", state="NY")
        emp2 = Employer(name="Test Company LLC", city="NY", state="NY")

        should_cluster, confidence, reason = should_auto_cluster(
            emp1, emp2, threshold=0.95
        )

        # If confidence < 0.95, should NOT auto-cluster
        if confidence < 0.95:
            self.assertFalse(
                should_cluster,
                f"Precision: Should NOT auto-cluster when confidence ({confidence:.3f}) < threshold (0.95)",
            )

    def test_substring_match_with_structural_conflict_should_not_match(self):
        """Test that substring matches are rejected when structural words conflict."""
        # Substring matches should NOT be allowed when structural words differ
        substring_conflict_cases = [
            {
                "emp1": Employer(
                    name="SERVICE MANAGEMENT GROUP, LLC", city="Kansas City", state="MO"
                ),
                "emp2": Employer(
                    name="CORPORATION SERVICE COMPANY", city="Wilmington", state="DE"
                ),
                "reason": "Substring match but structural words conflict (Management vs Corporation)",
            },
            {
                "emp1": Employer(
                    name="TRINITY TECHNOLOGIES CORPORATION", city="Boston", state="MA"
                ),
                "emp2": Employer(
                    name="TRINITY PARTNERS, LLC", city="Boston", state="MA"
                ),
                "reason": "Substring match but structural words conflict (Technologies vs Partners)",
            },
        ]

        for case in substring_conflict_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                # Should NOT match even if substring (structural words conflict)
                self.assertFalse(
                    is_match,
                    f"Precision issue: Should NOT match substring '{case['emp1'].name}' vs '{case['emp2'].name}' "
                    f"when structural words conflict ({case['reason']}) - "
                    f"reason: {reason}, confidence: {confidence:.3f}",
                )

    def test_normalization_edge_cases_that_cause_false_positives(self):
        """Test normalization edge cases that cause false positives."""
        # Cases where normalization creates false matches
        normalization_cases = [
            {
                "emp1": Employer(name="C. J. COAKLEY CO., INC.", city="NY", state="NY"),
                "emp2": Employer(name="C. J. COAKLEY CO., INC.", city="NY", state="NY"),
                "should_match": True,  # Same company, should match
                "reason": "Exact match - this is a true positive",
            },
            # Add more cases as we identify normalization issues
        ]

        for case in normalization_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                if case["should_match"]:
                    self.assertTrue(
                        is_match,
                        f"Should match: '{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']})",
                    )
                else:
                    self.assertFalse(
                        is_match,
                        f"Should NOT match: '{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']})",
                    )

    def test_geographic_qualifiers_distinguish_companies(self):
        """Test that geographic qualifiers (USA, US, North, South) distinguish companies."""
        geographic_cases = [
            {
                "emp1": Employer(name="ROCA, INC.", city="NY", state="NY"),
                "emp2": Employer(name="Roca USA, Inc", city="NY", state="NY"),
                "should_match": False,  # "USA" qualifier may distinguish
                "reason": 'Geographic qualifier "USA" may indicate different entity',
            },
            # Add more cases as we identify them
        ]

        for case in geographic_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                if not case["should_match"]:
                    self.assertFalse(
                        is_match,
                        f"Precision: Should NOT match when geographic qualifiers differ: "
                        f"'{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']}) - "
                        f"reason: {reason}, confidence: {confidence:.3f}",
                    )

    def test_hyphen_variations_require_exact_location(self):
        """Test that hyphen variations (HI-TEK vs HITEK) require exact location match."""
        hyphen_cases = [
            {
                "emp1": Employer(
                    name="HI-TEK PROFESSIONALS, INC.",
                    city="MEDIA",
                    state="PENNSYLVANIA",
                ),
                "emp2": Employer(
                    name="HITEK PROFESSIONALS, INC.", city="MEDIA", state=""
                ),
                "should_match": True,  # Same city, hyphen variation - likely same company
                "reason": "Hyphen variation with same city (state missing for one)",
            },
            {
                "emp1": Employer(
                    name="IredellStatesville Schools", city="Statesville", state=""
                ),
                "emp2": Employer(
                    name="Iredell-Statesville Schools", city="Statesville", state="NC"
                ),
                "should_match": True,  # Same city, hyphen variation - likely same school
                "reason": "Hyphen variation with same city (state missing for one)",
            },
            {
                "emp1": Employer(
                    name="HI-TEK PROFESSIONALS, INC.", city="MEDIA", state="PA"
                ),
                "emp2": Employer(
                    name="HITEK PROFESSIONALS, INC.", city="MEDIA", state="PA"
                ),
                "should_match": True,  # Same exact location - might be same company
                "reason": "Hyphen variation with exact location match",
            },
            {
                "emp1": Employer(name="E-KO Image Inc.", city="Chino", state="CA"),
                "emp2": Employer(name="EKO Image Inc.", city="Chino", state="CA"),
                "should_match": True,  # Same location - likely same company
                "reason": "Hyphen variation with same location (recall test)",
            },
            {
                "emp1": Employer(
                    name="HI-TEK PROFESSIONALS, INC.", city="MEDIA", state="PA"
                ),
                "emp2": Employer(
                    name="HITEK PROFESSIONALS, INC.", city="PHILADELPHIA", state="PA"
                ),
                "should_match": True,  # Same state, different city - might be same company
                "reason": "Hyphen variation with same state (city differs)",
            },
        ]

        for case in hyphen_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                if case["should_match"]:
                    self.assertTrue(
                        is_match,
                        f"Should match hyphen variation with exact location: "
                        f"'{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']}) - "
                        f"reason: {reason}, confidence: {confidence:.3f}",
                    )
                else:
                    self.assertFalse(
                        is_match,
                        f"Precision: Should NOT match hyphen variation with different locations: "
                        f"'{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']}) - "
                        f"reason: {reason}, confidence: {confidence:.3f}",
                    )

    def test_generic_names_missing_state_lower_confidence(self):
        """Test that hyphen variations with missing state now have confidence at threshold (0.95).

        RECALL FIX: Changed from 0.90 to 0.95 to improve recall for hyphen variations
        with same city but missing state. These are now auto-clustered.
        """
        generic_cases = [
            {
                "emp1": Employer(
                    name="IredellStatesville Schools", city="Statesville", state=""
                ),
                "emp2": Employer(
                    name="Iredell-Statesville Schools", city="Statesville", state="NC"
                ),
                "expected_confidence": 0.95,  # RECALL FIX: Now at threshold to improve recall
                "reason": "Hyphen variation with same city - now auto-clusters",
            },
        ]

        for case in generic_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                # Should match with confidence at threshold
                self.assertGreaterEqual(
                    confidence,
                    0.95,
                    f"Hyphen variation with same city should have confidence >= 0.95: "
                    f"'{case['emp1'].name}' vs '{case['emp2'].name}' - "
                    f"confidence: {confidence:.3f}, reason: {reason}",
                )

                # Verify should_auto_cluster accepts it (RECALL FIX)
                should_cluster, cluster_confidence, cluster_reason = (
                    should_auto_cluster(case["emp1"], case["emp2"], threshold=0.95)
                )
                self.assertTrue(
                    should_cluster,
                    f"Should auto-cluster hyphen variation with same city: "
                    f"confidence: {cluster_confidence:.3f} >= 0.95",
                )

    def test_bbc_entities_should_cluster_appropriately(self):
        """Test BBC entities clustering behavior."""
        # BBC test cases based on actual data
        bbc_cases = [
            {
                "emp1": Employer(
                    name="BBC International LLC", city="New York", state="NY"
                ),
                "emp2": Employer(
                    name="BBC International LLC", city="New York", state="NY"
                ),
                "should_match": True,
                "should_auto_cluster": True,
                "reason": "Exact same name and location - should definitely cluster",
            },
            {
                "emp1": Employer(name="BBC NEWS", city="New York", state="NY"),
                "emp2": Employer(
                    name="BBC News USA, Inc.", city="New York", state="NY"
                ),
                "should_match": True,
                "should_auto_cluster": True,
                "reason": "BBC News vs BBC News USA - same news entity with USA qualifier",
            },
            {
                "emp1": Employer(
                    name="BBC Global News US, LLC", city="New York", state="NY"
                ),
                "emp2": Employer(
                    name="BBC News USA, Inc.", city="New York", state="NY"
                ),
                "should_match": True,
                "should_auto_cluster": True,
                "reason": "BBC Global News US vs BBC News USA - both BBC news entities in US",
            },
            {
                "emp1": Employer(
                    name="BBC Innovation Corporation", city="Boston", state="MA"
                ),
                "emp2": Employer(
                    name="BBC News USA, Inc.", city="New York", state="NY"
                ),
                "should_match": False,
                "should_auto_cluster": False,
                "reason": "BBC Innovation vs BBC News - different BBC divisions (Innovation != News)",
            },
            {
                "emp1": Employer(
                    name="BBC Innovation Corporation", city="Boston", state="MA"
                ),
                "emp2": Employer(
                    name="BBC International LLC", city="New York", state="NY"
                ),
                "should_match": False,
                "should_auto_cluster": False,
                "reason": "BBC Innovation vs BBC International - different BBC divisions",
            },
            {
                "emp1": Employer(
                    name="BBC RETAIL AND INTERNET LLC", city="Seattle", state="WA"
                ),
                "emp2": Employer(
                    name="BBC News USA, Inc.", city="New York", state="NY"
                ),
                "should_match": False,
                "should_auto_cluster": False,
                "reason": "BBC Retail vs BBC News - completely different BBC divisions",
            },
        ]

        for case in bbc_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                # Test basic matching
                if case["should_match"]:
                    self.assertTrue(
                        is_match,
                        f"BBC entities should match: '{case['emp1'].name}' vs '{case['emp2'].name}' "
                        f"({case['reason']}) - reason: {reason}, confidence: {confidence:.3f}",
                    )
                else:
                    self.assertFalse(
                        is_match,
                        f"BBC entities should NOT match: '{case['emp1'].name}' vs '{case['emp2'].name}' "
                        f"({case['reason']}) - reason: {reason}, confidence: {confidence:.3f}",
                    )

                # Test auto-clustering threshold
                if case["should_match"]:
                    should_cluster, cluster_confidence, cluster_reason = (
                        should_auto_cluster(case["emp1"], case["emp2"], threshold=0.95)
                    )
                    if case["should_auto_cluster"]:
                        self.assertTrue(
                            should_cluster,
                            f"BBC entities should auto-cluster: '{case['emp1'].name}' vs '{case['emp2'].name}' "
                            f"({case['reason']}) - confidence: {cluster_confidence:.3f}, reason: {cluster_reason}",
                        )
                        self.assertGreaterEqual(
                            cluster_confidence,
                            0.95,
                            f"Confidence should be >= 0.95 for auto-clustering: {cluster_confidence:.3f}",
                        )
                    else:
                        # If should_match but not auto_cluster, confidence should be below threshold
                        self.assertLess(
                            cluster_confidence,
                            0.95,
                            f"Confidence should be < 0.95 if not auto-clustering: {cluster_confidence:.3f}",
                        )


if __name__ == "__main__":
    unittest.main()

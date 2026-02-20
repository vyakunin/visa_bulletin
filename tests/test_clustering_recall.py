"""Tests for recall improvements and bucket mismatch handling"""

import os
import sys
import unittest

import django

# Add project root to path
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, project_root)

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.salary.employer_clustering import (
    _get_fuzzy_bucket_candidates,
    match_employers,
    should_auto_cluster,
)
from models.salary import Employer


class TestClusteringRecall(unittest.TestCase):
    """Test recall improvements and bucket mismatch handling"""

    def test_hyphen_variations_with_missing_state_should_match(self):
        """Test that hyphen variations with same city but missing state now match (recall fix)."""
        # RECALL FIX: Increased confidence from 0.90 to 0.95 for hyphen variations
        # with same city but missing state, so they pass auto-cluster threshold
        hyphen_cases = [
            {
                "emp1": Employer(
                    name="IredellStatesville Schools", city="Statesville", state=""
                ),
                "emp2": Employer(
                    name="Iredell-Statesville Schools", city="Statesville", state="NC"
                ),
                "should_match": True,
                "min_confidence": 0.95,  # Should be at threshold to pass auto-cluster
                "reason": "Hyphen variation with same city (state missing)",
            },
            {
                "emp1": Employer(name="E-KO Image Inc.", city="Chino", state=""),
                "emp2": Employer(name="EKO Image Inc.", city="Chino", state="CA"),
                "should_match": True,
                "min_confidence": 0.95,
                "reason": "Hyphen variation with same city (state missing)",
            },
            {
                "emp1": Employer(
                    name="HI-TEK PROFESSIONALS, INC.",
                    city="MEDIA",
                    state="PENNSYLVANIA",
                ),
                "emp2": Employer(
                    name="HITEK PROFESSIONALS, INC.", city="MEDIA", state=""
                ),
                "should_match": True,
                "min_confidence": 0.95,
                "reason": "Hyphen variation with same city (state missing)",
            },
        ]

        for case in hyphen_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                is_match, confidence, reason = match_employers(
                    case["emp1"], case["emp2"]
                )

                self.assertTrue(
                    is_match,
                    f"Should match: '{case['emp1'].name}' vs '{case['emp2'].name}' ({case['reason']}) - "
                    f"reason: {reason}, confidence: {confidence:.3f}",
                )

                self.assertGreaterEqual(
                    confidence,
                    case.get("min_confidence", 0.95),
                    f"Confidence should be >= 0.95 to pass auto-cluster threshold: "
                    f"'{case['emp1'].name}' vs '{case['emp2'].name}' - "
                    f"confidence: {confidence:.3f}",
                )

                # Verify should_auto_cluster accepts it
                should_cluster, cluster_confidence, cluster_reason = (
                    should_auto_cluster(case["emp1"], case["emp2"], threshold=0.95)
                )
                self.assertTrue(
                    should_cluster,
                    f"Should auto-cluster hyphen variation with same city: "
                    f"confidence: {cluster_confidence:.3f} >= 0.95",
                )

    def test_bucket_mismatch_cases_should_match(self):
        """Test known bucket mismatch cases that should match (production issue).

        These are cases where normalization creates different buckets but they should
        still be compared and matched. This tests the algorithm's ability to handle
        normalization variations.
        """
        # Note: These are bucket mismatches in production (different normalized buckets)
        # but the algorithm should still match them when they're compared
        bucket_mismatch_cases = [
            {
                "emp1": Employer(name="HBSS CONNEC CORP", city="LOWELL", state="MA"),
                "emp2": Employer(name="HBSS Connect Corp", city="LOWELL", state="MA"),
                "should_match": True,
                "reason": "Typo normalization: CONNEC vs Connect (bucket mismatch)",
            },
            {
                "emp1": Employer(
                    name="APPLIED TESTESTING  GEOSCIENCES, LLC",
                    city="BRIDGEPORT",
                    state="PA",
                ),
                "emp2": Employer(
                    name="APPLIED TESTESTING & GEOSCIENCES, LLC",
                    city="BRIDGEPORT",
                    state="PA",
                ),
                "should_match": True,
                "reason": "Double space vs ampersand (bucket mismatch)",
            },
            {
                "emp1": Employer(
                    name="Merck Sharp & Dohme Corp.", city="Kenilworth", state="NJ"
                ),
                "emp2": Employer(
                    name="MERCK SHARP & DOHME CORP",
                    city="KENILWORTH",
                    state="NEW JERSEY",
                ),
                "should_match": True,
                "reason": "Ampersand normalization: & vs and (bucket mismatch)",
            },
        ]

        for case in bucket_mismatch_cases:
            with self.subTest(emp1=case["emp1"].name, emp2=case["emp2"].name):
                # These might normalize to different buckets, but if compared, should match
                norm1 = Employer.normalize_name(case["emp1"].name)
                norm2 = Employer.normalize_name(case["emp2"].name)

                # If they normalize to same bucket, should match
                if norm1 == norm2:
                    is_match, confidence, reason = match_employers(
                        case["emp1"], case["emp2"]
                    )
                    self.assertTrue(
                        is_match,
                        f"Should match (same normalized bucket): '{case['emp1'].name}' vs '{case['emp2'].name}' - "
                        f"reason: {reason}, confidence: {confidence:.3f}",
                    )
                else:
                    # Different buckets - this is a production issue (normalization needs fixing)
                    # But if they were compared, similarity matching should catch them
                    is_match, confidence, reason = match_employers(
                        case["emp1"], case["emp2"]
                    )
                    if case["should_match"]:
                        # High similarity should still match even with different buckets
                        self.assertTrue(
                            is_match,
                            f"Should match via similarity (bucket mismatch): '{case['emp1'].name}' vs '{case['emp2'].name}' - "
                            f"normalized: '{norm1}' vs '{norm2}', reason: {reason}, confidence: {confidence:.3f}",
                        )

    def test_fuzzy_bucket_candidates_generate_overlap(self):
        """Test that fuzzy bucket candidates generate overlapping buckets for similar names."""
        test_cases = [
            {
                "name1": "hbss connec corp",
                "name2": "hbss connect corp",
                "should_overlap": True,
                "reason": "Typo: CONNEC vs Connect should share word initials bucket",
            },
            {
                "name1": "mercedesbenz van",
                "name2": "mercede benz van",
                "should_overlap": True,
                "reason": "Spacing variation should share prefix+suffix bucket",
            },
            {
                "name1": "hi mom enterrise",
                "name2": "hi mom enterprise",
                "should_overlap": True,
                "reason": "Typo should share word initials bucket",
            },
            {
                "name1": "google inc",
                "name2": "microsoft corp",
                "should_overlap": False,
                "reason": "Different companies should not share buckets",
            },
        ]

        for case in test_cases:
            with self.subTest(name1=case["name1"], name2=case["name2"]):
                buckets1 = _get_fuzzy_bucket_candidates(case["name1"])
                buckets2 = _get_fuzzy_bucket_candidates(case["name2"])
                overlap = buckets1 & buckets2

                if case["should_overlap"]:
                    self.assertTrue(
                        bool(overlap),
                        f"Should have overlapping buckets: '{case['name1']}' vs '{case['name2']}' "
                        f"({case['reason']}) - buckets1: {buckets1}, buckets2: {buckets2}",
                    )
                else:
                    self.assertFalse(
                        bool(overlap),
                        f"Should NOT have overlapping buckets: '{case['name1']}' vs '{case['name2']}' "
                        f"({case['reason']}) - overlap: {overlap}",
                    )


if __name__ == "__main__":
    unittest.main()

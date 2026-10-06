"""Calibrated intervals: the error-distribution cache and the stratum an interval is drawn from.

The cache must be keyed by action_type.

Regression: the cache was keyed only by knowledge-date month, ignoring
action_type. publish_predictions processes final_action first, then filing, so
filing CIs silently reused the final_action error distribution — blowing the
filing CI out to multi-year widths (EB-3 India filing upper bound ran to 2018
for a Jan-2015 point estimate; its own distribution gives ~5 months).
"""

import unittest
from datetime import date, timedelta

from lib.business.vqs import calibration as cal


class TestCalibrationCachePerAction(unittest.TestCase):
    def setUp(self):
        self._orig_build = cal._build_error_distributions
        cal._error_distribution_cache = {}
        cal._cache_knowledge_month = None
        self.calls: list[str] = []

        def fake_build(kd, action_type="filing"):
            self.calls.append(action_type)
            # Distinct sentinel per action_type so sharing is detectable.
            return {("3rd", 3, 1, "volatile"): [1170] if action_type == "final_action" else [162]}

        cal._build_error_distributions = fake_build

    def tearDown(self):
        cal._build_error_distributions = self._orig_build
        cal._error_distribution_cache = {}
        cal._cache_knowledge_month = None

    def test_distributions_not_shared_across_action_types(self):
        kd = date(2026, 7, 31)
        fa = cal._get_error_distributions(kd, "final_action")
        fi = cal._get_error_distributions(kd, "filing")
        self.assertEqual(fa[("3rd", 3, 1, "volatile")], [1170])
        self.assertEqual(fi[("3rd", 3, 1, "volatile")], [162])  # NOT the final_action dist
        self.assertEqual(sorted(self.calls), ["filing", "final_action"])

    def test_same_action_is_cached_not_rebuilt(self):
        kd = date(2026, 7, 31)
        cal._get_error_distributions(kd, "filing")
        cal._get_error_distributions(kd, "filing")
        self.assertEqual(self.calls, ["filing"])  # second call served from cache

    def test_month_advance_rebuilds(self):
        cal._get_error_distributions(date(2026, 7, 31), "filing")
        cal._get_error_distributions(date(2026, 8, 31), "filing")
        self.assertEqual(self.calls, ["filing", "filing"])  # new month → rebuilt


class TestRegimeStratumMinimum(unittest.TestCase):
    """A thin regime stratum pools with the series' other regimes; a full one stands alone."""

    PRED = date(2023, 2, 1)

    def setUp(self):
        self._orig_regime = cal._get_regime
        self._orig_dists = cal._get_error_distributions
        cal._get_regime = lambda *a, **k: "recovering"
        self.dists: dict = {}
        cal._get_error_distributions = lambda kd, at="filing": self.dists

    def tearDown(self):
        cal._get_regime = self._orig_regime
        cal._get_error_distributions = self._orig_dists

    def _interval(self):
        return cal.compute_calibrated_interval(self.PRED, "1st", 3, "final_action", date(2026, 10, 31), 1)

    def test_ten_sample_stratum_is_pooled_not_trusted(self):
        # EB-1 India on 2026-10-06: two 2024 rebound jumps in a 10-sample stratum
        # rendered "80% range: Jan 1, 2023 - Oct 2, 2026".
        self.dists = {
            ("1st", 3, 1, "recovering"): [-31, -30, 0, 0, 30, 31, 31, 31, 1308, 1339],
            ("1st", 3, 1, "advancing"): [0] * 90,
        }
        _, high = self._interval()
        self.assertLess(high, self.PRED + timedelta(days=365))

    def test_full_stratum_is_used_alone(self):
        self.dists = {
            ("1st", 3, 1, "recovering"): list(range(0, 200, 10)),  # 20 samples, 0..190
            ("1st", 3, 1, "advancing"): [0] * 90,
        }
        _, high = self._interval()
        self.assertEqual(high, self.PRED + timedelta(days=180))


if __name__ == "__main__":
    unittest.main()

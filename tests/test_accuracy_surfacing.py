"""Pure-logic tests for the accuracy-surfacing shapers (no DB).

Covers:
* ``compare_to_no_change_baseline``'s new ``prev_cutoff_lookup`` param — it must
  score the no-change baseline from the supplied lookup WITHOUT touching the
  process-global ``data_cache`` (so a request path / test never depends on those
  never-invalidated memo caches).
* ``build_month_rollup`` — builds the recap-page banner straight from the page's
  ``matrix`` + the previous month's real actuals, producing per-category bands +
  a model-vs-no-change comparison, and ``None`` when nothing is scoreable.

Every number is derived from the real ``compute_bulletin_accuracy_summary`` /
``compare_to_no_change_baseline`` path — no hardcoded accuracy figures.
"""

from datetime import date
from unittest.mock import patch

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import SimpleTestCase  # noqa: E402

from lib.business.vqs.accuracy_metrics import (  # noqa: E402
    BulletinAccuracyRow,
    compare_to_no_change_baseline,
)
from lib.business.vqs.accuracy_surfacing import build_month_rollup  # noqa: E402
from models.enums.country import Country  # noqa: E402

_INDIA = Country.INDIA.value
_MONTH = date(2026, 8, 1)


def _row(vc, atype, pred, actual, err):
    return BulletinAccuracyRow(
        bulletin_date=_MONTH,
        visa_class=vc,
        country=_INDIA,
        action_type=atype,
        predicted_cutoff=pred,
        actual_cutoff=actual,
        error_days=err,
    )


class _Pred:
    """Stand-in for the recap view's prediction display object."""

    def __init__(self, d):
        self.predicted_date = d


class BaselineLookupTest(SimpleTestCase):
    def test_lookup_used_and_data_cache_untouched(self):
        # EB-2 India: model err 9d, no-change (prev 15 Nov -> actual 1 Dec) 16d
        # -> model wins. EB-3 India: model 13d, no-change (prev 1 Jan -> actual
        # 1 Feb) 31d -> model wins.
        rows = [
            _row("2nd", "final_action", date(2019, 12, 10), date(2019, 12, 1), 9),
            _row("3rd", "final_action", date(2013, 1, 19), date(2013, 2, 1), 13),
        ]
        prev_lookup = {
            ("2nd", _INDIA, "final_action", _MONTH): date(2019, 11, 15),
            ("3rd", _INDIA, "final_action", _MONTH): date(2013, 1, 1),
        }
        # If the lookup path ever fell through to data_cache, this patch would
        # raise — proving the request-safe path avoids the global cache.
        with patch(
            "lib.business.vqs.data_cache.get_cutoff_at_date",
            side_effect=AssertionError("data_cache must not be hit when a lookup is given"),
        ):
            res = compare_to_no_change_baseline(rows, prev_cutoff_lookup=prev_lookup)
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["model_wins"], 2)
        self.assertEqual(res["model_mean_error"], 11.0)  # mean(9, 13)
        self.assertEqual(res["baseline_mean_error"], 23.5)  # mean(16, 31)
        self.assertTrue(res["beats_baseline"])

    def test_missing_prev_row_is_skipped(self):
        rows = [_row("2nd", "final_action", date(2019, 12, 10), date(2019, 12, 1), 9)]
        # No entry in the lookup -> that row cannot be baselined -> excluded.
        res = compare_to_no_change_baseline(rows, prev_cutoff_lookup={})
        self.assertEqual(res["total"], 0)
        self.assertIsNone(res["model_win_pct"])


class BuildMonthRollupTest(SimpleTestCase):
    def _matrix(self):
        # EB-2 India FA: pred 10 Dec 2019 vs actual 1 Dec 2019 -> |9| days.
        # EB-3 India FA: pred 19 Jan 2013 vs actual 1 Feb 2013 -> |13| days.
        # Filing cells unpredicted; EB-2 India filing actual is Current (skip).
        return {
            "2nd": {
                _INDIA: {
                    "final_action": {
                        "predicted": _Pred(date(2019, 12, 10)),
                        "actual_date": date(2019, 12, 1),
                        "actual_is_current": False,
                        "actual_is_unavailable": False,
                    },
                    "filing": {
                        "predicted": None,
                        "actual_date": date(2020, 1, 1),
                        "actual_is_current": True,  # Current -> not scoreable
                        "actual_is_unavailable": False,
                    },
                }
            },
            "3rd": {
                _INDIA: {
                    "final_action": {
                        "predicted": _Pred(date(2013, 1, 19)),
                        "actual_date": date(2013, 2, 1),
                        "actual_is_current": False,
                        "actual_is_unavailable": False,
                    },
                    "filing": {"predicted": None, "actual_date": None},
                }
            },
        }

    def test_rollup_numbers_and_bands(self):
        roll = build_month_rollup(
            self._matrix(),
            _MONTH,
            ["2nd", "3rd"],
            [_INDIA],
            {("2nd", _INDIA, "final_action"): date(2019, 11, 15)},  # prev for EB-2 only
            {"2nd": "EB-2", "3rd": "EB-3"},
        )
        self.assertIsNotNone(roll)
        self.assertEqual(roll["n_scored"], 2)  # both FA cells scored
        self.assertEqual(roll["mae_days"], 11)  # round(mean(9, 13))
        self.assertEqual(roll["max_days"], 13)
        bands = {b["label"]: b["mae_days"] for b in roll["bands"]}
        self.assertEqual(bands, {"EB-2": 9, "EB-3": 13})
        # Baseline: only EB-2 has a prev actual in the lookup.
        base = roll["baseline"]
        self.assertEqual(base["total"], 1)
        self.assertEqual(base["model_wins"], 1)  # 9d < 16d no-change
        self.assertEqual(base["model_mean"], 9.0)
        self.assertEqual(base["baseline_mean"], 16.0)
        self.assertTrue(base["beats_baseline"])

    def test_returns_none_when_nothing_scoreable(self):
        # All actuals Current -> no scoreable pair -> None (banner omitted).
        matrix = {
            "2nd": {
                _INDIA: {
                    "final_action": {
                        "predicted": _Pred(date(2019, 12, 10)),
                        "actual_date": date(2020, 1, 1),
                        "actual_is_current": True,
                        "actual_is_unavailable": False,
                    },
                    "filing": {"predicted": None, "actual_date": None},
                }
            }
        }
        roll = build_month_rollup(
            matrix, _MONTH, ["2nd"], [_INDIA], {}, {"2nd": "EB-2"}
        )
        self.assertIsNone(roll)

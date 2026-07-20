"""Tests for the post-ingest VQS reporting hook.

Regression cover for a dangling import that silently disabled the hook: the
orchestrator imports `lib.business.vqs.reporting` lazily, inside a try/except
that only logs a warning, and `reporting.py` had no Bazel target -- so an
import of a name that never existed in `accuracy_metrics` broke the hook on
every bulletin ingest without failing a build, a test, or the ingest itself.

Pure unit tests - no DB, no Django.
"""

from datetime import date

from lib.business.vqs.accuracy_metrics import (
    BulletinAccuracyRow,
    compute_bulletin_accuracy_summary,
)


def _row(
    visa_class: str = "2nd",
    country: int = 1,
    error_days: int | None = 10,
    action_type: str = "final_action",
) -> BulletinAccuracyRow:
    return BulletinAccuracyRow(
        bulletin_date=date(2026, 8, 1),
        visa_class=visa_class,
        country=country,
        action_type=action_type,
        predicted_cutoff=date(2024, 8, 1),
        actual_cutoff=date(2024, 8, 11),
        error_days=error_days,
    )


class TestReportingHookImports:
    """The hook must be importable -- this is the bug that shipped."""

    def test_reporting_module_imports(self):
        # Regression: `compute_bulletin_accuracy_summary` was imported here but
        # never defined in accuracy_metrics, so this import raised ImportError
        # on every post-ingest run.
        from lib.business.vqs.reporting import run_post_ingest_evaluation

        assert callable(run_post_ingest_evaluation)


class TestBulletinAccuracySummary:
    def test_empty_rows_give_null_metrics_not_crash(self):
        summary = compute_bulletin_accuracy_summary([])
        assert summary["overall"]["count"] == 0
        assert summary["overall"]["mean_error_days"] is None
        assert summary["overall"]["mean_abs_error_days"] is None

    def test_mae_uses_absolute_error_signed_mean_does_not(self):
        # +30 and -30 cancel in the signed mean but not in MAE.
        rows = [_row(error_days=30), _row(error_days=-30)]
        summary = compute_bulletin_accuracy_summary(rows)
        assert summary["overall"]["mean_error_days"] == 0.0
        assert summary["overall"]["mean_abs_error_days"] == 30.0
        assert summary["overall"]["count"] == 2

    def test_rows_without_a_prediction_are_excluded(self):
        rows = [_row(error_days=10), _row(error_days=None)]
        summary = compute_bulletin_accuracy_summary(rows)
        assert summary["overall"]["count"] == 1
        assert summary["overall"]["mean_abs_error_days"] == 10.0

    def test_eb4_excluded_by_default_as_policy_driven(self):
        rows = [_row(visa_class="2nd", error_days=10), _row(visa_class="4th", error_days=200)]
        summary = compute_bulletin_accuracy_summary(rows)
        assert summary["overall"]["count"] == 1
        assert summary["overall"]["mean_abs_error_days"] == 10.0

        keep = compute_bulletin_accuracy_summary(rows, exclude_eb4=False)
        assert keep["overall"]["count"] == 2

    def test_by_series_breakdown_is_keyed_like_ci_coverage(self):
        rows = [
            _row(visa_class="2nd", country=1, error_days=10),
            _row(visa_class="2nd", country=1, error_days=20),
            _row(visa_class="3rd", country=2, error_days=-40),
        ]
        summary = compute_bulletin_accuracy_summary(rows)
        assert summary["by_series"]["2nd/1"]["count"] == 2
        assert summary["by_series"]["2nd/1"]["mean_abs_error_days"] == 15.0
        assert summary["by_series"]["3rd/2"]["mean_abs_error_days"] == 40.0

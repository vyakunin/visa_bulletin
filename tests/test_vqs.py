"""Tests for VQS (Virtual Queue Simulation): queue snapshot, demand, solver."""

from datetime import date, timedelta

import pytest

from lib.business.vqs.demand import build_virtual_queue_snapshot
from lib.business.vqs.queue_snapshot import VirtualQueueSnapshot
from lib.business.vqs.solver import run_monthly_loop


class TestVirtualQueueSnapshot:
    """Tests for VirtualQueueSnapshot."""

    def test_add_and_get_demand_between(self):
        snapshot = VirtualQueueSnapshot()
        snapshot.add(date(2023, 1, 1), 100)
        snapshot.add(date(2023, 2, 1), 200)
        snapshot.add(date(2023, 3, 1), 150)
        assert snapshot.get_demand_between(date(2023, 1, 15), date(2023, 2, 28)) == 300
        assert snapshot.get_demand_between(date(2023, 1, 1), date(2023, 3, 1)) == 450
        assert snapshot.get_total_demand() == 450

    def test_advance_cutoff_consumes_supply(self):
        snapshot = VirtualQueueSnapshot()
        snapshot.add(date(2023, 1, 1), 500)
        snapshot.add(date(2023, 2, 1), 400)
        new_cutoff, consumed = snapshot.advance_cutoff(date(2022, 6, 1), 700)
        assert consumed == 700
        assert new_cutoff == date(2023, 2, 1)

    def test_advance_cutoff_exhausts_queue(self):
        snapshot = VirtualQueueSnapshot()
        snapshot.add(date(2023, 1, 1), 100)
        new_cutoff, consumed = snapshot.advance_cutoff(date(2022, 6, 1), 500)
        assert consumed == 100
        assert new_cutoff == date(2023, 1, 1)


class TestBuildVirtualQueueSnapshot:
    """Tests for Model A (demand) naive de-aggregator."""

    def test_filters_by_publication_date(self):
        facts = [
            {
                "metric": "i140_receipts",
                "value": 1000,
                "reference_period_start": date(2024, 4, 1),
                "reference_period_end": date(2024, 6, 30),
                "dimensions": {"country": "India", "category": "2nd"},
                "publication_date": date(2024, 8, 1),
            },
        ]
        snapshot = build_virtual_queue_snapshot(date(2024, 7, 1), facts)
        assert snapshot.get_total_demand() == 0

    def test_includes_facts_on_or_before_knowledge_date(self):
        facts = [
            {
                "metric": "i140_receipts",
                "value": 1000,
                "reference_period_start": date(2024, 4, 1),
                "reference_period_end": date(2024, 6, 30),
                "dimensions": {"country": "India", "category": "2nd"},
                "publication_date": date(2024, 7, 1),
            },
        ]
        snapshot = build_virtual_queue_snapshot(date(2024, 8, 1), facts, visa_class="2nd", country="India")
        assert snapshot.get_total_demand() == 1000
        assert snapshot.get_demand_between(date(2023, 4, 1), date(2023, 4, 30)) == 1000

    def test_filters_by_visa_class_and_country(self):
        facts = [
            {
                "metric": "i140_receipts",
                "value": 500,
                "reference_period_start": date(2024, 4, 1),
                "reference_period_end": date(2024, 6, 30),
                "dimensions": {"country": "India", "category": "2nd"},
                "publication_date": date(2024, 7, 1),
            },
            {
                "metric": "i140_receipts",
                "value": 300,
                "reference_period_start": date(2024, 4, 1),
                "reference_period_end": date(2024, 6, 30),
                "dimensions": {"country": "China", "category": "2nd"},
                "publication_date": date(2024, 7, 1),
            },
        ]
        snapshot = build_virtual_queue_snapshot(date(2024, 8, 1), facts, visa_class="2nd", country="India")
        assert snapshot.get_total_demand() == 500

    def test_convolution_uses_perm_lag_when_available(self):
        """Phase 2: demand distributed by PERM lag buckets when distribution present."""
        q_start = date(2024, 4, 1)
        q_end = date(2024, 6, 30)
        facts = [
            {
                "metric": "perm_lag_distribution",
                "value": {180: 0.5, 270: 0.5},
                "reference_period_start": q_start,
                "reference_period_end": q_end,
                "publication_date": date(2024, 7, 1),
            },
            {
                "metric": "i140_receipts",
                "value": 1000,
                "reference_period_start": q_start,
                "reference_period_end": q_end,
                "dimensions": {"country": "India", "category": "2nd"},
                "publication_date": date(2024, 7, 1),
            },
        ]
        snapshot = build_virtual_queue_snapshot(date(2024, 8, 1), facts, visa_class="2nd", country="India")
        assert snapshot.get_total_demand() == 1000
        pd_180 = q_start - timedelta(days=180)
        pd_270 = q_start - timedelta(days=270)
        bucket_180 = date(pd_180.year, pd_180.month, 1)
        bucket_270 = date(pd_270.year, pd_270.month, 1)
        assert snapshot.get_demand_between(bucket_180, bucket_180) == 500
        assert snapshot.get_demand_between(bucket_270, bucket_270) == 500

    def test_fallback_to_naive_when_no_perm_lag(self):
        """When no perm_lag_distribution for quarter, use fixed 12-month lag."""
        facts = [
            {
                "metric": "i140_receipts",
                "value": 800,
                "reference_period_start": date(2024, 4, 1),
                "reference_period_end": date(2024, 6, 30),
                "dimensions": {"country": "India", "category": "2nd"},
                "publication_date": date(2024, 7, 1),
            },
        ]
        snapshot = build_virtual_queue_snapshot(date(2024, 8, 1), facts, visa_class="2nd", country="India")
        assert snapshot.get_total_demand() == 800
        assert snapshot.get_demand_between(date(2023, 4, 1), date(2023, 4, 30)) == 800


class TestRunMonthlyLoop:
    """Tests for solver monthly loop."""

    def test_yields_results_until_supply_consumed(self):
        snapshot = VirtualQueueSnapshot()
        snapshot.add(date(2023, 1, 1), 700)
        snapshot.add(date(2023, 2, 1), 700)
        results = list(
            run_monthly_loop(
                snapshot,
                current_cutoff=date(2022, 6, 1),
                monthly_supply=700,
                start_month=date(2024, 2, 1),
                max_months=5,
            )
        )
        assert len(results) >= 1
        assert results[0].month == date(2024, 2, 1)
        assert results[0].consumed == 700
        assert results[0].cutoff_date == date(2023, 1, 1)

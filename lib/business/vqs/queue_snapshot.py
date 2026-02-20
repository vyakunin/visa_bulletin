"""Virtual queue snapshot for VQS.

Histogram of applicants waiting, binned by priority date (e.g. by month).
Used by the solver to consume demand from the head of the queue.
"""

from collections import defaultdict
from datetime import date


class VirtualQueueSnapshot:
    """
    Snapshot of the virtual queue: demand (applicants) binned by priority date.

    Buckets are keyed by the first day of the month (or day) for that priority date.
    """

    def __init__(self) -> None:
        self._buckets: dict[date, int] = defaultdict(int)

    def add(self, bucket_date: date, count: int) -> None:
        """Add count to the bucket for the given priority date (month)."""
        # Normalize to first of month for consistent bucketing
        key = date(bucket_date.year, bucket_date.month, 1)
        self._buckets[key] += count

    def get_bucket(self, bucket_date: date) -> int:
        """Return demand count for the given priority-date month (0 if empty)."""
        key = date(bucket_date.year, bucket_date.month, 1)
        return self._buckets.get(key, 0)

    def get_demand_between(self, from_date: date, to_date: date) -> int:
        """Return total demand (applicants) in buckets between from_date and to_date (inclusive)."""
        total = 0
        from_first = date(from_date.year, from_date.month, 1)
        to_first = date(to_date.year, to_date.month, 1)
        for d, count in self._buckets.items():
            if from_first <= d <= to_first:
                total += count
        return total

    def get_total_demand(self) -> int:
        """Return total demand across all buckets."""
        return sum(self._buckets.values())

    def advance_cutoff(
        self, current_cutoff: date, supply: int
    ) -> tuple[date | None, int]:
        """
        Consume up to supply applicants from the head of the queue (starting at current_cutoff).
        Deducts consumed amounts from buckets so the next month does not double-count.

        Returns (new_cutoff_date, consumed). new_cutoff_date is the first day of the month
        such that everyone with PD before that month has been processed (or None if queue
        exhausted before consuming supply). consumed is the number actually consumed.
        """
        consumed = 0
        cursor = date(current_cutoff.year, current_cutoff.month, 1)
        sorted_dates = sorted(self._buckets.keys())
        for d in sorted_dates:
            if d < cursor:
                continue
            if consumed >= supply:
                return (cursor, consumed)
            available = self._buckets[d]
            take = min(available, supply - consumed)
            consumed += take
            self._buckets[d] -= take
            if self._buckets[d] <= 0:
                del self._buckets[d]
            cursor = d
            if consumed >= supply:
                return (cursor, consumed)
        if consumed > 0:
            return (cursor, consumed)
        return (None, 0)

    def scale_remaining_by(self, lambda_: float) -> None:
        """
        Multiply all bucket counts by lambda_ (attrition/retention).
        Use after each month in the solver when Model B is enabled (e.g. λ=0.995).
        """
        if lambda_ <= 0 or lambda_ >= 1.0:
            return
        for d in list(self._buckets.keys()):
            self._buckets[d] = max(0, int(self._buckets[d] * lambda_))
            if self._buckets[d] <= 0:
                del self._buckets[d]

"""Cache behaviour of the Wayback CDX client.

The cache is an optimisation over a heavily rate-limited third-party API, so a
cache problem must never cost us a response we already paid for. Regression for
2026-07-18: the backfill ran against a docker-cp'd cache dir owned by another
uid, and every uncached lookup threw ``PermissionError`` *after* a successful
fetch — the archive data was discarded and the bulletin row left NULL.
"""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from lib.business.bulletin import wayback

URL = "https://travel.state.gov/.../visa-bulletin-for-august-2025.html"
ROWS = ["20250715120000", "20250716120000"]


class TestCacheIsBestEffort(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.cache = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_unwritable_cache_still_returns_the_fetched_history(self):
        """A read-only cache dir must degrade to "no caching", not lose the data."""
        with mock.patch.object(wayback, "_query_cdx", return_value=ROWS) as q:
            with mock.patch.object(Path, "write_text", side_effect=PermissionError(13, "denied")):
                history = wayback.fetch_captures(URL, cache_dir=self.cache)
        q.assert_called_once()
        self.assertEqual(history.first_capture, datetime(2025, 7, 15, 12, 0))
        self.assertEqual(history.capture_gap_days, 1)

    def test_corrupt_cache_entry_falls_back_to_a_fresh_query(self):
        path = self.cache / "visa-bulletin-for-august-2025.html.cdx.json"
        path.write_text("{truncated")
        with mock.patch.object(wayback, "_query_cdx", return_value=ROWS) as q:
            history = wayback.fetch_captures(URL, cache_dir=self.cache)
        q.assert_called_once()
        self.assertEqual(history.first_capture, datetime(2025, 7, 15, 12, 0))

    def test_a_good_cache_entry_avoids_the_network(self):
        path = self.cache / "visa-bulletin-for-august-2025.html.cdx.json"
        path.write_text(json.dumps(ROWS))
        with mock.patch.object(wayback, "_query_cdx") as q:
            history = wayback.fetch_captures(URL, cache_dir=self.cache)
        q.assert_not_called()
        self.assertEqual(history.first_capture, datetime(2025, 7, 15, 12, 0))

    def test_never_archived_url_is_cached_as_empty(self):
        """An unarchived bulletin must not be re-queried on every run."""
        with mock.patch.object(wayback, "_query_cdx", return_value=[]) as q:
            first = wayback.fetch_captures(URL, cache_dir=self.cache)
            second = wayback.fetch_captures(URL, cache_dir=self.cache)
        q.assert_called_once()
        self.assertIsNone(first.first_capture)
        self.assertIsNone(second.first_capture)

    def test_unparseable_timestamp_is_skipped_not_fatal(self):
        with mock.patch.object(wayback, "_query_cdx", return_value=["nonsense", ROWS[0]]):
            history = wayback.fetch_captures(URL, cache_dir=self.cache)
        self.assertEqual(history.captures, (datetime(2025, 7, 15, 12, 0),))
        self.assertIsNone(history.capture_gap_days)  # single capture -> no gap


if __name__ == "__main__":
    unittest.main()

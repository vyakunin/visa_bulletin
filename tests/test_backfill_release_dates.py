"""The release-date backfill never turns our own ingest time into a release date."""

from datetime import UTC, date, datetime
from unittest import mock

import pytest

import scripts.bulletin.backfill_release_dates as backfill
from models.bulletin import Bulletin

SEP_2026 = date(2026, 9, 1)


def _run(tmp_path, *, refresh: bool) -> None:
    with mock.patch.object(backfill, "first_capture_date", return_value=(None, None)):
        backfill.backfill(dry_run=False, since=None, refresh=refresh, cache_dir=tmp_path, limit=None)


@pytest.mark.django_db
def test_ingest_time_is_not_written_as_a_release_date(tmp_path):
    """Sep 2026 was ingested 02:30 UTC Aug 22 — a plausible lead, and a Saturday."""
    b = Bulletin.objects.create(publication_date=SEP_2026)
    Bulletin.objects.filter(pk=b.pk).update(fetched_at=datetime(2026, 8, 22, 2, 30, tzinfo=UTC))
    _run(tmp_path, refresh=False)
    assert Bulletin.objects.get(pk=b.pk).released_on is None


@pytest.mark.django_db
def test_refresh_keeps_a_bridge_recorded_release(tmp_path):
    b = Bulletin.objects.create(publication_date=SEP_2026)
    Bulletin.objects.filter(pk=b.pk).update(
        released_on=date(2026, 8, 21), released_on_source=Bulletin.SOURCE_LIVE
    )
    _run(tmp_path, refresh=True)
    got = Bulletin.objects.get(pk=b.pk)
    assert (got.released_on, got.released_on_source) == (date(2026, 8, 21), Bulletin.SOURCE_LIVE)

"""refresh_bulletin turns a bridge-observed release bracket into ``Bulletin.released_on``."""

from datetime import UTC, date, datetime, timedelta

import pytest

import scripts.cron.refresh_bulletin as rb
from lib.business.bulletin.release_bracket import (
    RELEASE_OBSERVATIONS_FILENAME,
    ReleaseBracket,
    dump_brackets,
)
from lib.utils.http_utils import BULLETIN_HTML_CACHE_DIR_ENV
from models.bulletin import Bulletin

SEP_2026 = date(2026, 9, 1)
# The September 2026 bulletin's real bracket: absent at 22:00 ET, listed at 22:30 ET.
SEP_BRACKET = ReleaseBracket(
    datetime(2026, 8, 22, 2, 0, tzinfo=UTC), datetime(2026, 8, 22, 2, 30, tzinfo=UTC)
)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(BULLETIN_HTML_CACHE_DIR_ENV, str(tmp_path))
    return tmp_path


def _observe(cache_dir, brackets: dict[date, ReleaseBracket]) -> None:
    dump_brackets(brackets, cache_dir / RELEASE_OBSERVATIONS_FILENAME)


@pytest.mark.django_db
def test_tight_bracket_records_the_eastern_release_date(cache_dir):
    Bulletin.objects.create(publication_date=SEP_2026)
    _observe(cache_dir, {SEP_2026: SEP_BRACKET})

    assert rb.record_observed_release_dates() == 1
    b = Bulletin.objects.get(publication_date=SEP_2026)
    assert b.released_on == date(2026, 8, 21)  # Friday in Washington, Saturday in UTC
    assert b.released_on_source == Bulletin.SOURCE_LIVE


@pytest.mark.django_db
def test_wide_bracket_records_nothing(cache_dir):
    Bulletin.objects.create(publication_date=SEP_2026)
    present = SEP_BRACKET.first_present_at
    _observe(
        cache_dir,
        {SEP_2026: ReleaseBracket(present - timedelta(hours=24, seconds=1), present)},
    )

    assert rb.record_observed_release_dates() == 0
    assert Bulletin.objects.get(publication_date=SEP_2026).released_on is None


@pytest.mark.django_db
def test_recorded_date_is_never_overwritten(cache_dir):
    b = Bulletin.objects.create(publication_date=SEP_2026)
    Bulletin.objects.filter(pk=b.pk).update(
        released_on=date(2026, 8, 20), released_on_source=Bulletin.SOURCE_WAYBACK
    )
    _observe(cache_dir, {SEP_2026: SEP_BRACKET})

    assert rb.record_observed_release_dates() == 0
    assert Bulletin.objects.get(pk=b.pk).released_on == date(2026, 8, 20)


@pytest.mark.django_db
def test_no_cache_dir_records_nothing(monkeypatch):
    monkeypatch.delenv(BULLETIN_HTML_CACHE_DIR_ENV, raising=False)
    Bulletin.objects.create(publication_date=SEP_2026)
    assert rb.record_observed_release_dates() == 0


@pytest.mark.django_db
def test_cache_without_observations_records_nothing(cache_dir):
    Bulletin.objects.create(publication_date=SEP_2026)
    assert rb.record_observed_release_dates() == 0


@pytest.mark.django_db
def test_bridge_log_correction_sets_the_observed_dates_once():
    from scripts.oneoff.correct_bridge_release_dates import correct

    for month in (date(2026, 8, 1), SEP_2026, date(2026, 10, 1)):
        Bulletin.objects.create(publication_date=month)
    kept = Bulletin.objects.get(publication_date=date(2026, 10, 1))
    Bulletin.objects.filter(pk=kept.pk).update(
        released_on=date(2026, 9, 28), released_on_source=Bulletin.SOURCE_WAYBACK
    )

    correct(dry_run=True)
    assert Bulletin.objects.filter(publication_date=SEP_2026, released_on__isnull=True).exists()

    correct(dry_run=False)
    correct(dry_run=False)
    got = dict(Bulletin.objects.values_list("publication_date", "released_on"))
    assert got[date(2026, 8, 1)] == date(2026, 7, 20)  # Monday, 12:00-12:30 ET
    assert got[SEP_2026] == date(2026, 8, 21)  # Friday, 22:00-22:30 ET
    assert got[date(2026, 10, 1)] == date(2026, 9, 28)  # an existing value is left alone

"""The release window the bridge observes, and the release date it supports."""

from datetime import UTC, date, datetime, timedelta

from lib.business.bulletin.release_bracket import (
    MAX_RELEASE_BRACKET,
    ReleaseBracket,
    dump_brackets,
    load_brackets,
    observe,
    release_date_of,
)

SEP_2026 = date(2026, 9, 1)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_release_date_is_read_in_eastern_time():
    """The September 2026 bulletin appeared at 02:30 UTC on Aug 22 — Friday Aug 21 in
    Washington. Read in UTC it renders as a Saturday release."""
    assert release_date_of(_utc(2026, 8, 22, 2, 30)) == date(2026, 8, 21)


def test_naive_moment_is_utc():
    assert release_date_of(datetime(2026, 8, 22, 2, 30)) == date(2026, 8, 21)


def test_tight_bracket_supports_its_eastern_date():
    bracket = ReleaseBracket(_utc(2026, 8, 22, 2, 0), _utc(2026, 8, 22, 2, 30))
    assert bracket.release_date() == date(2026, 8, 21)


def test_bracket_exactly_at_the_limit_is_accepted():
    present = _utc(2026, 8, 22, 2, 30)
    assert ReleaseBracket(present - MAX_RELEASE_BRACKET, present).release_date() == date(2026, 8, 21)


def test_bracket_past_the_limit_supports_nothing():
    """A failure streak (or a bridge that started after the release) leaves the
    window too wide to name a day; unknown must stay unknown."""
    present = _utc(2026, 8, 22, 2, 30)
    late = ReleaseBracket(present - MAX_RELEASE_BRACKET - timedelta(seconds=1), present)
    assert late.release_date() is None


def test_open_bracket_supports_nothing():
    assert ReleaseBracket(None, _utc(2026, 8, 22, 2, 30)).release_date() is None
    assert ReleaseBracket(_utc(2026, 8, 22, 2, 0), None).release_date() is None


def test_observe_closes_the_bracket_once():
    brackets: dict[date, ReleaseBracket] = {}
    observe(brackets, SEP_2026, False, _utc(2026, 8, 22, 1, 30))
    observe(brackets, SEP_2026, False, _utc(2026, 8, 22, 2, 0))
    observe(brackets, SEP_2026, True, _utc(2026, 8, 22, 2, 30))
    # A later poll — present or flaky-absent — must not move a closed bracket.
    observe(brackets, SEP_2026, True, _utc(2026, 8, 22, 3, 0))
    observe(brackets, SEP_2026, False, _utc(2026, 8, 22, 3, 30))
    assert brackets[SEP_2026] == ReleaseBracket(_utc(2026, 8, 22, 2, 0), _utc(2026, 8, 22, 2, 30))


def test_first_sighting_without_a_prior_absence_stays_open():
    """Months already published when the bridge started have no lower bound."""
    brackets: dict[date, ReleaseBracket] = {}
    observe(brackets, SEP_2026, True, _utc(2026, 8, 22, 2, 30))
    assert brackets[SEP_2026].release_date() is None


def test_brackets_round_trip(tmp_path):
    path = tmp_path / "brackets.json"
    brackets = {
        SEP_2026: ReleaseBracket(_utc(2026, 8, 22, 2, 0), _utc(2026, 8, 22, 2, 30)),
        date(2026, 10, 1): ReleaseBracket(_utc(2026, 9, 29, 10, 30), None),
    }
    dump_brackets(brackets, path)
    assert load_brackets(path) == brackets


def test_missing_state_file_loads_empty(tmp_path):
    assert load_brackets(tmp_path / "absent.json") == {}

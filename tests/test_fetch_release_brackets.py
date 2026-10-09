"""The browser fetcher carries release brackets across polls and hands them to the ingest."""

import importlib.util
from datetime import date
from pathlib import Path

from lib.business.bulletin.release_bracket import (
    RELEASE_OBSERVATIONS_FILENAME,
    load_brackets,
)

_FETCHER = Path(__file__).resolve().parent.parent / "scripts/fetch_bulletin_via_browser.py"


def _fetcher():
    spec = importlib.util.spec_from_file_location("fetch_bulletin_via_browser", _FETCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bracket_closes_across_two_polls(tmp_path):
    fetcher = _fetcher()
    state = tmp_path / "state" / "release_brackets.json"
    months = ["2026-08", "2026-09"]
    august_only = {"visa-bulletin-for-august-2026.html"}
    both = august_only | {"visa-bulletin-for-september-2026.html"}

    first_cache = tmp_path / "poll1"
    first_cache.mkdir()
    fetcher._record_brackets(state, first_cache, months, august_only)
    second_cache = tmp_path / "poll2"
    second_cache.mkdir()
    fetcher._record_brackets(state, second_cache, months, both)

    handed_over = load_brackets(second_cache / RELEASE_OBSERVATIONS_FILENAME)
    sep = handed_over[date(2026, 9, 1)]
    assert sep.last_absent_at is not None and sep.first_present_at is not None
    assert sep.release_date() is not None
    # August was already listed on the first poll: no lower bound, so no date.
    assert handed_over[date(2026, 8, 1)].release_date() is None
    assert load_brackets(state) == handed_over

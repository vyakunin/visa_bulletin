"""Regression: browser-fetched HTML cache feeds the Akamai-walled bulletin ingest.

travel.state.gov 403s every non-browser client (Akamai). The fix pre-places
browser-fetched HTML in BULLETIN_HTML_CACHE_DIR; fetch_page (index) and the plugin
download (bulletin pages) must read that cache instead of the network. Without the
cache env set, both must behave exactly as before (network path). These tests pin
that fallback so a refactor can't silently re-break the ingest.
"""

from unittest.mock import patch

from lib.utils.http_utils import bulletin_cache_file, fetch_page

_INDEX_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
_BULLETIN_URL = (
    "https://travel.state.gov/content/travel/en/legal/visa-law0/"
    "visa-bulletin/2026/visa-bulletin-for-july-2026.html"
)


def test_cache_file_none_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("BULLETIN_HTML_CACHE_DIR", raising=False)
    assert bulletin_cache_file(_INDEX_URL) is None


def test_cache_file_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLETIN_HTML_CACHE_DIR", str(tmp_path))
    assert bulletin_cache_file(_INDEX_URL) is None  # dir set but file absent


def test_cache_file_matches_by_url_basename(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLETIN_HTML_CACHE_DIR", str(tmp_path))
    (tmp_path / "visa-bulletin.html").write_text("<html>index</html>")
    (tmp_path / "visa-bulletin-for-july-2026.html").write_text("<html>july</html>")
    assert bulletin_cache_file(_INDEX_URL) == tmp_path / "visa-bulletin.html"
    assert bulletin_cache_file(_BULLETIN_URL) == tmp_path / "visa-bulletin-for-july-2026.html"


def test_fetch_page_reads_cache_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLETIN_HTML_CACHE_DIR", str(tmp_path))
    (tmp_path / "visa-bulletin.html").write_text("<html>CACHED INDEX</html>")
    # If the cache is honored, requests.get must never be called.
    with patch("lib.utils.http_utils.requests.get") as mock_get:
        html = fetch_page(_INDEX_URL)
    assert html == "<html>CACHED INDEX</html>"
    mock_get.assert_not_called()


def test_fetch_page_falls_back_to_network_when_no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLETIN_HTML_CACHE_DIR", str(tmp_path))  # dir set, file absent
    with patch("lib.utils.http_utils.requests.get") as mock_get:
        mock_get.return_value.text = "<html>NET</html>"
        mock_get.return_value.raise_for_status.return_value = None
        html = fetch_page(_INDEX_URL)
    assert html == "<html>NET</html>"
    mock_get.assert_called_once()

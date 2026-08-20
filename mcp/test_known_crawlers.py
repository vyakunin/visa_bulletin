"""The digest's declared-crawler allowlist, run through the real awk.

Two lists govern a declared crawler and they have to agree: nginx's `$bot_key`
map decides who gets THROTTLED, this one decides who the digest reports as a
crawler instead of as a client IP worth flagging. This one was hand-typed inside
the awk and drifted to about half the throttle map, so OpenAI's OAI-SearchBot —
throttled by nginx, and announcing itself in every UA — was unknown here, and
its five /16 neighbours (~2.5k req/24h, 2,172 on /employer/ and 1,930 on
/job-title/) rendered as the top five "real" client IPs in the morning digest.

The failure is silent by construction: an unrecognised crawler looks exactly
like a scraper worth chasing. So these run the GENERATED program through the
same awk the homeserver runs and read the buckets it emits.

Run: `uv run pytest test_known_crawlers.py` from this dir (the module needs
httpx/mcp, so it is not a bazel target — same convention as the sibling tests).
"""

import shutil
import subprocess

import daily_checkup_server as m
import pytest

_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Verbatim from the prod log, 2026-08-20: the token is appended to a full Chrome
# UA, which is why "looks like a browser" is not a usable test.
_OAI = f"{_CHROME}; compatible; OAI-SearchBot/1.4; +https://openai.com/searchbot"


def _line(ip: str, path: str, ua: str, status: str = "200") -> str:
    return (
        f'{ip} - - [20/Aug/2026:14:20:49 +0000] "GET {path} HTTP/1.1" '
        f'{status} 75187 0.176 "https://visa-bulletin.us/" "{ua}"'
    )


def _awk_bin() -> str:
    for candidate in ("mawk", "gawk", "awk"):
        found = shutil.which(candidate)
        if found:
            return found
    pytest.skip("no awk binary available")


def _reduce(lines: list[str]) -> dict:
    res = subprocess.run(
        [_awk_bin(), m._nginx_awk_program()],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    out: dict = {"ip": {}, "botip": {}}
    for row in res.stdout.splitlines():
        key, _, val = row.partition("=")
        if key in ("ip", "botip"):
            addr, _, count = val.partition("|")
            out[key][addr] = int(count)
        elif val.isdigit():
            out[key] = int(val)
    return out


def test_oai_searchbot_is_a_crawler_not_a_client_ip():
    """The reported defect: five OpenAI /16s at the top of 'real client IPs'."""
    got = _reduce([_line("74.7.243.18", "/employer/some-employer/", _OAI)])
    assert got["botip"] == {"74.7.243.18": 1}
    assert got["ip"] == {}, "an OpenAI crawler IP must never read as a client to chase"
    assert got["page_hits_bot"] == 1
    assert got["page_hits_human"] == 0


def test_a_crawler_that_never_says_bot_is_still_not_human():
    """anthropic-ai / meta-externalagent / ia_archiver carry no "bot" token, so
    the UA heuristic alone files them as human. The allowlist is what catches
    them, which is why is_bot ORs it in."""
    for ua in ("anthropic-ai", "meta-externalagent/1.1", "ia_archiver"):
        got = _reduce([_line("203.0.113.7", "/job-title/x/", f"{_CHROME} ({ua})")])
        assert got["page_hits_human"] == 0, ua
        assert got["botip"] == {"203.0.113.7": 1}, ua


def test_a_real_browser_is_still_a_human_client_ip():
    """The over-reach side: widening the allowlist must not eat real traffic."""
    got = _reduce([_line("198.51.100.4", "/employment-based/india/", _CHROME)])
    assert got["page_hits_human"] == 1
    assert got["page_hits_bot"] == 0
    assert got["ip"] == {"198.51.100.4": 1}
    assert got["botip"] == {}


def test_a_publisher_subnet_counts_even_under_a_browser_ua():
    got = _reduce([_line("66.249.66.1", "/", _CHROME)])
    assert got["botip"] == {"66.249.66.1": 1}
    assert got["page_hits_human"] == 0


def test_an_undeclared_scraper_still_reaches_the_flagged_bucket():
    got = _reduce([_line("192.0.2.9", "/salaries/", "python-requests/2.31.0")])
    assert got["ip"] == {"192.0.2.9": 1}
    assert got["botip"] == {}
    assert got["page_hits_bot"] == 1


def test_every_token_is_lowercase_and_awk_safe():
    """The generator rejects a token that would break the regex literal or the
    single-quoted shell string the program rides in — pin that it still does."""
    m._awk_known_crawler_test()  # the live list must pass
    original = m.KNOWN_CRAWLER_UA_TOKENS
    for bad in ("Googlebot", "some/bot", "bot'x", "a|b"):
        m.KNOWN_CRAWLER_UA_TOKENS = original + (bad,)
        try:
            with pytest.raises(ValueError):
                m._awk_known_crawler_test()
        finally:
            m.KNOWN_CRAWLER_UA_TOKENS = original

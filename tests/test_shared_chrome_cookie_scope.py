"""Static guard: never clear cookies unscoped on the SHARED debug Chrome profile.

`fetch_bulletin_via_browser.py` attaches to the box's debug Chrome (:9222) over CDP
to get past travel.state.gov's Akamai wall, and sheds a poisoned `_abck` cookie first.
That profile is shared infrastructure: it carries the logged-in Google, Reddit
(reddit_post MCP), AdSense and LinkedIn sessions. A bare `ctx.clear_cookies()` wipes
ALL of them — and this fetcher runs unattended on a 4-hourly cron, so an unscoped
clear is a recurring, silent sign-out of every other automation on the box
(the failure class ~/.claude/rules/mcps.md already records for this profile).

The clear must therefore always carry a `domain=` filter. This asserts that guard
stays wired — a bare re-introduction is a one-word edit that no functional test of
the fetcher would fail on, because clearing too much still fetches the bulletin fine.

What this CANNOT verify (only a live run can): that the scoped clear still sheds
enough state to beat the wall. That is the end-state check — run the fetcher and
confirm `index_ok: true` plus surviving Google/Reddit cookies.
"""

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_FETCHER = _REPO / "scripts/fetch_bulletin_via_browser.py"


def _clear_cookies_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "clear_cookies"
    ]


def test_fetcher_never_clears_cookies_unscoped() -> None:
    """Every clear_cookies() in the fetcher passes a domain= filter."""
    tree = ast.parse(_FETCHER.read_text(encoding="utf-8"))
    calls = _clear_cookies_calls(tree)

    assert calls, (
        "Expected at least one clear_cookies() call in "
        f"{_FETCHER.name} — if the Akamai cookie-shedding moved, update this guard."
    )
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords}
        assert "domain" in kwargs, (
            f"{_FETCHER.name}:{call.lineno} calls clear_cookies() without domain=. "
            "This runs against the SHARED debug Chrome profile, so an unscoped clear "
            "signs the box out of Google/Reddit/AdSense/LinkedIn on every cron run. "
            "Scope it to the travel.state.gov domains (AKAMAI_COOKIE_DOMAINS)."
        )


def test_akamai_cookie_domains_stay_scoped_to_state_dept() -> None:
    """The cleared domains are travel.state.gov only — never a broad/empty target."""
    import sys

    sys.path.insert(0, str(_REPO / "scripts"))
    tree = ast.parse(_FETCHER.read_text(encoding="utf-8"))
    domains: tuple[str, ...] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "AKAMAI_COOKIE_DOMAINS" for t in node.targets
        ):
            domains = tuple(ast.literal_eval(node.value))

    assert domains, "AKAMAI_COOKIE_DOMAINS not found — the cookie-clear scope must stay explicit."
    for domain in domains:
        assert domain.lstrip(".").endswith("travel.state.gov"), (
            f"AKAMAI_COOKIE_DOMAINS contains {domain!r}, which is not a travel.state.gov "
            "domain. Widening this scope clears other automations' sessions."
        )

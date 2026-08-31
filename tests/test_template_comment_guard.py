"""Static guard: no template comment can reach a rendered page.

Django's `{# #}` is SINGLE-LINE ONLY. A `{# ... #}` whose body spans a newline is
not parsed as a comment at all — the tag ends at the first newline and everything
inside is emitted verbatim into the response as body text. Multi-line commentary
needs `{% comment %}` / `{% endcomment %}`.

Four such comments shipped in `e79727f` and served raw template source on
~11.5k sitemapped /employer/, /job-title/ and /salaries/ URLs for twelve days,
one of them publishing an internal repo path as visible page copy. This closes
the class rather than those four sites: any future multi-line `{# #}` fails here.

Scanning the templates beats asserting on a rendered response, because it covers
every template including the ones no rendering test exercises.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TEMPLATE_ROOTS = ("webapp/templates",)
_SKIP_DIRS = {"node_modules", "staticfiles", ".git", "__pycache__"}


def _templates() -> list[Path]:
    found: list[Path] = []
    for root in _TEMPLATE_ROOTS:
        for path in sorted((_REPO / root).rglob("*.html")):
            if _SKIP_DIRS.isdisjoint(path.parts):
                found.append(path)
    return found


def _leaking_comments(source: str) -> list[tuple[int, str]]:
    """Line numbers of `{#` openers Django will NOT strip, with the reason."""
    leaks = []
    for opener in re.finditer(r"\{#", source):
        line = source.count("\n", 0, opener.start()) + 1
        close = source.find("#}", opener.end())
        if close == -1:
            leaks.append((line, "unclosed"))
        elif "\n" in source[opener.end() : close]:
            leaks.append((line, "spans a newline"))
    return leaks


def test_templates_exist():
    """A scan over zero files passes vacuously — assert the corpus is real."""
    assert len(_templates()) > 20


def test_no_template_comment_reaches_the_page():
    offenders = []
    for path in _templates():
        for line, why in _leaking_comments(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(_REPO)}:{line} ({why})")
    assert not offenders, (
        "`{# #}` is single-line only — these are rendered as visible body text:\n  "
        + "\n  ".join(offenders)
        + "\nUse {% comment %} / {% endcomment %} for multi-line commentary."
    )

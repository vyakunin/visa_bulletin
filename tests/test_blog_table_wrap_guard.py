"""Static guard: blog/analysis pages must not break numbers/%/codes mid-token.

`.blog-content` carries Bootstrap's `.text-break` (`word-break: break-word
!important`), which breaks single tokens mid-character inside narrow table columns
on mobile ("34.9%" -> "34." / "9%", "FY21" -> "FY2" / "1"). Every /analysis/ post
renders through `blog/post_detail.html`, so the fix lives there once. This asserts
that guard stays wired — a cheap static check that a `bazel test` catches if the
rule is removed or the template is rewritten without it.

What this CANNOT verify (a real browser can): that the CSS actually wins the
cascade at a given viewport. That is the computed-style check (Playwright at
mobile width) documented in .claude/rules/blog_content_html.md.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TEMPLATE = _REPO / "webapp/templates/blog/post_detail.html"
_I129_GENERATOR = _REPO / "scripts/oneoff/generate_i129_story_posts.py"

# Editorial / internal-process voice that must not reach the published /analysis/ copy
# (see .claude/rules/blog_content_html.md Trap 2). These are the mechanically-detectable
# tells; the semantic "does the lead establish the claim it counters" judgment is NOT
# statically checkable and stays a human/LLM review step.
_EDITORIAL_VOICE_TELLS = (
    "Mandatory caveats",
    "and we say so",
    "we flag",
    "Lead with the",
    "read it correctly",
    "read them correctly",
    "on the page)",  # draft meta like "caveats (on the page)"
)


def _blog_content_wraps_table_cells_normally(css_source: str) -> bool:
    """True if a rule resets word-break to normal on .blog-content table cells."""
    return bool(
        re.search(
            r"\.blog-content\s+table[^{]*\{[^}]*word-break:\s*normal",
            css_source,
        )
    )


def test_post_detail_neutralizes_text_break_on_tables():
    src = _TEMPLATE.read_text(encoding="utf-8")
    assert _blog_content_wraps_table_cells_normally(src), (
        "post_detail.html must reset word-break to normal on .blog-content table "
        "cells, or numbers/%/FY-codes break mid-token on mobile (see "
        ".claude/rules/blog_content_html.md)."
    )


def test_i129_stories_have_no_editorial_voice():
    """Catch the mechanical 'internal discussion leaked into publication' tells."""
    src = _I129_GENERATOR.read_text(encoding="utf-8")
    hits = [tell for tell in _EDITORIAL_VOICE_TELLS if tell in src]
    assert not hits, (
        f"editorial/internal-process voice found in published /analysis/ copy: {hits}. "
        "Write caveats and headings TO the reader (see .claude/rules/blog_content_html.md)."
    )

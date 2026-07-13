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

_TEMPLATE = Path(__file__).resolve().parent.parent / "webapp/templates/blog/post_detail.html"


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

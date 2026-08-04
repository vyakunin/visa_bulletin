"""`_text_excerpt` builds the meta description — it must not emit code as prose.

The excerpt feeds `<meta name="description">`, `og:description`, `twitter:description`
and the JSON-LD `BlogPosting.description` (webapp/views/blog_views.py). Stripping tags
alone leaves the BODY of a `<style>` element behind, and the /analysis/ data stories
prepend one on purpose — the mobile table-wrap guard that keeps `34.9%` from breaking
mid-token on a phone (.claude/rules/blog_content_html.md Trap 1). The result was a
description that opened with ~120 characters of CSS before the first real word, on all
three story pages, in every SERP snippet and social unfurl.

The bug is invisible to a rendering test: the page looks perfect, because the corruption
lives only in the head metadata.
"""

from tests.django_setup import setup_django_for_tests

# blog_views imports models.blog at module scope, so the app registry has to be up
# before the import below. django_py_test does not ship tests/conftest.py into the
# runfiles, so the bootstrap conftest would normally do is done here explicitly.
setup_django_for_tests()

from webapp.views.blog_views import _text_excerpt  # noqa: E402

_TABLE_STYLE = (
    "<style>.blog-content table td,.blog-content table th"
    "{overflow-wrap:normal!important;word-break:normal!important;}</style>"
)


def test_style_block_contents_are_not_in_the_excerpt():
    """A leading <style> block contributes nothing — not its tags, not its CSS."""
    html = _TABLE_STYLE + "<p>In 2024, Bloomberg revealed that thousands of companies…</p>"
    out = _text_excerpt(html)
    assert out.startswith("In 2024, Bloomberg"), out
    for token in ("blog-content", "overflow-wrap", "word-break", "!important", "{", "}"):
        assert token not in out, f"CSS token {token!r} leaked into the meta description: {out!r}"


def test_script_block_contents_are_not_in_the_excerpt():
    """Same for <script> — a Plotly payload would otherwise become the description."""
    html = '<script type="application/json">{"x":[1,2,3],"type":"scatter"}</script><p>Real prose.</p>'
    out = _text_excerpt(html)
    assert out == "Real prose."


def test_prose_is_still_extracted_and_truncated():
    """The ordinary path is unchanged: tags out, whitespace collapsed, ellipsis at the cap."""
    assert _text_excerpt("<p>Hello   <b>world</b></p>") == "Hello world"
    long_out = _text_excerpt("<p>" + "word " * 200 + "</p>")
    assert len(long_out) <= 200
    assert long_out.endswith("…")


def test_uppercase_and_attributed_style_tags_are_handled():
    """Case and attributes must not let a code element through."""
    html = '<STYLE media="screen">.a{color:red}</STYLE><p>Body text.</p>'
    assert _text_excerpt(html) == "Body text."

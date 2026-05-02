import json
import re

from django.shortcuts import get_object_or_404, render
from django.templatetags.static import static

from models.blog import BlogPost

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text_excerpt(html: str, max_len: int = 200) -> str:
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0] + "…"


def blog_list(request):
    """List all published blog posts."""
    posts = BlogPost.objects.filter(is_published=True).order_by("-published_date")
    structured_data = {
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": "U.S. Immigration Data — Analysis",
        "url": request.build_absolute_uri(),
        "description": (
            "Monthly analysis of U.S. visa bulletin movement, priority date "
            "predictions, and immigration trends."
        ),
        "blogPost": [
            {
                "@type": "BlogPosting",
                "headline": p.title,
                "url": request.build_absolute_uri(f"/analysis/{p.slug}/"),
                "datePublished": p.published_date.isoformat(),
                "articleSection": p.category,
            }
            for p in posts[:20]
        ],
    }
    return render(
        request,
        "blog/post_list.html",
        {
            "posts": posts,
            "page_title": "Visa Bulletin Analysis — Monthly Updates",
            "page_description": (
                "Monthly analysis of visa bulletin movement for EB-1, EB-2, EB-3 "
                "and family-sponsored categories. Priority date predictions and trends."
            ),
            "structured_data": json.dumps(structured_data),
        },
    )


def blog_detail(request, slug):
    """View a single blog post."""
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    related_posts = (
        BlogPost.objects.filter(is_published=True)
        .exclude(slug=slug)
        .order_by("-published_date")[:3]
    )
    canonical_url = request.build_absolute_uri(f"/analysis/{post.slug}/")
    site_logo = request.build_absolute_uri(static("og-image.png"))
    description = _text_excerpt(post.content)
    structured_data = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "description": description,
        "datePublished": post.published_date.isoformat(),
        "dateModified": post.published_date.isoformat(),
        "articleSection": post.category,
        "author": {
            "@type": "Person",
            "name": "Vlad Yakunin",
            "url": "https://github.com/vyakunin",
        },
        "publisher": {
            "@type": "Organization",
            "name": "U.S. Immigration Data",
            "url": "https://visa-bulletin.us",
            "logo": {"@type": "ImageObject", "url": site_logo},
        },
        "image": site_logo,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical_url},
        "url": canonical_url,
        "inLanguage": "en-US",
    }
    return render(
        request,
        "blog/post_detail.html",
        {
            "post": post,
            "related_posts": related_posts,
            "page_title": post.title,
            "page_description": description,
            "structured_data": json.dumps(structured_data),
            "canonical_url": canonical_url,
            "og_type": "article",
        },
    )

from django.shortcuts import get_object_or_404, render

from models.blog import BlogPost


def blog_list(request):
    """List all published blog posts."""
    posts = BlogPost.objects.filter(is_published=True).order_by("-published_date")
    return render(request, "blog/post_list.html", {"posts": posts})


def blog_detail(request, slug):
    """View a single blog post."""
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    related_posts = (
        BlogPost.objects.filter(is_published=True)
        .exclude(slug=slug)
        .order_by("-published_date")[:3]
    )
    return render(request, "blog/post_detail.html", {"post": post, "related_posts": related_posts})

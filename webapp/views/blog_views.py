from django.shortcuts import render, get_object_or_404
from models.blog import BlogPost

def blog_list(request):
    """List all published blog posts."""
    posts = BlogPost.objects.filter(is_published=True).order_by("-published_date")
    return render(request, "blog/post_list.html", {"posts": posts})

def blog_detail(request, slug):
    """View a single blog post."""
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    return render(request, "blog/post_detail.html", {"post": post})

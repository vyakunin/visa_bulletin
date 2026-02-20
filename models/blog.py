from django.db import models
from django.utils.text import slugify


class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=200)
    content = models.TextField(help_text="HTML or Markdown content")
    published_date = models.DateField(auto_now_add=True)
    is_published = models.BooleanField(default=False)
    category = models.CharField(max_length=50, default="Analysis")
    related_bulletin = models.ForeignKey(
        "models.Bulletin",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts",
    )

    class Meta:
        ordering = ["-published_date"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

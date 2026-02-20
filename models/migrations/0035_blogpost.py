import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0034_predictedbulletin_predictedcutoff_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlogPost",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=200, unique=True)),
                ("content", models.TextField(help_text="HTML or Markdown content")),
                ("published_date", models.DateField(auto_now_add=True)),
                ("is_published", models.BooleanField(default=False)),
                ("category", models.CharField(default="Analysis", max_length=50)),
                (
                    "related_bulletin",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="blog_posts",
                        to="models.bulletin",
                    ),
                ),
            ],
            options={
                "ordering": ["-published_date"],
            },
        ),
    ]

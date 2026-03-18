"""Generate or regenerate blog analysis posts for bulletins with predictions.

Usage:
    bazel run //scripts/oneoff:generate_initial_blog_post
    bazel run //scripts/oneoff:generate_initial_blog_post -- --all
    bazel run //scripts/oneoff:generate_initial_blog_post -- --month 2026-02
"""

import argparse
import os
import sys

import django

sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.blog.bulletin_narrator import BulletinNarrator
from models.bulletin import Bulletin
from models.vqs import PredictedBulletin


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Regenerate for all bulletins with predictions")
    parser.add_argument("--month", type=str, help="Specific month YYYY-MM")
    args = parser.parse_args()

    narrator = BulletinNarrator()

    if args.month:
        year, month = args.month.split("-")
        bulletins = Bulletin.objects.filter(
            publication_date__year=int(year),
            publication_date__month=int(month),
        )
    elif args.all:
        pred_months = PredictedBulletin.objects.values_list("target_bulletin_month", flat=True)
        bulletins = Bulletin.objects.filter(
            publication_date__in=pred_months,
        ).order_by("publication_date")
    else:
        bulletins = Bulletin.objects.order_by("-publication_date")[:1]

    if not bulletins:
        print("No matching bulletins found.")
        return

    for bulletin in bulletins:
        print(f"Generating post for: {bulletin.publication_date}")
        post = narrator.generate_post_for_bulletin(bulletin)
        print(f"  -> {post.title} (slug: {post.slug}, {len(post.content)} chars)")

    print(f"Done. Generated {len(bulletins)} post(s).")


if __name__ == "__main__":
    run()

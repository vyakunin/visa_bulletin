import os
import sys
import django

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.bulletin import Bulletin
from lib.business.blog.bulletin_narrator import BulletinNarrator

def run():
    # Get latest bulletin
    bulletin = Bulletin.objects.order_by("-publication_date").first()
    if not bulletin:
        print("No bulletins found.")
        return

    print(f"Generating blog post for bulletin: {bulletin.publication_date}")
    
    narrator = BulletinNarrator()
    post = narrator.generate_post_for_bulletin(bulletin)
    
    print(f"Created post: {post.title}")
    print(f"Slug: {post.slug}")
    print(f"Content length: {len(post.content)}")
    print("Done.")

if __name__ == "__main__":
    run()

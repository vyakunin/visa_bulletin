"""One-off: delete PredictedBulletin rows with gap > 200 days (wrong knowledge date from buggy backfill)."""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.vqs import PredictedBulletin

bad_ids = list(
    PredictedBulletin.objects.extra(
        where=["(target_bulletin_month - prediction_date) > 200"]
    ).values_list("id", flat=True)
)
print(f"Deleting {len(bad_ids)} bad PredictedBulletin rows (cascades to PredictedCutoff)...")
deleted, _ = PredictedBulletin.objects.filter(id__in=bad_ids).delete()
print(f"Deleted {deleted} objects total (including cascaded cutoffs).")

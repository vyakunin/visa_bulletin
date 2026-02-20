#!/usr/bin/env python3
"""Check status of bucket mismatch reviews"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from models.salary import EmployerClusteringReview

bucket_mismatch_reviews = EmployerClusteringReview.objects.filter(
    notes__contains="Bucket mismatch"
)

approved = bucket_mismatch_reviews.filter(status="approved").count()
rejected = bucket_mismatch_reviews.filter(status="rejected").count()
pending = bucket_mismatch_reviews.filter(status="pending").count()

print("Bucket mismatch reviews in database:")
print(f"  Total: {bucket_mismatch_reviews.count()}")
print(f"  Approved (same): {approved}")
print(f"  Rejected (different): {rejected}")
print(f"  Pending: {pending}")

print("\nSample approved bucket mismatch examples:")
for review in bucket_mismatch_reviews.filter(status="approved")[:5]:
    print(f"  '{review.employer1.name}' vs '{review.employer2.name}'")
    print(
        f"    {review.employer1.name_normalized} vs {review.employer2.name_normalized}"
    )

if pending > 0:
    print("\nPending reviews (need manual review):")
    for review in bucket_mismatch_reviews.filter(status="pending")[:10]:
        print(f"  '{review.employer1.name}' vs '{review.employer2.name}'")
        print(
            f"    {review.employer1.name_normalized} vs {review.employer2.name_normalized} | sim: {review.similarity_score:.3f}"
        )

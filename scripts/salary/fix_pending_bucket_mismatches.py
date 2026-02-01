#!/usr/bin/env python3
"""Fix pending bucket mismatch reviews that are clearly same companies"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django
django.setup()

from models.salary import EmployerClusteringReview
from django.db import transaction
from django.utils import timezone
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

setup_logging()
import logging
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

script_logger.log_call(
    args={},
    context='Fixing pending bucket mismatch reviews that are clearly same'
)

# Find pending reviews that are clearly same (normalization issues)
reviews = EmployerClusteringReview.objects.filter(
    status='pending',
    notes__contains='Bucket mismatch'
).order_by('-created_at')

logger.info(f"Found {reviews.count()} pending bucket mismatch reviews")

to_approve = []
for review in reviews:
    norm1 = review.employer1.name_normalized.lower()
    norm2 = review.employer2.name_normalized.lower()
    
    # Check if it's a normalization issue (same words, different formatting)
    def clean_words(s):
        s = s.replace('-', ' ').replace('&', ' ').replace('.', ' ').replace('/', ' ').replace('|', ' ')
        return {w for w in s.split() if w not in ['the', 'a', 'of', 'and', 'inc', 'llc', 'corp', 'ltd'] and len(w) > 2}
    
    words1 = clean_words(norm1)
    words2 = clean_words(norm2)
    
    if words1 == words2 and len(words1) > 0:
        to_approve.append(review)
        logger.info(f"  Will approve: '{review.employer1.name}' vs '{review.employer2.name}'")

logger.info(f"\nFound {len(to_approve)} pending reviews that are clearly same")

if to_approve:
    with transaction.atomic():
        for review in to_approve:
            review.status = 'approved'
            review.reviewed_by = 'auto-corrected-pending'
            review.reviewed_at = timezone.now()
            review.save()
    logger.info(f"Approved {len(to_approve)} reviews")
else:
    logger.info("No reviews to approve")




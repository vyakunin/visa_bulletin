#!/usr/bin/env python3
"""
Display pending bucket mismatch reviews for manual review.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django.db import transaction
from django.utils import timezone

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.salary import EmployerClusteringReview

setup_logging()
import logging

logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

script_logger.log_call(args={}, context="Reviewing pending bucket mismatch reviews")

# Find pending reviews
reviews = EmployerClusteringReview.objects.filter(
    status="pending", notes__contains="Bucket mismatch"
).order_by("-similarity_score")

logger.info(f"Found {reviews.count()} pending bucket mismatch reviews\n")
logger.info("=" * 100)

to_approve = []
to_reject = []

for i, review in enumerate(reviews, 1):
    emp1 = review.employer1
    emp2 = review.employer2

    logger.info(f"\n{i}. Similarity: {review.similarity_score:.3f}")
    logger.info(f"   Employer 1: '{emp1.name}'")
    logger.info(f"              Location: {emp1.city}, {emp1.state}")
    logger.info(f"              Normalized: '{emp1.name_normalized}'")
    logger.info(f"   Employer 2: '{emp2.name}'")
    logger.info(f"              Location: {emp2.city}, {emp2.state}")
    logger.info(f"              Normalized: '{emp2.name_normalized}'")
    logger.info(f"   Reason: {review.match_reason}")

    # Analyze the difference
    norm1 = emp1.name_normalized.lower()
    norm2 = emp2.name_normalized.lower()

    # Check for common patterns
    if norm1 == norm2:
        logger.info("   → SAME: Normalized names are identical (normalization bug)")
        to_approve.append((review, "Normalized names identical"))
    elif review.similarity_score >= 0.95:
        # Check for typos
        if any(
            typo in norm1 or typo in norm2
            for typo in [
                "consltancy",
                "servies",
                "seperation",
                "innocations",
                "corportaion",
            ]
        ):
            logger.info("   → SAME: High similarity with obvious typo")
            to_approve.append((review, "High similarity with typo"))
        elif "d/b/a" in norm1 or "d/b/a" in norm2 or "dba" in norm1 or "dba" in norm2:
            logger.info("   → SAME: D/B/A vs DBA variation")
            to_approve.append((review, "D/B/A vs DBA variation"))
        elif "c.p.a" in norm1 or "c.p.a" in norm2 or "cpa" in norm1 or "cpa" in norm2:
            logger.info("   → SAME: C.P.A. vs CPA variation")
            to_approve.append((review, "C.P.A. vs CPA variation"))
        elif norm1.replace(" ", "") == norm2.replace(" ", ""):
            logger.info("   → SAME: Only spacing differences")
            to_approve.append((review, "Only spacing differences"))
        else:
            logger.info("   → NEEDS REVIEW: High similarity but unclear")
    elif review.similarity_score < 0.90:
        # Check if first significant word is different
        words1 = [w for w in norm1.split() if len(w) > 3]
        words2 = [w for w in norm2.split() if len(w) > 3]
        if words1 and words2 and words1[0] != words2[0]:
            logger.info(
                f"   → DIFFERENT: Different first words ({words1[0]} vs {words2[0]})"
            )
            to_reject.append(
                (review, f"Different first words: {words1[0]} vs {words2[0]}")
            )
        else:
            logger.info("   → NEEDS REVIEW: Lower similarity, unclear")
    else:
        logger.info("   → NEEDS REVIEW: Medium similarity, needs manual check")

logger.info("\n" + "=" * 100)
logger.info("\nSummary:")
logger.info(f"  Auto-approve: {len(to_approve)}")
logger.info(f"  Auto-reject: {len(to_reject)}")
logger.info(
    f"  Needs manual review: {reviews.count() - len(to_approve) - len(to_reject)}"
)

if to_approve or to_reject:
    logger.info("\nApplying decisions...")
    with transaction.atomic():
        for review, reason in to_approve:
            review.status = "approved"
            review.reviewed_by = "auto-reviewed"
            review.reviewed_at = timezone.now()
            review.notes = f"{review.notes} | Auto-approved: {reason}"
            review.save()
            logger.info(
                f"  ✓ Approved: '{review.employer1.name}' vs '{review.employer2.name}' ({reason})"
            )

        for review, reason in to_reject:
            review.status = "rejected"
            review.reviewed_by = "auto-reviewed"
            review.reviewed_at = timezone.now()
            review.notes = f"{review.notes} | Auto-rejected: {reason}"
            review.save()
            logger.info(
                f"  ✗ Rejected: '{review.employer1.name}' vs '{review.employer2.name}' ({reason})"
            )

    logger.info(
        f"\nApplied {len(to_approve)} approvals and {len(to_reject)} rejections"
    )
else:
    logger.info("\nNo automatic decisions to apply")

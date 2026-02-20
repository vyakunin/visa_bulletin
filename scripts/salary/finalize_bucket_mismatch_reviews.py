#!/usr/bin/env python3
"""Finalize bucket mismatch reviews - mark clearly same/different"""

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

script_logger.log_call(args={}, context="Finalizing bucket mismatch reviews")

# Get all pending bucket mismatch reviews
pending_reviews = EmployerClusteringReview.objects.filter(
    status="pending", notes__contains="Bucket mismatch"
).order_by("id")

logger.info(f"Found {pending_reviews.count()} pending bucket mismatch reviews")

# Clearly different companies (different core names)
clearly_different = [
    ("LHP Architects", "PGN Architects"),
    ("SVP Technologies", "VK Technologies"),
    ("CS ENGINEERS", "PBS ENGINEERS"),
    ("HITEK PROFESSIONALS", "KIT PROFESSIONALS"),
    ("DoiT International", "Y INTERNATIONAL"),
    ("GL Intelligence", "Lead Intelligence"),
    ("GEO Semiconductor", "GV SEMICONDUCTOR"),
    ("Ray Engineering", "ARBAB ENGINEERING"),
    ("C.A.C INDUSTRIES", "AFC INDUSTRIES"),
    ("AVT Technology", "AUGMENT TECHNOLOGY"),
    ("MCP INDUSTRIES", "ASC INDUSTRIES"),
    ("MPR Associates", "KCM ASSOCIATES"),
    ("Asrtrix Technology", "AST Technology"),
]

# Clearly same (typos, normalization issues)
clearly_same_patterns = [
    # Typo patterns
    ("enterrises", "enterprises"),
    ("franching", "franchising"),
    ("connec", "connect"),
    ("constructiobn", "construction"),
    # Hyphenation/spacing
    ("mercedesbenz", "mercedes benz"),
    ("e-ko", "eko"),
    ("e ko", "eko"),
    # Formatting
    ("dds", "d.d.s."),
    ("dds,", "d.d.s.,"),
]

to_approve = []
to_reject = []

for review in pending_reviews:
    name1 = review.employer1.name.lower()
    name2 = review.employer2.name.lower()
    norm1 = review.employer1.name_normalized.lower()
    norm2 = review.employer2.name_normalized.lower()

    # Check if clearly different
    is_different = False
    for diff1, diff2 in clearly_different:
        if (diff1.lower() in name1 and diff2.lower() in name2) or (
            diff2.lower() in name1 and diff1.lower() in name2
        ):
            to_reject.append((review, f"Different companies: {diff1} vs {diff2}"))
            is_different = True
            break

    if is_different:
        continue

    # Check if clearly same (typos/normalization)
    is_same = False
    for pattern1, pattern2 in clearly_same_patterns:
        if (pattern1 in norm1 and pattern2 in norm2) or (
            pattern2 in norm1 and pattern1 in norm2
        ):
            to_approve.append(
                (review, f"Same company: {pattern1} vs {pattern2} (typo/normalization)")
            )
            is_same = True
            break

    if is_same:
        continue

    # Check for other normalization issues (same core words)
    def clean_words(s):
        s = (
            s.replace("-", " ")
            .replace("&", " ")
            .replace(".", " ")
            .replace("/", " ")
            .replace("|", " ")
            .replace(",", " ")
        )
        return {
            w
            for w in s.split()
            if w
            not in ["the", "a", "of", "and", "inc", "llc", "corp", "ltd", "pc", "pllc"]
            and len(w) > 2
        }

    words1 = clean_words(norm1)
    words2 = clean_words(norm2)

    if words1 == words2 and len(words1) > 0:
        to_approve.append(
            (review, "Same company: same core words (normalization issue)")
        )
        continue

    # Still need review
    logger.warning(
        f"  NEEDS REVIEW: '{review.employer1.name}' vs '{review.employer2.name}'"
    )
    logger.warning(f"    {norm1} vs {norm2} | sim: {review.similarity_score:.3f}")

logger.info(f"\nWill approve {len(to_approve)} reviews (clearly same)")
logger.info(f"Will reject {len(to_reject)} reviews (clearly different)")

if to_approve or to_reject:
    with transaction.atomic():
        for review, reason in to_approve:
            review.status = "approved"
            review.reviewed_by = "auto-finalized"
            review.reviewed_at = timezone.now()
            if review.notes:
                review.notes += f" | {reason}"
            else:
                review.notes = reason
            review.save()
            logger.info(
                f"  Approved: '{review.employer1.name}' vs '{review.employer2.name}' - {reason}"
            )

        for review, reason in to_reject:
            review.status = "rejected"
            review.reviewed_by = "auto-finalized"
            review.reviewed_at = timezone.now()
            if review.notes:
                review.notes += f" | {reason}"
            else:
                review.notes = reason
            review.save()
            logger.info(
                f"  Rejected: '{review.employer1.name}' vs '{review.employer2.name}' - {reason}"
            )

    logger.info(f"\nFinalized {len(to_approve) + len(to_reject)} reviews")
else:
    logger.info("No reviews to finalize")

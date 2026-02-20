#!/usr/bin/env python3
"""
Apply manual review decisions for pending bucket mismatch reviews.
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

script_logger.log_call(
    args={},
    context="Applying manual review decisions for pending bucket mismatch reviews",
)

# Manual review decisions based on analysis
# Format: (emp1_name_pattern, emp2_name_pattern, decision, reason)
# Use partial matches to handle variations
MANUAL_DECISIONS = [
    # Same company cases
    (
        "Governmental Management Services",
        "Governmental Management Services",
        "approved",
        "Missing hyphen in normalization",
    ),
    (
        "RAISON PURE INTERNATIONAL",
        "Raison Pure Internatial",
        "approved",
        "Typo: Internatial vs International",
    ),
    (
        "Sunpower Corporation",
        "Sunpower Corporations",
        "approved",
        "Punctuation/plural variation",
    ),
    (
        "SaarGummi Tennessee",
        "SAARGUMMI TENNESSEE",
        "approved",
        "Typo: lnc vs inc, same company",
    ),
    (
        "New England Annual Conference",
        "New England Conference",
        "approved",
        'Missing "Annual" word',
    ),
    (
        "Edward C. Donahue, C.P.A.",
        "Edward C. Donahue, CPA",
        "approved",
        "C.P.A. vs CPA variation",
    ),
    (
        "Penn Schoen & Berland",
        "Penn, Schoen and Berland",
        "approved",
        "Punctuation variation",
    ),
    ("Padilla", "PADILLA AND COMPANY", "approved", "Spacing/and variation"),
    (
        "ORTHOPAEDIC ASSOCIATES",
        "ORTHOPAEDIC ASSOCIATES LLP",
        "approved",
        "Missing LLP suffix",
    ),
    (
        "Test Stratus Technology",
        "Stratus Technology",
        "approved",
        "Test prefix variation",
    ),
    (
        "JEFFREY L. BONDE",
        "JEFF BONDE",
        "approved",
        "Full name vs nickname, same person",
    ),
    ("CREDIT CARD DISCOUNT", "CREDITCARD DISCOUNT", "approved", "Spacing variation"),
    # Different company cases
    ("Eta Wireless", "Get Wireless", "rejected", "Different companies: Eta vs Get"),
    (
        "ORIC Pharmaceuticals",
        "OSI PHARMACEUTICALS",
        "rejected",
        "Different companies: ORIC vs OSI",
    ),
    (
        "GREENTREE CLEANERS",
        "ENTREE CLEANERS",
        "rejected",
        "Different companies: Greentree vs Entree",
    ),
    ("ZY Electronics", "SKY ELECTRONICS", "rejected", "Different companies: ZY vs SKY"),
    ("AVILA CAPITAL", "ASL Capital", "rejected", "Different companies: AVILA vs ASL"),
    (
        "ORIC Pharmaceuticals",
        "RA Pharmaceuticals",
        "rejected",
        "Different companies: ORIC vs RA",
    ),
    ("B Properties", "LBTS PROPERTIES", "rejected", "Different companies: B vs LBTS"),
    (
        "David Yurman",
        "David Ryuman",
        "rejected",
        "Different companies: Yurman vs Ryuman",
    ),
    ("ISN Software", "MSC Software", "rejected", "Different companies: ISN vs MSC"),
    (
        "Inspirit IoT",
        "Inspirit AI",
        "rejected",
        "Different companies: IoT vs AI divisions",
    ),
    ("Eta Wireless", "AA WIRELESS", "rejected", "Different companies: Eta vs AA"),
    (
        "SPF North America",
        "PPM North America",
        "rejected",
        "Different companies: SPF vs PPM",
    ),
    ("ATLAS PROPERTY", "GLS Property", "rejected", "Different companies: Atlas vs GLS"),
    ("ATLAS PROPERTY", "LT Property", "rejected", "Different companies: Atlas vs LT"),
    (
        "UB TRANSPORTATION",
        "LRB TRANSPORTATION",
        "rejected",
        "Different companies: UB vs LRB",
    ),
    (
        "UB TRANSPORTATION",
        "Turk Transportation",
        "rejected",
        "Different companies: UB vs Turk",
    ),
    (
        "UB TRANSPORTATION",
        "Berg Transportation",
        "rejected",
        "Different companies: UB vs Berg",
    ),
    (
        "MARRS PROFESSIONAL",
        "MMI Professional",
        "rejected",
        "Different companies: MARRS vs MMI",
    ),
    (
        "KAPSCH TRAFFICCOM IVHS",
        "KAPSCH TRAFFICCOM USA",
        "rejected",
        "Different divisions: IVHS vs USA",
    ),
    (
        "P&S CONSTRUCTION",
        "VPS Construction",
        "rejected",
        "Different companies: P&S vs VPS",
    ),
    (
        "SMB Shared Services",
        "BP&C Shared Services",
        "rejected",
        "Different companies: SMB vs BP&C",
    ),
]

# Find pending reviews
reviews = EmployerClusteringReview.objects.filter(
    status="pending", notes__contains="Bucket mismatch"
).order_by("-similarity_score")

logger.info(f"Found {reviews.count()} pending bucket mismatch reviews")

to_approve = []
to_reject = []
unmatched = []

for review in reviews:
    emp1_name = review.employer1.name.upper()
    emp2_name = review.employer2.name.upper()

    matched = False
    for emp1_pattern, emp2_pattern, decision, reason in MANUAL_DECISIONS:
        emp1_pattern_upper = emp1_pattern.upper()
        emp2_pattern_upper = emp2_pattern.upper()

        # Check if both names match the patterns (either order)
        if (emp1_pattern_upper in emp1_name and emp2_pattern_upper in emp2_name) or (
            emp1_pattern_upper in emp2_name and emp2_pattern_upper in emp1_name
        ):
            if decision == "approved":
                to_approve.append((review, reason))
            else:
                to_reject.append((review, reason))
            matched = True
            break

    if not matched:
        unmatched.append(review)

logger.info("\nMatched decisions:")
logger.info(f"  To approve: {len(to_approve)}")
logger.info(f"  To reject: {len(to_reject)}")
logger.info(f"  Unmatched (need manual review): {len(unmatched)}")

if unmatched:
    logger.warning("\nUnmatched reviews (need manual decision):")
    for review in unmatched[:10]:  # Show first 10
        logger.warning(
            f"  '{review.employer1.name}' vs '{review.employer2.name}' (sim: {review.similarity_score:.3f})"
        )
    if len(unmatched) > 10:
        logger.warning(f"  ... and {len(unmatched) - 10} more")

if to_approve or to_reject:
    logger.info("\nApplying decisions...")
    with transaction.atomic():
        for review, reason in to_approve:
            review.status = "approved"
            review.reviewed_by = "manual-reviewed"
            review.reviewed_at = timezone.now()
            review.notes = f"{review.notes} | Manual-approved: {reason}"
            review.save()
            logger.info(
                f"  ✓ Approved: '{review.employer1.name}' vs '{review.employer2.name}' ({reason})"
            )

        for review, reason in to_reject:
            review.status = "rejected"
            review.reviewed_by = "manual-reviewed"
            review.reviewed_at = timezone.now()
            review.notes = f"{review.notes} | Manual-rejected: {reason}"
            review.save()
            logger.info(
                f"  ✗ Rejected: '{review.employer1.name}' vs '{review.employer2.name}' ({reason})"
            )

    logger.info(
        f"\nApplied {len(to_approve)} approvals and {len(to_reject)} rejections"
    )
    logger.info(f"Remaining pending: {len(unmatched)}")
else:
    logger.info("\nNo decisions to apply")

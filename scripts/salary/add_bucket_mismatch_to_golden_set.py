#!/usr/bin/env python3
"""
Add bucket mismatch candidates to golden set.

Reviews candidates and adds them to EmployerClusteringReview table.
"""

import argparse
import json
import logging
import os
from pathlib import Path

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django.db import transaction
from django.utils import timezone

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer, EmployerClusteringReview

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def find_employer_by_name(
    name: str, city: str = "", state: str = ""
) -> Employer | None:
    """Find employer by name, optionally matching city/state"""
    query = Employer.objects.filter(name=name)
    if city:
        query = query.filter(city__iexact=city)
    if state:
        query = query.filter(state__iexact=state)

    employers = list(query[:2])
    if len(employers) == 1:
        return employers[0]
    elif len(employers) > 1:
        logger.warning(
            f"Multiple employers found for '{name}' ({city}, {state}), using first"
        )
        return employers[0]
    return None


def is_obviously_same(candidate: dict) -> bool:
    """Determine if candidate is obviously the same company"""
    norm1 = candidate["emp1_normalized"]
    norm2 = candidate["emp2_normalized"]

    # Normalize further: remove punctuation, extra spaces, hyphens, apostrophes
    def clean_for_comparison(s):
        s = s.lower()
        # Remove punctuation (including apostrophes)
        for char in ".,/&()-'":
            s = s.replace(char, " ")
        # Normalize "&" to "and"
        s = s.replace("&", " and ")
        # Normalize spaces
        words = [w for w in s.split() if w]
        return " ".join(words)

    clean1 = clean_for_comparison(norm1)
    clean2 = clean_for_comparison(norm2)

    # If cleaned versions are identical, same company
    if clean1 == clean2:
        return True

    # Check if core words match (ignoring plurals and minor variations)
    words1 = set(clean1.split())
    words2 = set(clean2.split())

    # Filter out generic words (from shared module)
    from lib.business.salary.generic_words import ALL_GENERIC_WORDS

    significant1 = {w for w in words1 if len(w) > 2 and w not in ALL_GENERIC_WORDS}
    significant2 = {w for w in words2 if len(w) > 2 and w not in ALL_GENERIC_WORDS}

    # If all significant words match, same company
    if significant1 == significant2 and len(significant1) > 0:
        return True

    # Check for singular/plural differences
    if len(significant1) == len(significant2) and len(significant1) > 1:
        # Check if all words match except one might be plural
        words1_list = sorted(significant1)
        words2_list = sorted(significant2)
        if len(words1_list) == len(words2_list):
            mismatches = 0
            for w1, w2 in zip(words1_list, words2_list):
                if w1 != w2:
                    # Check if one is plural of the other
                    if not (
                        w1 + "s" == w2
                        or w1 == w2 + "s"
                        or w1 + "es" == w2
                        or w1 == w2 + "es"
                    ):
                        mismatches += 1
            if mismatches == 0:
                return True

    # Very high similarity (>= 0.98) - likely same company with typos/normalization issues
    if candidate["similarity"] >= 0.98:
        return True

    # High similarity (>= 0.97) with same core structure suggests same company
    if candidate["similarity"] >= 0.97:
        # Check if first significant word matches
        first_word1 = next(
            (w for w in clean1.split() if len(w) > 2 and w not in ALL_GENERIC_WORDS),
            None,
        )
        first_word2 = next(
            (w for w in clean2.split() if len(w) > 2 and w not in ALL_GENERIC_WORDS),
            None,
        )
        if first_word1 and first_word2 and first_word1 == first_word2:
            # If most words match, likely same
            common_words = significant1 & significant2
            if (
                len(common_words) >= min(len(significant1), len(significant2)) * 0.7
            ):  # Lowered threshold to 70%
                return True

    return False


def is_obviously_different(candidate: dict) -> bool:
    """Determine if candidate is obviously different companies"""
    # Different core company names (not just structural words)
    norm1 = candidate["emp1_normalized"]
    norm2 = candidate["emp2_normalized"]

    # Extract first significant word (company name)
    words1 = [w for w in norm1.split() if len(w) > 2]
    words2 = [w for w in norm2.split() if len(w) > 2]

    if words1 and words2:
        # If first significant words are different, likely different companies
        if words1[0] != words2[0] and len(words1[0]) > 3 and len(words2[0]) > 3:
            # But check if they're just abbreviations (e.g., "c&a" vs "c and a")
            norm1_lower = norm1.lower()
            norm2_lower = norm2.lower()
            if (
                words1[0].lower() not in norm2_lower
                and words2[0].lower() not in norm1_lower
            ):
                return True

    return False


def add_candidates_to_golden_set(
    candidates_file: Path, dry_run: bool = False, auto_approve_obvious: bool = True
):
    """Add bucket mismatch candidates to golden set"""
    logger.info(f"Loading candidates from {candidates_file}")

    candidates = []
    with open(candidates_file) as f:
        for line in f:
            if not line.strip():
                continue
            candidates.append(json.loads(line))

    logger.info(f"Loaded {len(candidates)} candidates")

    # Categorize candidates
    obviously_same = []
    obviously_different = []
    needs_review = []

    for candidate in candidates:
        if is_obviously_same(candidate):
            obviously_same.append(candidate)
        elif is_obviously_different(candidate):
            obviously_different.append(candidate)
        else:
            needs_review.append(candidate)

    logger.info("Categorized:")
    logger.info(f"  Obviously same: {len(obviously_same)}")
    logger.info(f"  Obviously different: {len(obviously_different)}")
    logger.info(f"  Needs review: {len(needs_review)}")

    # Show candidates that need review
    if needs_review:
        logger.warning("\nCandidates needing manual review:")
        for i, candidate in enumerate(needs_review[:20], 1):  # Show first 20
            logger.warning(
                f"  {i}. '{candidate['emp1_name']}' ({candidate['emp1_normalized']}) "
                f"vs '{candidate['emp2_name']}' ({candidate['emp2_normalized']}) "
                f"| sim: {candidate['similarity']:.3f}"
            )
        if len(needs_review) > 20:
            logger.warning(f"  ... and {len(needs_review) - 20} more")

    if dry_run:
        logger.info("\nDRY RUN - Would add:")
        logger.info(f"  {len(obviously_same)} as 'same' (approved)")
        logger.info(f"  {len(obviously_different)} as 'different' (rejected)")
        logger.info(f"  {len(needs_review)} need manual review")
        return

    # Add to database
    added_same = 0
    added_different = 0
    skipped = 0
    errors = 0

    with transaction.atomic():
        all_candidates = (
            obviously_same + obviously_different if auto_approve_obvious else []
        )
        all_candidates.extend(needs_review)  # Add needs_review so user can review them

        for candidate in all_candidates:
            try:
                # Find employers
                emp1 = find_employer_by_name(
                    candidate["emp1_name"],
                    candidate.get("emp1_city", ""),
                    candidate.get("emp1_state", ""),
                )
                emp2 = find_employer_by_name(
                    candidate["emp2_name"],
                    candidate.get("emp2_city", ""),
                    candidate.get("emp2_state", ""),
                )

                if not emp1 or not emp2:
                    logger.warning(
                        f"Could not find employers: '{candidate['emp1_name']}' or '{candidate['emp2_name']}'"
                    )
                    skipped += 1
                    continue

                # Check if review already exists
                existing = EmployerClusteringReview.objects.filter(
                    employer1=emp1, employer2=emp2
                ).first()

                if existing:
                    logger.debug(
                        f"Review already exists for '{emp1.name}' vs '{emp2.name}'"
                    )
                    skipped += 1
                    continue

                # Determine status
                if candidate in obviously_same:
                    status = "approved"
                    reviewed_by = "auto-same"
                elif candidate in obviously_different:
                    status = "rejected"
                    reviewed_by = "auto-different"
                else:
                    status = "pending"
                    reviewed_by = "needs-review"

                # Create review
                _review = EmployerClusteringReview.objects.create(
                    employer1=emp1,
                    employer2=emp2,
                    similarity_score=candidate["similarity"],
                    match_reason=candidate.get("reason", ""),
                    status=status,
                    reviewed_by=reviewed_by,
                    reviewed_at=timezone.now() if status != "pending" else None,
                    notes=f"Bucket mismatch candidate: {candidate.get('reason', '')}",
                )

                if status == "approved":
                    added_same += 1
                elif status == "rejected":
                    added_different += 1

            except Exception as e:
                logger.error(f"Error processing candidate: {e}", exc_info=True)
                errors += 1

    logger.info("\nAdded to golden set:")
    logger.info(f"  Same (approved): {added_same}")
    logger.info(f"  Different (rejected): {added_different}")
    logger.info(f"  Pending review: {len(needs_review)}")
    logger.info(f"  Skipped (already exists): {skipped}")
    logger.info(f"  Errors: {errors}")


def main():
    parser = argparse.ArgumentParser(
        description="Add bucket mismatch candidates to golden set"
    )
    parser.add_argument(
        "candidates_file", type=Path, help="JSONL file with bucket mismatch candidates"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be added without actually adding",
    )
    parser.add_argument(
        "--no-auto-approve",
        action="store_true",
        help="Do not auto-approve obvious cases (add all as pending)",
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={
            "candidates_file": str(args.candidates_file),
            "dry_run": args.dry_run,
            "no_auto_approve": args.no_auto_approve,
        },
        context="Adding bucket mismatch candidates to golden set",
    )

    add_candidates_to_golden_set(
        args.candidates_file,
        dry_run=args.dry_run,
        auto_approve_obvious=not args.no_auto_approve,
    )


if __name__ == "__main__":
    main()

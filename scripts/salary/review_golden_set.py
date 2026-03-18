#!/usr/bin/env python3
"""
Review golden set examples and mark them as reviewed.

Loads examples from JSONL file, reviews them, and creates/updates
EmployerClusteringReview entries with approved/rejected status.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from django.db import transaction
from django.utils import timezone

from django_config.logging_config import setup_logging
from lib.business.salary.employer_clustering import match_employers
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer, EmployerClusteringReview

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def load_examples(jsonl_file: Path, limit: int | None = None) -> list[dict]:
    """Load examples from JSONL file."""
    examples = []
    with open(jsonl_file) as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                example = json.loads(line)
                example["_line_num"] = line_num
                examples.append(example)
                if limit and len(examples) >= limit:
                    break
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON on line {line_num}: {e}")
                continue
    return examples


def find_employer_by_name(
    name: str, city: str = "", state: str = ""
) -> Employer | None:
    """
    Find employer in database by name and optionally location.

    Returns first match if multiple found.
    """
    # Try exact name match first
    employers = Employer.objects.filter(name=name)

    # Filter by location if provided
    if city:
        employers = employers.filter(city__iexact=city)
    if state:
        employers = employers.filter(state__iexact=state)

    employer = employers.first()
    if employer:
        return employer

    # Try normalized name match
    normalized = Employer.normalize_name(name)
    employers = Employer.objects.filter(name_normalized=normalized)
    if city:
        employers = employers.filter(city__iexact=city)
    if state:
        employers = employers.filter(state__iexact=state)

    return employers.first()


def review_example(example: dict, auto_approve: bool = False) -> dict:
    """
    Review a single example and determine if it should be approved or rejected.

    Returns dict with:
    - should_approve: bool
    - reason: str
    - is_borderline: bool
    """
    emp1_name = example.get("emp1_name", "")
    emp2_name = example.get("emp2_name", "")
    ground_truth = example.get("ground_truth", "unknown")
    similarity = example.get("similarity", 0.0)

    # Find employers in database
    emp1 = find_employer_by_name(
        emp1_name, example.get("emp1_city", ""), example.get("emp1_state", "")
    )
    emp2 = find_employer_by_name(
        emp2_name, example.get("emp2_city", ""), example.get("emp2_state", "")
    )

    if not emp1 or not emp2:
        return {
            "should_approve": None,
            "reason": f"Employer not found in database (emp1: {emp1 is not None}, emp2: {emp2 is not None})",
            "is_borderline": False,
            "emp1": emp1,
            "emp2": emp2,
        }

    # Use production algorithm to check
    is_match, confidence, reason = match_employers(emp1, emp2)

    # Determine if should approve based on ground truth
    should_approve = ground_truth == "same"

    # Check for borderline cases
    is_borderline = False

    # Borderline: Low similarity but marked as same
    if ground_truth == "same" and similarity < 0.7:
        is_borderline = True

    # Borderline: High similarity but marked as different
    if ground_truth == "different" and similarity > 0.8:
        is_borderline = True

    # Borderline: Structural word conflicts but marked as same
    if ground_truth == "same":
        # Check for obvious structural conflicts
        structural_conflicts = [
            ("HOLDINGS", "CAPITAL MANAGEMENT"),
            ("TECHNOLOGY", "CONSULTING"),
            ("SERVICE COMPANY", "MANAGEMENT GROUP"),
        ]
        name1_upper = emp1_name.upper()
        name2_upper = emp2_name.upper()
        for conflict1, conflict2 in structural_conflicts:
            if conflict1 in name1_upper and conflict2 in name2_upper:
                is_borderline = True
                break
            if conflict2 in name1_upper and conflict1 in name2_upper:
                is_borderline = True
                break

    # Borderline: Generic names that could be different entities
    generic_names = ["CHILDREN'S HOSPITAL", "COLUMBIA COLLEGE", "UNIVERSITY"]
    name1_upper = emp1_name.upper()
    name2_upper = emp2_name.upper()
    for generic in generic_names:
        if generic in name1_upper and generic in name2_upper:
            # Check if different locations suggest different entities
            loc1 = f"{example.get('emp1_city', '')}, {example.get('emp1_state', '')}"
            loc2 = f"{example.get('emp2_city', '')}, {example.get('emp2_state', '')}"
            if loc1.strip(", ") != loc2.strip(", "):
                is_borderline = True
                break

    return {
        "should_approve": should_approve,
        "reason": reason
        or f"Similarity: {similarity:.3f}, Ground truth: {ground_truth}",
        "is_borderline": is_borderline,
        "emp1": emp1,
        "emp2": emp2,
        "similarity": similarity,
        "confidence": confidence,
    }


def create_or_update_review(
    emp1: Employer,
    emp2: Employer,
    should_approve: bool,
    similarity: float,
    reason: str,
    reviewed_by: str = "manual",
) -> EmployerClusteringReview:
    """Create or update review entry."""
    # Ensure emp1.id < emp2.id for consistency
    if emp1.id > emp2.id:
        emp1, emp2 = emp2, emp1

    review, created = EmployerClusteringReview.objects.get_or_create(
        employer1=emp1,
        employer2=emp2,
        defaults={
            "similarity_score": similarity,
            "match_reason": reason,
            "status": "approved" if should_approve else "rejected",
            "reviewed_by": reviewed_by,
            "reviewed_at": timezone.now(),
        },
    )

    if not created:
        # Update existing review
        review.status = "approved" if should_approve else "rejected"
        review.reviewed_by = reviewed_by
        review.reviewed_at = timezone.now()
        review.similarity_score = similarity
        review.match_reason = reason
        review.save()

    return review


def main():
    parser = argparse.ArgumentParser(
        description="Review golden set examples and mark as reviewed"
    )
    parser.add_argument("examples_file", type=Path, help="JSONL file with examples")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Number of examples to review (default: 200)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve non-borderline cases without asking",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Review but do not save to database"
    )

    args = parser.parse_args()

    # Log execution
    script_logger.log_call(
        args=vars(args), context="Reviewing golden set examples and marking as reviewed"
    )

    # Load examples
    if not args.examples_file.exists():
        logger.error(f"Examples file not found: {args.examples_file}")
        sys.exit(1)

    logger.info(f"Loading examples from {args.examples_file}...")
    examples = load_examples(args.examples_file, limit=args.limit)
    logger.info(f"Loaded {len(examples)} examples")

    if not examples:
        logger.error("No examples to review!")
        sys.exit(1)

    # Review examples
    reviewed_count = 0
    borderline_cases = []
    not_found_cases = []
    errors = []

    print(f"\n{'=' * 80}")
    print(f"REVIEWING {len(examples)} EXAMPLES")
    print(f"{'=' * 80}\n")

    for i, example in enumerate(examples, 1):
        emp1_name = example.get("emp1_name", "N/A")
        emp2_name = example.get("emp2_name", "N/A")
        ground_truth = example.get("ground_truth", "unknown")

        print(
            f"[{i}/{len(examples)}] Reviewing: '{emp1_name}' vs '{emp2_name}' ({ground_truth})"
        )

        try:
            result = review_example(example, auto_approve=args.auto_approve)

            if result["should_approve"] is None:
                # Employer not found
                not_found_cases.append(
                    {
                        "example": i,
                        "emp1_name": emp1_name,
                        "emp2_name": emp2_name,
                        "reason": result["reason"],
                    }
                )
                print(f"  ⚠️  SKIPPED: {result['reason']}")
                continue

            if result["is_borderline"]:
                # Borderline case - ask user
                borderline_cases.append(
                    {
                        "example": i,
                        "emp1_name": emp1_name,
                        "emp2_name": emp2_name,
                        "emp1_location": f"{example.get('emp1_city', '')}, {example.get('emp1_state', '')}",
                        "emp2_location": f"{example.get('emp2_city', '')}, {example.get('emp2_state', '')}",
                        "similarity": result.get("similarity", 0.0),
                        "ground_truth": ground_truth,
                        "reason": result["reason"],
                        "result": result,
                    }
                )
                print(f"  ⚠️  BORDERLINE: {result['reason']}")
                print(
                    f"      Ground truth: {ground_truth}, Similarity: {result.get('similarity', 0.0):.3f}"
                )
            else:
                # Clear case - auto-approve/reject
                if not args.dry_run:
                    with transaction.atomic():
                        _review = create_or_update_review(
                            result["emp1"],
                            result["emp2"],
                            result["should_approve"],
                            result.get("similarity", 0.0),
                            result["reason"],
                            reviewed_by="manual",
                        )
                    reviewed_count += 1
                    status = "APPROVED" if result["should_approve"] else "REJECTED"
                    print(f"  ✅ {status}: {result['reason']}")
                else:
                    reviewed_count += 1
                    status = "APPROVED" if result["should_approve"] else "REJECTED"
                    print(f"  ✅ {status} (DRY RUN): {result['reason']}")

        except Exception as e:
            errors.append(
                {
                    "example": i,
                    "emp1_name": emp1_name,
                    "emp2_name": emp2_name,
                    "error": str(e),
                }
            )
            logger.error(f"Error reviewing example {i}: {e}", exc_info=True)
            print(f"  ❌ ERROR: {e}")

    # Summary
    print(f"\n{'=' * 80}")
    print("REVIEW SUMMARY")
    print(f"{'=' * 80}\n")
    print(f"Total examples: {len(examples)}")
    print(f"Reviewed: {reviewed_count}")
    print(f"Borderline cases: {len(borderline_cases)}")
    print(f"Not found in DB: {len(not_found_cases)}")
    print(f"Errors: {len(errors)}")

    # Show borderline cases
    if borderline_cases:
        print(f"\n{'=' * 80}")
        print("BORDERLINE CASES - NEED YOUR DECISION")
        print(f"{'=' * 80}\n")

        for case in borderline_cases:
            print(f"\nExample #{case['example']}:")
            print(f"  Employer 1: {case['emp1_name']}")
            print(f"    Location: {case['emp1_location']}")
            print(f"  Employer 2: {case['emp2_name']}")
            print(f"    Location: {case['emp2_location']}")
            print(f"  Similarity: {case['similarity']:.3f}")
            print(f"  Ground truth: {case['ground_truth']}")
            print(f"  Reason: {case['reason']}")
            print(f"  Current status: Marked as '{case['ground_truth']}' in golden set")

            if not args.auto_approve:
                response = (
                    input("\n  Approve (same company)? [y/n/skip]: ").strip().lower()
                )
                if response == "y":
                    should_approve = True
                elif response == "n":
                    should_approve = False
                else:
                    print("  Skipped")
                    continue

                if not args.dry_run:
                    with transaction.atomic():
                        _review = create_or_update_review(
                            case["result"]["emp1"],
                            case["result"]["emp2"],
                            should_approve,
                            case["similarity"],
                            case["reason"],
                            reviewed_by="manual-borderline",
                        )
                    reviewed_count += 1
                    status = "APPROVED" if should_approve else "REJECTED"
                    print(f"  ✅ {status}")

    # Show not found cases
    if not_found_cases:
        print(f"\n{'=' * 80}")
        print("EMPLOYERS NOT FOUND IN DATABASE")
        print(f"{'=' * 80}\n")
        for case in not_found_cases[:10]:  # Show first 10
            print(
                f"Example #{case['example']}: {case['emp1_name']} vs {case['emp2_name']}"
            )
            print(f"  {case['reason']}")
        if len(not_found_cases) > 10:
            print(f"\n... and {len(not_found_cases) - 10} more")

    # Show errors
    if errors:
        print(f"\n{'=' * 80}")
        print("ERRORS")
        print(f"{'=' * 80}\n")
        for error in errors:
            print(
                f"Example #{error['example']}: {error['emp1_name']} vs {error['emp2_name']}"
            )
            print(f"  Error: {error['error']}")

    if args.dry_run:
        print("\n⚠️  DRY RUN - No changes saved to database")
    else:
        print(f"\n✅ Reviewed {reviewed_count} examples and saved to database")


if __name__ == "__main__":
    main()

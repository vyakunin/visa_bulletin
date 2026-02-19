#!/usr/bin/env python3
"""
Review queue management for employer clustering

Allows reviewing ambiguous employer matches that need human/LLM review.
"""

import argparse
import os

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

import logging

from django.db import transaction
from django.utils import timezone

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer, EmployerCluster, EmployerClusteringReview

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def show_pending_reviews(limit: int | None = None):
    """Display pending reviews with similarity scores"""
    reviews = EmployerClusteringReview.objects.filter(status='pending').order_by('-similarity_score')

    if limit:
        reviews = reviews[:limit]

    count = reviews.count()
    if count == 0:
        print("No pending reviews.")
        return

    print(f"\n{count} pending review(s):\n")
    print(f"{'ID':<6} {'Employer 1':<40} {'Employer 2':<40} {'Score':<8} {'Reason'}")
    print("-" * 120)

    for review in reviews:
        emp1 = review.employer1
        emp2 = review.employer2
        emp1_str = f"{emp1.name[:35]}..." if len(emp1.name) > 35 else emp1.name
        emp2_str = f"{emp2.name[:35]}..." if len(emp2.name) > 35 else emp2.name
        reason = review.match_reason[:30] + "..." if len(review.match_reason) > 30 else review.match_reason

        print(f"{review.id:<6} {emp1_str:<40} {emp2_str:<40} {review.similarity_score:<8.3f} {reason}")

    print()


def process_llm_reviews(batch_size: int = 100, model: str = "llama3.2"):
    """
    Automatically review using local LLM (ollama)
    
    Falls back to human review if LLM unavailable.
    """
    reviews = EmployerClusteringReview.objects.filter(status='pending').order_by('-similarity_score')[:batch_size]

    if not reviews.exists():
        print("No pending reviews to process.")
        return

    print(f"Processing {reviews.count()} reviews with LLM ({model})...")

    # Check if ollama is available
    import subprocess
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, timeout=5)
        if result.returncode != 0:
            print("Warning: ollama not available, skipping LLM review")
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("Warning: ollama not available, skipping LLM review")
        return

    processed = 0
    for review in reviews:
        result = llm_review_match(review.employer1, review.employer2, model)

        if result:
            review.status = 'approved' if result['is_match'] else 'rejected'
            review.reviewed_by = 'llm'
            review.reviewed_at = timezone.now()
            review.notes = result.get('reasoning', '')
            review.save()
            processed += 1

    print(f"Processed {processed} reviews with LLM.")


def llm_review_match(employer1: Employer, employer2: Employer, model: str = "llama3.2") -> dict | None:
    """
    Use local LLM (ollama) to determine if two employers are the same
    
    Returns: {
        'is_match': bool,
        'confidence': float,
        'reasoning': str
    } or None if LLM unavailable
    """
    import json
    import subprocess

    prompt = f"""Are these two employer names referring to the same company?

Employer 1: {employer1.name} (Location: {employer1.city}, {employer1.state})
Employer 2: {employer2.name} (Location: {employer2.city}, {employer2.state})

Respond with JSON only:
{{
    "is_match": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

    try:
        result = subprocess.run(
            ['ollama', 'run', model],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.warning(f"LLM review failed for {employer1.name} vs {employer2.name}")
            return None

        # Parse JSON response
        output = result.stdout.strip()
        # Try to extract JSON from response (LLM might add extra text)
        import re
        json_match = re.search(r'\{[^}]+\}', output)
        if json_match:
            data = json.loads(json_match.group())
            return {
                'is_match': data.get('is_match', False),
                'confidence': data.get('confidence', 0.5),
                'reasoning': data.get('reasoning', '')
            }

        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.warning(f"LLM review error: {e}")
        return None


def human_review_interactive():
    """Interactive CLI for human review"""
    reviews = EmployerClusteringReview.objects.filter(status='pending').order_by('-similarity_score')

    if not reviews.exists():
        print("No pending reviews.")
        return

    print(f"\n{reviews.count()} pending review(s). Press Ctrl+C to exit.\n")

    for review in reviews:
        emp1 = review.employer1
        emp2 = review.employer2

        print(f"\nReview #{review.id}")
        print(f"Employer 1: {emp1.name} ({emp1.city}, {emp1.state})")
        print(f"Employer 2: {emp2.name} ({emp2.city}, {emp2.state})")
        print(f"Similarity: {review.similarity_score:.3f}")
        print(f"Reason: {review.match_reason}")
        print("\nAre these the same employer?")
        print("  [y]es - Same employer")
        print("  [n]o - Different employers")
        print("  [s]kip - Review later")
        print("  [q]uit - Exit review")

        while True:
            choice = input("\nChoice: ").strip().lower()

            if choice == 'y':
                review.status = 'approved'
                review.reviewed_by = 'human'
                review.reviewed_at = timezone.now()
                review.save()
                print("✓ Approved - Same employer")
                break
            elif choice == 'n':
                review.status = 'rejected'
                review.reviewed_by = 'human'
                review.reviewed_at = timezone.now()
                review.save()
                print("✗ Rejected - Different employers")
                break
            elif choice == 's':
                print("Skipped")
                break
            elif choice == 'q':
                print("Exiting review")
                return
            else:
                print("Invalid choice. Enter y, n, s, or q.")


def apply_approved_matches():
    """Merge employers based on approved reviews"""
    approved = EmployerClusteringReview.objects.filter(status='approved')

    if not approved.exists():
        print("No approved matches to apply.")
        return

    print(f"Applying {approved.count()} approved matches...")

    with transaction.atomic():
        for review in approved:
            emp1 = review.employer1
            emp2 = review.employer2

            # Get or create cluster for emp1
            if emp1.canonical_cluster:
                cluster = emp1.canonical_cluster
            else:
                cluster = EmployerCluster.objects.create(
                    canonical_name=emp1.name
                )
                emp1.canonical_cluster = cluster
                emp1.save()

            # Assign emp2 to same cluster
            emp2.canonical_cluster = cluster
            emp2.save()

            # Update cluster stats
            cluster.total_lca_count = sum(e.total_lca_count for e in cluster.employers.all())
            cluster.total_perm_count = sum(e.total_perm_count for e in cluster.employers.all())

            # Calculate average salary
            salaries = [float(e.avg_salary) for e in cluster.employers.all() if e.avg_salary]
            if salaries:
                cluster.avg_salary = sum(salaries) / len(salaries)

            cluster.save()

    print(f"Applied {approved.count()} matches.")


def main():
    parser = argparse.ArgumentParser(description='Review employer clustering matches')
    parser.add_argument('action', choices=['show', 'llm', 'human', 'apply'],
                       help='Action to perform')
    parser.add_argument('--limit', type=int, help='Limit number of reviews to show/process')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Batch size for LLM processing (default: 100)')
    parser.add_argument('--model', type=str, default='llama3.2',
                       help='Ollama model to use (default: llama3.2)')

    args = parser.parse_args()

    script_logger.log_call(
        args=vars(args),
        context=f'Review employer clustering: {args.action}'
    )

    if args.action == 'show':
        show_pending_reviews(limit=args.limit)
    elif args.action == 'llm':
        process_llm_reviews(batch_size=args.batch_size, model=args.model)
    elif args.action == 'human':
        human_review_interactive()
    elif args.action == 'apply':
        apply_approved_matches()


if __name__ == '__main__':
    main()








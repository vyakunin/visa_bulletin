#!/usr/bin/env python3
"""
Collect employer clustering matching examples from database.

Extracts examples from:
- EmployerClusteringReview (reviewed pairs with status)
- Auto-clustered pairs (from Employer.canonical_cluster)
- False positives/negatives from evaluation runs

Saves examples to JSONL file for use in benchmarks and training.
"""

import argparse
import difflib
import json
import logging
import os
import random
from pathlib import Path

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

from django.db.models import Count

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer, EmployerCluster, EmployerClusteringReview

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def collect_reviewed_pairs(output_file: Path, limit: int | None = None) -> int:
    """
    Collect examples from EmployerClusteringReview table.
    
    Returns:
        Number of examples collected
    """
    logger.info("Collecting reviewed pairs from EmployerClusteringReview...")

    # Query reviewed pairs (approved or rejected)
    query = EmployerClusteringReview.objects.filter(
        status__in=['approved', 'rejected']
    ).select_related('employer1', 'employer2')

    if limit:
        query = query[:limit]

    examples = []
    for review in query:
        examples.append({
            'type': 'reviewed',
            'emp1_name': review.employer1.name,
            'emp1_city': review.employer1.city or '',
            'emp1_state': review.employer1.state or '',
            'emp2_name': review.employer2.name,
            'emp2_city': review.employer2.city or '',
            'emp2_state': review.employer2.state or '',
            'similarity': review.similarity_score,
            'ground_truth': 'same' if review.status == 'approved' else 'different',
            'reviewed_by': review.reviewed_by or 'unknown',
            'match_reason': review.match_reason or '',
            'notes': review.notes or '',
        })

    logger.info(f"Collected {len(examples)} reviewed pairs")
    return examples


def collect_auto_clustered_pairs(output_file: Path, sample_size: int = 1000) -> list:
    """
    Collect examples from auto-clustered employers (same canonical_cluster).
    
    Returns:
        List of example pairs
    """
    logger.info(f"Collecting {sample_size} auto-clustered pairs...")

    # Get clusters with multiple employers
    clusters = EmployerCluster.objects.annotate(
        employer_count=Count('employers')
    ).filter(employer_count__gt=1)

    examples = []
    collected = 0

    for cluster in clusters:
        employers = list(cluster.employers.all()[:10])  # Sample up to 10 per cluster

        # Create pairs from employers in same cluster
        for i in range(len(employers)):
            for j in range(i + 1, len(employers)):
                if collected >= sample_size:
                    break

                emp1 = employers[i]
                emp2 = employers[j]

                # Calculate similarity
                similarity = difflib.SequenceMatcher(
                    None,
                    emp1.name_normalized,
                    emp2.name_normalized
                ).ratio()

                examples.append({
                    'type': 'auto_clustered',
                    'emp1_name': emp1.name,
                    'emp1_city': emp1.city or '',
                    'emp1_state': emp1.state or '',
                    'emp2_name': emp2.name,
                    'emp2_city': emp2.city or '',
                    'emp2_state': emp2.state or '',
                    'similarity': similarity,
                    'ground_truth': 'same',  # They're in the same cluster
                    'cluster_id': cluster.id,
                    'canonical_name': cluster.canonical_name,
                })
                collected += 1

            if collected >= sample_size:
                break

        if collected >= sample_size:
            break

    logger.info(f"Collected {len(examples)} auto-clustered pairs")
    return examples


def collect_different_company_pairs(output_file: Path, sample_size: int = 500) -> list:
    """
    Collect examples of different companies (negative examples).
    
    Samples pairs from different clusters or unclustered employers.
    
    Returns:
        List of example pairs
    """
    logger.info(f"Collecting {sample_size} different-company pairs...")

    # Get employers from different clusters
    clustered_employers = list(
        Employer.objects.filter(canonical_cluster__isnull=False)
        .select_related('canonical_cluster')
        .values_list('id', 'canonical_cluster_id', named=True)
    )

    # Group by cluster
    cluster_groups = {}
    for emp_id, cluster_id in clustered_employers:
        if cluster_id not in cluster_groups:
            cluster_groups[cluster_id] = []
        cluster_groups[cluster_id].append(emp_id)

    # Sample pairs from different clusters
    examples = []
    cluster_ids = list(cluster_groups.keys())

    for _ in range(sample_size):
        # Pick two different clusters
        cluster1_id, cluster2_id = random.sample(cluster_ids, 2)

        # Pick one employer from each cluster
        emp1_id = random.choice(cluster_groups[cluster1_id])
        emp2_id = random.choice(cluster_groups[cluster2_id])

        emp1 = Employer.objects.get(id=emp1_id)
        emp2 = Employer.objects.get(id=emp2_id)

        # Calculate similarity
        similarity = difflib.SequenceMatcher(
            None,
            emp1.name_normalized,
            emp2.name_normalized
        ).ratio()

        examples.append({
            'type': 'different_companies',
            'emp1_name': emp1.name,
            'emp1_city': emp1.city or '',
            'emp1_state': emp1.state or '',
            'emp2_name': emp2.name,
            'emp2_city': emp2.city or '',
            'emp2_state': emp2.state or '',
            'similarity': similarity,
            'ground_truth': 'different',
            'cluster1_id': cluster1_id,
            'cluster2_id': cluster2_id,
        })

    logger.info(f"Collected {len(examples)} different-company pairs")
    return examples


def save_examples(examples: list, output_file: Path):
    """Save examples to JSONL file."""
    logger.info(f"Saving {len(examples)} examples to {output_file}...")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        for example in examples:
            f.write(json.dumps(example) + '\n')

    logger.info(f"Saved examples to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Collect employer clustering matching examples"
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('data/clustering_examples.jsonl'),
        help='Output JSONL file path (default: data/clustering_examples.jsonl)'
    )
    parser.add_argument(
        '--reviewed-limit',
        type=int,
        default=None,
        help='Limit number of reviewed pairs to collect (default: all)'
    )
    parser.add_argument(
        '--auto-clustered-size',
        type=int,
        default=1000,
        help='Number of auto-clustered pairs to sample (default: 1000)'
    )
    parser.add_argument(
        '--different-size',
        type=int,
        default=500,
        help='Number of different-company pairs to sample (default: 500)'
    )
    parser.add_argument(
        '--skip-reviewed',
        action='store_true',
        help='Skip collecting reviewed pairs'
    )
    parser.add_argument(
        '--skip-auto-clustered',
        action='store_true',
        help='Skip collecting auto-clustered pairs'
    )
    parser.add_argument(
        '--skip-different',
        action='store_true',
        help='Skip collecting different-company pairs'
    )

    args = parser.parse_args()

    # Log execution
    script_logger.log_call(
        args=vars(args),
        context='Collecting employer clustering examples for benchmark dataset'
    )

    all_examples = []

    # Collect reviewed pairs
    if not args.skip_reviewed:
        reviewed = collect_reviewed_pairs(args.output, args.reviewed_limit)
        all_examples.extend(reviewed)

    # Collect auto-clustered pairs
    if not args.skip_auto_clustered:
        auto_clustered = collect_auto_clustered_pairs(args.output, args.auto_clustered_size)
        all_examples.extend(auto_clustered)

    # Collect different-company pairs
    if not args.skip_different:
        different = collect_different_company_pairs(args.output, args.different_size)
        all_examples.extend(different)

    # Save all examples
    if all_examples:
        save_examples(all_examples, args.output)
        logger.info(f"\nTotal examples collected: {len(all_examples)}")
        logger.info(f"  - Reviewed: {sum(1 for e in all_examples if e['type'] == 'reviewed')}")
        logger.info(f"  - Auto-clustered: {sum(1 for e in all_examples if e['type'] == 'auto_clustered')}")
        logger.info(f"  - Different companies: {sum(1 for e in all_examples if e['type'] == 'different_companies')}")
    else:
        logger.warning("No examples collected!")


if __name__ == '__main__':
    main()

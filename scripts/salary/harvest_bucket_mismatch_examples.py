#!/usr/bin/env python3
"""
Harvest potential false negatives due to hash clustering (normalized name buckets).

Finds pairs of employers that:
- Normalize to different values (different hash buckets)
- But have high similarity (potential matches)
- Would never be compared in production clustering

These are candidates for false negatives and should be reviewed and added to golden set.
"""

import argparse
import json
import logging
import os
from collections import defaultdict
from pathlib import Path

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

from django_config.logging_config import setup_logging
from lib.business.salary.generic_words import (
    ALL_GENERIC_WORDS,
)
from lib.utils.logging_utils import ScriptLogger
from models.salary import Employer

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def extract_core_words(normalized_name: str) -> set[str]:
    """Extract core (non-generic) words from normalized name"""
    words = set(normalized_name.split())
    return {w for w in words if w not in ALL_GENERIC_WORDS}


def buckets_differ_only_by_generic_words(norm1: str, norm2: str) -> bool:
    """Check if two normalized names differ only by generic words"""
    core1 = extract_core_words(norm1)
    core2 = extract_core_words(norm2)
    return core1 == core2 and len(core1) > 0


def harvest_bucket_mismatch_candidates(
    min_similarity: float = 0.80,
    max_candidates: int = 500,
    output_file: Path | None = None
) -> list[dict]:
    """
    Find pairs of employers that normalize to different buckets but have high similarity.
    
    Args:
        min_similarity: Minimum similarity score to consider (0.0-1.0)
        max_candidates: Maximum number of candidates to return
        output_file: Optional path to save results as JSONL
    
    Returns:
        List of candidate pairs with metadata
    """
    logger.info("Harvesting bucket mismatch candidates...")
    logger.info(f"  Min similarity: {min_similarity}")
    logger.info(f"  Max candidates: {max_candidates}")

    # Load all employers with their normalized names
    logger.info("Loading employers from database...")
    employers = list(Employer.objects.all().values('id', 'name', 'name_normalized', 'city', 'state'))
    logger.info(f"Loaded {len(employers)} employers")

    # Group by normalized name (hash buckets)
    buckets = defaultdict(list)
    for emp in employers:
        buckets[emp['name_normalized']].append(emp)

    logger.info(f"Found {len(buckets)} unique normalized name buckets")

    # Find candidates: pairs in different buckets with high similarity
    # Optimization: Use word-based indexing to only compare relevant buckets
    candidates = []
    checked_pairs = set()  # Avoid duplicates

    logger.info("Searching for high-similarity pairs in different buckets...")
    logger.info("  Using optimized approach: word-based bucket indexing + random sampling")

    # Build word-to-buckets index (only compare buckets that share CORE words, not generic words)
    import random
    word_to_buckets = defaultdict(list)
    for bucket_name, bucket_employers in buckets.items():
        # Only index core (non-generic) words
        core_words = extract_core_words(bucket_name)
        for word in core_words:
            if len(word) > 2:  # Skip very short words
                word_to_buckets[word].append(bucket_name)

    logger.info(f"  Built word index: {len(word_to_buckets)} core words mapping to buckets")
    logger.info(f"  (Excluded generic words like: {', '.join(sorted(list(ALL_GENERIC_WORDS))[:10])}...)")

    # Sample 1-2 employers per bucket (much smaller sample)
    sampled_employers_by_bucket = {}
    for bucket_name, bucket_employers in buckets.items():
        # Randomly sample 1-2 employers per bucket
        sample_size = min(random.randint(1, 2), len(bucket_employers))
        sampled = random.sample(bucket_employers, sample_size)
        sampled_employers_by_bucket[bucket_name] = sampled

    total_sampled = sum(len(emps) for emps in sampled_employers_by_bucket.values())
    logger.info(f"  Sampled {total_sampled} employers from {len(buckets)} buckets (1-2 per bucket)")

    # Compare only buckets that share common words (much more efficient)
    import difflib
    import time
    start_time = time.time()
    comparisons = 0
    similarity_calculations = 0
    buckets_processed = 0

    # Process buckets in random order
    bucket_names = list(sampled_employers_by_bucket.keys())
    random.shuffle(bucket_names)

    for bucket1_name in bucket_names:
        if len(candidates) >= max_candidates:
            break

        buckets_processed += 1
        if buckets_processed % 1000 == 0:
            elapsed = time.time() - start_time
            logger.info(
                f"  Progress: {buckets_processed:,}/{len(bucket_names):,} buckets "
                f"({buckets_processed/len(bucket_names)*100:.1f}%) | "
                f"Comparisons: {comparisons:,} | "
                f"Similarity calcs: {similarity_calculations:,} | "
                f"Candidates: {len(candidates)} | "
                f"Time: {elapsed:.1f}s"
            )

        emp1_list = sampled_employers_by_bucket[bucket1_name]
        core_words1 = extract_core_words(bucket1_name)

        # Only compare with buckets that share at least one CORE word (not generic)
        candidate_buckets = set()
        for word in core_words1:
            if len(word) > 2 and word in word_to_buckets:
                candidate_buckets.update(word_to_buckets[word])

        # Remove self and limit to reasonable number of comparisons
        candidate_buckets.discard(bucket1_name)

        # Skip buckets that differ only by generic words (not meaningful bucket mismatches)
        candidate_buckets_filtered = []
        for bucket2_name in candidate_buckets:
            if not buckets_differ_only_by_generic_words(bucket1_name, bucket2_name):
                candidate_buckets_filtered.append(bucket2_name)

        candidate_buckets = candidate_buckets_filtered
        if len(candidate_buckets) > 100:  # Limit comparisons per bucket
            candidate_buckets = random.sample(candidate_buckets, 100)

        for bucket2_name in candidate_buckets:
            if len(candidates) >= max_candidates:
                break

            emp2_list = sampled_employers_by_bucket.get(bucket2_name, [])

            # Compare all pairs between these two buckets
            for emp1 in emp1_list:
                if len(candidates) >= max_candidates:
                    break

                norm1 = emp1['name_normalized']

                for emp2 in emp2_list:
                    if len(candidates) >= max_candidates:
                        break

                    norm2 = emp2['name_normalized']

                    # Skip if already checked (avoid duplicates)
                    pair_key = tuple(sorted([emp1['id'], emp2['id']]))
                    if pair_key in checked_pairs:
                        continue
                    checked_pairs.add(pair_key)
                    comparisons += 1

                    # Quick filter: skip if normalized names share no common CORE words
                    # (generic words don't count - we want meaningful differences)
                    core_words1 = extract_core_words(norm1)
                    core_words2 = extract_core_words(norm2)
                    if not core_words1.intersection(core_words2) and len(core_words1) > 0 and len(core_words2) > 0:
                        continue

                    # Skip if buckets differ only by generic words (not a meaningful bucket mismatch)
                    if buckets_differ_only_by_generic_words(norm1, norm2):
                        continue

                    # Calculate similarity
                    similarity_calculations += 1
                    similarity = difflib.SequenceMatcher(None, emp1['name'].lower(), emp2['name'].lower()).ratio()

                    # Only consider high-similarity pairs
                    if similarity >= min_similarity:
                        candidates.append({
                            'emp1_id': emp1['id'],
                            'emp1_name': emp1['name'],
                            'emp1_city': emp1['city'] or '',
                            'emp1_state': emp1['state'] or '',
                            'emp1_normalized': norm1,
                            'emp2_id': emp2['id'],
                            'emp2_name': emp2['name'],
                            'emp2_city': emp2['city'] or '',
                            'emp2_state': emp2['state'] or '',
                            'emp2_normalized': norm2,
                            'similarity': similarity,
                            'bucket_mismatch': True,
                            'reason': f"Different normalized buckets: '{norm1}' vs '{norm2}' (similarity: {similarity:.3f})"
                        })

    # Sort by similarity (highest first)
    candidates.sort(key=lambda x: x['similarity'], reverse=True)

    total_time = time.time() - start_time
    logger.info(f"Found {len(candidates)} bucket mismatch candidates")
    logger.info(f"  Total comparisons: {comparisons:,}")
    logger.info(f"  Similarity calculations: {similarity_calculations:,}")
    logger.info(f"  Filter efficiency: {(1 - similarity_calculations/comparisons)*100:.1f}% filtered by quick checks" if comparisons > 0 else "")
    logger.info(f"  Total time: {total_time:.1f}s ({total_time/60:.1f} min)")

    # Save to file if requested
    if output_file:
        logger.info(f"Saving {len(candidates)} candidates to {output_file}")
        with open(output_file, 'w') as f:
            for candidate in candidates:
                f.write(json.dumps(candidate) + '\n')
        logger.info(f"Saved to {output_file}")

    return candidates


def print_candidates(candidates: list[dict], limit: int | None = None):
    """Print candidates in human-readable format"""
    print(f"\n{'='*80}")
    print("BUCKET MISMATCH CANDIDATES (Potential False Negatives)")
    print(f"{'='*80}")
    print(f"Total candidates: {len(candidates)}")
    if limit:
        print(f"Showing top {limit} by similarity:")
        candidates = candidates[:limit]
    print()

    for i, candidate in enumerate(candidates, 1):
        print(f"{i}. Similarity: {candidate['similarity']:.3f}")
        print(f"   Employer 1: '{candidate['emp1_name']}'")
        print(f"               Location: {candidate['emp1_city']}, {candidate['emp1_state']}")
        print(f"               Normalized: '{candidate['emp1_normalized']}'")
        print(f"   Employer 2: '{candidate['emp2_name']}'")
        print(f"               Location: {candidate['emp2_city']}, {candidate['emp2_state']}")
        print(f"               Normalized: '{candidate['emp2_normalized']}'")
        print(f"   Reason: {candidate['reason']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Harvest potential false negatives due to hash clustering (bucket mismatches)"
    )
    parser.add_argument(
        '--min-similarity',
        type=float,
        default=0.80,
        help='Minimum similarity score to consider (0.0-1.0, default: 0.80)'
    )
    parser.add_argument(
        '--max-candidates',
        type=int,
        default=500,
        help='Maximum number of candidates to find (default: 500)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output JSONL file path (optional)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of candidates to display (default: show all)'
    )
    parser.add_argument(
        '--format',
        choices=['summary', 'detailed', 'jsonl'],
        default='detailed',
        help='Output format (default: detailed)'
    )

    args = parser.parse_args()

    # Log the execution
    script_logger.log_call(
        args={
            'min_similarity': args.min_similarity,
            'max_candidates': args.max_candidates,
            'output': str(args.output) if args.output else None,
            'limit': args.limit,
            'format': args.format,
        },
        context='Harvesting bucket mismatch candidates for golden set coverage'
    )

    # Harvest candidates
    candidates = harvest_bucket_mismatch_candidates(
        min_similarity=args.min_similarity,
        max_candidates=args.max_candidates,
        output_file=args.output
    )

    # Print results
    if args.format == 'summary':
        print(f"Found {len(candidates)} bucket mismatch candidates")
        if candidates:
            print(f"  Highest similarity: {candidates[0]['similarity']:.3f}")
            print(f"  Lowest similarity: {candidates[-1]['similarity']:.3f}")
            print(f"  Average similarity: {sum(c['similarity'] for c in candidates) / len(candidates):.3f}")
    elif args.format == 'detailed':
        print_candidates(candidates, limit=args.limit)
    elif args.format == 'jsonl':
        # Already saved if output_file was provided
        if not args.output:
            # Print to stdout
            for candidate in candidates:
                print(json.dumps(candidate))

    logger.info("Harvesting complete")


if __name__ == '__main__':
    main()


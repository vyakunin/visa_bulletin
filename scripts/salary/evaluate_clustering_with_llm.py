#!/usr/bin/env python3
"""
Evaluate employer clustering precision/recall using LLM validation.

Samples pairs from:
1. Auto-clustered pairs (should be true positives)
2. Queued for review pairs (may include false positives that should be rejected)

Uses offline LLM (Ollama) to validate if pairs are actually the same company.
"""

import argparse
import json
import logging
import os
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

# Setup Django FIRST (before any imports that might trigger model imports)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

# Add project root to path
if 'BUILD_WORKSPACE_DIRECTORY' in os.environ:
    project_root = Path(os.environ['BUILD_WORKSPACE_DIRECTORY'])
else:
    current = Path(__file__).parent
    while current != current.parent:
        if (current / 'BUILD').exists() or (current / 'MODULE.bazel').exists():
            project_root = current
            break
        current = current.parent
    else:
        project_root = Path(__file__).parent.parent.parent

sys.path.insert(0, str(project_root))

import django
django.setup()

from django.apps import apps
Employer = apps.get_model('models', 'Employer')
EmployerClusteringReview = apps.get_model('models', 'EmployerClusteringReview')

from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Import shared LLM validation utilities
from lib.business.salary.llm_verifier import validate_pair_with_llm as validate_pair_shared
from lib.business.salary.clustering_evaluator import EmployerPair


def validate_pair_with_llm(emp1: Employer, emp2: Employer, similarity: float) -> tuple[Optional[bool], Optional[str]]:
    """
    Use LLM to validate if two employers are the same company.
    
    Wrapper around shared validate_pair_with_llm that adapts the interface
    to work with Employer objects and return tuple instead of EvaluationOutcome.
    
    Returns: (is_same_company, llm_response) or (None, None) if validation failed
    """
    # Convert Employer objects to EmployerPair
    pair = EmployerPair(
        emp1_name=emp1.name,
        emp1_city=emp1.city,
        emp1_state=emp1.state,
        emp2_name=emp2.name,
        emp2_city=emp2.city,
        emp2_state=emp2.state,
        similarity=similarity
    )
    
    # Use shared validation function
    outcome = validate_pair_shared(pair)
    
    # Convert EvaluationOutcome to tuple for backward compatibility
    if outcome.is_same is None:
        return None, None
    return outcome.is_same, outcome.response


def sample_pairs_from_clustering_results(
    auto_clustered_pairs: list[tuple[Employer, Employer, float]],
    queued_pairs: list[tuple[Employer, Employer, float]],
    sample_size: int = 50
) -> dict:
    """
    Sample pairs from auto-clustered and queued sets for evaluation.
    
    Returns dict with sampled pairs and metadata.
    """
    # Sample from each category
    auto_sample_size = min(sample_size // 2, len(auto_clustered_pairs))
    queue_sample_size = min(sample_size // 2, len(queued_pairs))
    
    auto_sample = random.sample(auto_clustered_pairs, auto_sample_size) if auto_clustered_pairs else []
    queue_sample = random.sample(queued_pairs, queue_sample_size) if queued_pairs else []
    
    return {
        'auto_clustered': auto_sample,
        'queued_for_review': queue_sample,
        'total_auto': len(auto_clustered_pairs),
        'total_queued': len(queued_pairs),
    }


def evaluate_samples(samples: dict) -> dict:
    """
    Evaluate sampled pairs using LLM validation.
    
    Returns metrics dict with precision/recall.
    """
    logger.info("Evaluating auto-clustered pairs...")
    auto_tp = 0  # True positives (correctly clustered)
    auto_fp = 0  # False positives (incorrectly clustered)
    auto_total = 0
    
    for emp1, emp2, similarity in samples['auto_clustered']:
        auto_total += 1
        is_same, response = validate_pair_with_llm(emp1, emp2, similarity)
        if is_same is None:
            logger.warning(f"Skipping {emp1.name} <-> {emp2.name} (LLM unavailable)")
            continue
        
        if is_same:
            auto_tp += 1
            logger.debug(f"✓ TP: {emp1.name} <-> {emp2.name}")
        else:
            auto_fp += 1
            logger.warning(f"✗ FP: {emp1.name} <-> {emp2.name} (LLM: {response[:100]})")
    
    logger.info("Evaluating queued-for-review pairs...")
    queue_tp = 0  # True positives (should have been clustered)
    queue_fp = 0  # False positives (correctly queued)
    queue_total = 0
    
    for emp1, emp2, similarity in samples['queued_for_review']:
        queue_total += 1
        is_same, response = validate_pair_with_llm(emp1, emp2, similarity)
        if is_same is None:
            logger.warning(f"Skipping {emp1.name} <-> {emp2.name} (LLM unavailable)")
            continue
        
        if is_same:
            queue_tp += 1  # Should have been auto-clustered (false negative)
            logger.warning(f"✗ FN: {emp1.name} <-> {emp2.name} (should be clustered, LLM: {response[:100]})")
        else:
            queue_fp += 1  # Correctly queued (true negative)
            logger.debug(f"✓ TN: {emp1.name} <-> {emp2.name}")
    
    # Calculate metrics
    auto_precision = auto_tp / max(auto_total, 1)
    auto_recall = auto_tp / max(auto_tp + queue_tp, 1)  # TP / (TP + FN)
    
    metrics = {
        'auto_clustered': {
            'total_evaluated': auto_total,
            'true_positives': auto_tp,
            'false_positives': auto_fp,
            'precision': auto_precision,
        },
        'queued_for_review': {
            'total_evaluated': queue_total,
            'true_negatives': queue_fp,  # Correctly queued (not same company)
            'false_negatives': queue_tp,  # Should have been clustered
        },
        'overall': {
            'precision': auto_precision,
            'recall': auto_recall,
            'f1_score': 2 * (auto_precision * auto_recall) / max(auto_precision + auto_recall, 0.001),
        }
    }
    
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Evaluate clustering precision/recall with LLM")
    parser.add_argument('--clustering-log', required=True, help='Path to clustering dry-run log file')
    parser.add_argument('--sample-size', type=int, default=50, help='Number of pairs to sample per category')
    parser.add_argument('--seed', type=int, default=42, help='Random seed for sampling')
    parser.add_argument('--output', help='Output JSON file for metrics')
    
    args = parser.parse_args()
    
    random.seed(args.seed)
    
    # Parse clustering log to extract pairs
    logger.info(f"Parsing clustering log: {args.clustering_log}")
    auto_clustered_pairs = []
    queued_pairs = []
    
    with open(args.clustering_log, 'r') as f:
        for line in f:
            if 'Auto-clustered:' in line:
                # Extract employer names and similarity
                # Format: "Auto-clustered: Name1 <-> Name2 (similarity)"
                parts = line.split('Auto-clustered:')[1].strip()
                if '<->' in parts:
                    name_parts = parts.split('<->')
                    if len(name_parts) == 2:
                        name1 = name_parts[0].strip()
                        rest = name_parts[1].strip()
                        # Extract similarity from "(0.xxx)"
                        similarity_str = rest.split('(')[1].split(')')[0] if '(' in rest else '1.000'
                        try:
                            similarity = float(similarity_str)
                            # Look up employers
                            emp1 = Employer.objects.filter(name=name1).first()
                            if emp1:
                                name2 = rest.split('(')[0].strip()
                                emp2 = Employer.objects.filter(name=name2).first()
                                if emp2:
                                    auto_clustered_pairs.append((emp1, emp2, similarity))
                        except ValueError:
                            pass
            
            elif 'Queued for review:' in line:
                # Similar parsing for queued pairs
                parts = line.split('Queued for review:')[1].strip()
                if '<->' in parts:
                    name_parts = parts.split('<->')
                    if len(name_parts) == 2:
                        name1 = name_parts[0].strip()
                        rest = name_parts[1].strip()
                        similarity_str = rest.split('(')[1].split(')')[0] if '(' in rest else '0.000'
                        try:
                            similarity = float(similarity_str)
                            emp1 = Employer.objects.filter(name=name1).first()
                            if emp1:
                                name2 = rest.split('(')[0].strip()
                                emp2 = Employer.objects.filter(name=name2).first()
                                if emp2:
                                    queued_pairs.append((emp1, emp2, similarity))
                        except ValueError:
                            pass
    
    logger.info(f"Found {len(auto_clustered_pairs):,} auto-clustered pairs")
    logger.info(f"Found {len(queued_pairs):,} queued pairs")
    
    if not auto_clustered_pairs and not queued_pairs:
        logger.error("No pairs found in clustering log. Check log format.")
        return 1
    
    # Sample pairs
    samples = sample_pairs_from_clustering_results(
        auto_clustered_pairs,
        queued_pairs,
        sample_size=args.sample_size
    )
    
    logger.info(f"Sampled {len(samples['auto_clustered'])} auto-clustered pairs")
    logger.info(f"Sampled {len(samples['queued_for_review'])} queued pairs")
    
    # Evaluate with LLM
    metrics = evaluate_samples(samples)
    
    # Print results
    print("\n" + "="*60)
    print("CLUSTERING EVALUATION RESULTS")
    print("="*60)
    print(f"\nAuto-Clustered Pairs:")
    print(f"  Total evaluated: {metrics['auto_clustered']['total_evaluated']}")
    print(f"  True positives: {metrics['auto_clustered']['true_positives']}")
    print(f"  False positives: {metrics['auto_clustered']['false_positives']}")
    print(f"  Precision: {metrics['auto_clustered']['precision']:.1%}")
    
    print(f"\nQueued for Review Pairs:")
    print(f"  Total evaluated: {metrics['queued_for_review']['total_evaluated']}")
    print(f"  True negatives: {metrics['queued_for_review']['true_negatives']}")
    print(f"  False negatives: {metrics['queued_for_review']['false_negatives']}")
    
    print(f"\nOverall Metrics:")
    print(f"  Precision: {metrics['overall']['precision']:.1%}")
    print(f"  Recall: {metrics['overall']['recall']:.1%}")
    print(f"  F1 Score: {metrics['overall']['f1_score']:.3f}")
    print("="*60)
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(metrics, f, indent=2)
        logger.info(f"Metrics saved to {args.output}")
    
    return 0


if __name__ == '__main__':
    import os
    sys.exit(main())


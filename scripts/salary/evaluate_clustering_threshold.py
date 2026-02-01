#!/usr/bin/env python3
"""
Test a single clustering threshold and report precision/recall with samples.

Useful for binary search to find the threshold that achieves 99% precision.
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
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

from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Import evaluator (now uses async parallel HTTP API)
from lib.business.salary.clustering_evaluator import ClusteringEvaluator


def load_pairs_from_jsonl(jsonl_file: str) -> tuple[list, list]:
    """Load pairs from JSONL file."""
    auto_clustered = []
    queued = []
    
    with open(jsonl_file, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                pair = json.loads(line)
                if pair['type'] == 'auto_clustered':
                    auto_clustered.append(pair)
                elif pair['type'] == 'queued_for_review':
                    queued.append(pair)
            except json.JSONDecodeError:
                continue
    
    return auto_clustered, queued


def evaluate_samples(auto_sample: list, queue_sample: list) -> tuple[dict, list, list]:
    """
    Evaluate sampled pairs using LLM validation.
    
    Returns: (metrics_dict, false_positive_samples, false_negative_samples)
    """
    logger.info(f"Evaluating {len(auto_sample)} auto-clustered pairs...")
    auto_tp = 0
    auto_fp = 0
    auto_total = 0
    auto_skipped = 0
    false_positives = []
    
    for pair in auto_sample:
        auto_total += 1
        is_same, response = validate_pair_with_llm(
            pair['emp1_name'], pair['emp1_city'], pair['emp1_state'],
            pair['emp2_name'], pair['emp2_city'], pair['emp2_state'],
            pair['similarity']
        )
        if is_same is None:
            auto_skipped += 1
            continue
        
        if is_same:
            auto_tp += 1
        else:
            auto_fp += 1
            false_positives.append({
                **pair,
                'llm_response': response,
                'reason': 'False positive - should not be clustered'
            })
    
    logger.info(f"Evaluating {len(queue_sample)} queued pairs...")
    queue_tp = 0
    queue_fp = 0
    queue_total = 0
    queue_skipped = 0
    false_negatives = []
    
    for pair in queue_sample:
        queue_total += 1
        is_same, response = validate_pair_with_llm(
            pair['emp1_name'], pair['emp1_city'], pair['emp1_state'],
            pair['emp2_name'], pair['emp2_city'], pair['emp2_state'],
            pair['similarity']
        )
        if is_same is None:
            queue_skipped += 1
            continue
        
        if is_same:
            queue_tp += 1
            false_negatives.append({
                **pair,
                'llm_response': response,
                'reason': 'False negative - should be clustered'
            })
        else:
            queue_fp += 1
    
    auto_precision = auto_tp / max(auto_total, 1)
    auto_recall = auto_tp / max(auto_tp + queue_tp, 1) if (auto_tp + queue_tp) > 0 else 0.0
    
    metrics = {
        'auto_clustered': {
            'total_evaluated': auto_total,
            'true_positives': auto_tp,
            'false_positives': auto_fp,
            'precision': auto_precision,
            'skipped': auto_skipped,
        },
        'queued_for_review': {
            'total_evaluated': queue_total,
            'true_negatives': queue_fp,
            'false_negatives': queue_tp,
            'skipped': queue_skipped,
        },
        'overall': {
            'precision': auto_precision,
            'recall': auto_recall,
            'f1_score': 2 * (auto_precision * auto_recall) / max(auto_precision + auto_recall, 0.001),
        }
    }
    
    return metrics, false_positives, false_negatives


def run_clustering(threshold: float, pairs_output: str, min_pairs: int, seed: int) -> bool:
    """Run clustering script and capture pairs. Stops early when enough pairs collected."""
    logger.info(f"Running clustering with threshold={threshold:.3f}...")
    logger.info(f"Early stopping: Will stop when {min_pairs:,} pairs collected")
    
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
    
    cmd = [
        'bazel', 'run', '//scripts/salary:cluster_existing_employers', '--',
        '--dry-run',
        '--threshold', str(threshold),
        '--pairs-output', pairs_output,
        '--min-pairs', str(min_pairs),  # Stop when we have enough pairs for sampling
        '--shuffle',  # Shuffle for random sampling
        '--shuffle-seed', str(seed),  # Reproducible randomness
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root))
    if result.returncode != 0:
        # Check if it's just early stopping (StopIteration)
        if "Enough pairs collected" in result.stderr or "Enough pairs collected" in result.stdout:
            logger.info("Early stopping triggered - enough pairs collected")
            return True
        logger.error(f"Clustering failed: {result.stderr}")
        return False
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Test clustering threshold and report precision/recall")
    parser.add_argument('--threshold', type=float, required=True, help='Threshold to test')
    parser.add_argument('--sample-size', type=int, default=500, help='Sample size per category')
    parser.add_argument('--min-pairs', type=int, default=1000, help='Minimum pairs to collect before stopping (default: 1000, should be ≥ sample_size*2)')
    parser.add_argument('--output-dir', default='/tmp/clustering_test', help='Output directory')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--show-all-samples', action='store_true', help='Show all false positive/negative samples')
    
    args = parser.parse_args()
    
    random.seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Run clustering (with early stopping)
    pairs_file = f"{args.output_dir}/pairs_threshold_{args.threshold:.3f}.jsonl"
    if not run_clustering(args.threshold, pairs_file, args.min_pairs, args.seed):
        return 1
    
    # Load pairs
    auto_clustered, queued = load_pairs_from_jsonl(pairs_file)
    logger.info(f"Found {len(auto_clustered):,} auto-clustered pairs")
    logger.info(f"Found {len(queued):,} queued pairs")
    
    if not auto_clustered and not queued:
        logger.error("No pairs found")
        return 1
    
    # Sample pairs
    auto_sample = random.sample(auto_clustered, min(args.sample_size, len(auto_clustered))) if auto_clustered else []
    queue_sample = random.sample(queued, min(args.sample_size, len(queued))) if queued else []
    
    logger.info(f"Sampled {len(auto_sample)} auto-clustered pairs")
    logger.info(f"Sampled {len(queue_sample)} queued pairs")
    
    # Check if LLM is available (required for validation)
    ollama_check = subprocess.run(["which", "ollama"], capture_output=True)
    if ollama_check.returncode != 0:
        logger.error("="*60)
        logger.error("ERROR: Ollama not found!")
        logger.error("LLM validation is required for meaningful precision measurement.")
        logger.error("Heuristic validation is circular (uses same thresholds we're testing).")
        logger.error("Install: brew install ollama && ollama pull llama3.2:3b")
        logger.error("="*60)
        return 1
    
    # Check if model is available
    model_check = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if "llama3.2:3b" not in model_check.stdout and "mistral" not in model_check.stdout:
        logger.warning("No suitable LLM model found. Pulling llama3.2:3b...")
        pull_result = subprocess.run(["ollama", "pull", "llama3.2:3b"], capture_output=True, text=True)
        if pull_result.returncode != 0:
            logger.error("Failed to pull model. Please run: ollama pull llama3.2:3b")
            return 1
    
    # Evaluate with LLM using parallel async HTTP API
    # Create evaluator with parallel processing enabled (default)
    template_path = Path(__file__).parent / 'llm_prompt_template.txt'
    
    evaluator = ClusteringEvaluator(
        llm_validator=None,  # None = use async HTTP API
        prompt_template_path=template_path,
        use_parallel=True,  # Enable parallel processing (2-4x faster)
        max_concurrent=4  # Match Ollama server parallel config
    )
    
    # Evaluator now handles dict pairs directly (converts internally for async)
    results = evaluator.evaluate_samples(auto_sample, queue_sample)
    metrics = results.metrics
    false_positives = results.false_positives
    false_negatives = results.false_negatives
    
    # Warn if too many samples were skipped (LLM unavailable)
    total_skipped = metrics['auto_clustered']['skipped'] + metrics['queued_for_review']['skipped']
    if total_skipped > len(auto_sample) * 0.1:  # More than 10% skipped
        logger.warning(f"WARNING: {total_skipped} samples skipped ({total_skipped/len(auto_sample)*100:.1f}%). "
                      f"Precision measurement may be unreliable.")
    
    # Print results
    print("\n" + "="*60)
    print(f"THRESHOLD TEST RESULTS (threshold={args.threshold:.3f})")
    print("="*60)
    print(f"\nSample Size:")
    print(f"  Auto-clustered: {len(auto_sample):,} pairs evaluated")
    print(f"  Queued: {len(queue_sample):,} pairs evaluated")
    print(f"\nMetrics:")
    print(f"  Precision: {metrics['overall']['precision']:.2%}")
    print(f"  Recall: {metrics['overall']['recall']:.2%}")
    print(f"  F1 Score: {metrics['overall']['f1_score']:.3f}")
    print(f"\nAuto-Clustered Breakdown:")
    print(f"  True positives: {metrics['auto_clustered']['true_positives']}")
    print(f"  False positives: {metrics['auto_clustered']['false_positives']}")
    print(f"  Skipped: {metrics['auto_clustered']['skipped']}")
    print(f"\nQueued Breakdown:")
    print(f"  True negatives: {metrics['queued_for_review']['true_negatives']}")
    print(f"  False negatives: {metrics['queued_for_review']['false_negatives']}")
    print(f"  Skipped: {metrics['queued_for_review']['skipped']}")
    print(f"\nTotal Pairs:")
    print(f"  Auto-clustered: {len(auto_clustered):,}")
    print(f"  Queued: {len(queued):,}")
    
    # Show false positives
    if false_positives:
        print(f"\n{'='*60}")
        print(f"FALSE POSITIVES ({len(false_positives)} found):")
        print("="*60)
        max_show = len(false_positives) if args.show_all_samples else 20
        for i, fp in enumerate(false_positives[:max_show], 1):
            print(f"\n{i}. {fp['emp1_name']} <-> {fp['emp2_name']}")
            print(f"   Similarity: {fp['similarity']:.3f}")
            print(f"   Location 1: {fp['emp1_city']}, {fp['emp1_state']}")
            print(f"   Location 2: {fp['emp2_city']}, {fp['emp2_state']}")
            if fp.get('llm_response'):
                print(f"   LLM: {fp['llm_response'][:200]}")
        if len(false_positives) > max_show:
            print(f"\n... and {len(false_positives) - max_show} more")
    else:
        print(f"\n✓ No false positives found!")
    
    # Show false negatives
    if false_negatives:
        print(f"\n{'='*60}")
        print(f"FALSE NEGATIVES ({len(false_negatives)} found):")
        print("="*60)
        max_show = len(false_negatives) if args.show_all_samples else 20
        for i, fn in enumerate(false_negatives[:max_show], 1):
            print(f"\n{i}. {fn['emp1_name']} <-> {fn['emp2_name']}")
            print(f"   Similarity: {fn['similarity']:.3f}")
            print(f"   Location 1: {fn['emp1_city']}, {fn['emp1_state']}")
            print(f"   Location 2: {fn['emp2_city']}, {fn['emp2_state']}")
            if fn.get('llm_response'):
                print(f"   LLM: {fn['llm_response'][:200]}")
        if len(false_negatives) > max_show:
            print(f"\n... and {len(false_negatives) - max_show} more")
    else:
        print(f"\n✓ No false negatives found!")
    
    print("\n" + "="*60)
    
    # Save results JSON
    result_file = f"{args.output_dir}/results_threshold_{args.threshold:.3f}.json"
    with open(result_file, 'w') as f:
        json.dump({
            'threshold': args.threshold,
            'metrics': metrics,
            'total_auto_clustered': len(auto_clustered),
            'total_queued': len(queued),
            'sample_size': {
                'auto_clustered': len(auto_sample),
                'queued': len(queue_sample),
            },
            'false_positives': false_positives,
            'false_negatives': false_negatives,
        }, f, indent=2)
    
    print(f"Results saved to: {result_file}")
    
    # Save false positives MD file
    if false_positives:
        md_file = f"{args.output_dir}/false_positives_threshold_{args.threshold:.3f}.md"
        with open(md_file, 'w') as f:
            f.write(f"# False Positives - Threshold {args.threshold:.3f}\n\n")
            f.write(f"**Total False Positives:** {len(false_positives)}\n\n")
            f.write(f"Generated from evaluation with sample size: {len(auto_sample)} auto-clustered pairs\n\n")
            f.write("---\n\n")
            
            for i, fp in enumerate(false_positives, 1):
                f.write(f"## False Positive {i}\n\n")
                f.write(f"**Employer 1:** {fp['emp1_name']}\n")
                f.write(f"- Location: {fp.get('emp1_city', 'N/A')}, {fp.get('emp1_state', 'N/A')}\n\n")
                f.write(f"**Employer 2:** {fp['emp2_name']}\n")
                f.write(f"- Location: {fp.get('emp2_city', 'N/A')}, {fp.get('emp2_state', 'N/A')}\n\n")
                f.write(f"**Similarity Score:** {fp['similarity']:.3f}\n\n")
                if fp.get('llm_response'):
                    f.write(f"**LLM Response:**\n```\n{fp['llm_response']}\n```\n\n")
                f.write("---\n\n")
        
        print(f"False positives saved to: {md_file}")
    else:
        print("No false positives to save.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

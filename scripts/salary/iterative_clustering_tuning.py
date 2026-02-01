#!/usr/bin/env python3
"""
Iterative clustering tuning to achieve 99% precision.

Process:
1. Run clustering (dry-run) with current thresholds
2. Sample pairs and evaluate with LLM
3. Compute precision/recall metrics
4. Adjust thresholds/logic based on results
5. Repeat 3-4 times
6. Produce final report
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

# Setup Django - must be done before any model imports
# Add project root to path first
if 'BUILD_WORKSPACE_DIRECTORY' in os.environ:
    project_root = Path(os.environ['BUILD_WORKSPACE_DIRECTORY'])
else:
    # Fallback: find project root by looking for BUILD file
    current = Path(__file__).parent
    while current != current.parent:
        if (current / 'BUILD').exists() or (current / 'MODULE.bazel').exists():
            project_root = current
            break
        current = current.parent
    else:
        project_root = Path(__file__).parent.parent.parent

sys.path.insert(0, str(project_root))

# Setup Django environment and initialize
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django
django.setup()

# Now safe to import models (Django is fully initialized)
# Use get_model to avoid triggering models/__init__.py imports during Django setup
from django.apps import apps
Employer = apps.get_model('models', 'Employer')

from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def call_ollama(prompt: str, model: str = "llama3.2:3b", max_retries: int = 3) -> Optional[str]:
    """Call Ollama LLM with prompt and return response. Uses exponential backoff for retries."""
    try:
        # Check if ollama is available
        result = subprocess.run(["which", "ollama"], capture_output=True)
        if result.returncode != 0:
            logger.warning("Ollama not found. Install from https://ollama.ai/ or use --skip-llm")
            return None
        
        # Exponential backoff: start with 5s, double each retry (5s, 10s, 20s)
        base_timeout = 5
        for attempt in range(max_retries):
            timeout = base_timeout * (2 ** attempt)
            try:
                result = subprocess.run(
                    ["ollama", "run", model, prompt],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False
                )
                if result.returncode == 0:
                    return result.stdout.strip()
                elif attempt < max_retries - 1:
                    wait_time = min(2 ** attempt, 10)  # Cap at 10s
                    logger.debug(f"Ollama call failed, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
            except subprocess.TimeoutExpired:
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt, 10)
                    logger.debug(f"Ollama call timed out, retrying with longer timeout in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    logger.warning(f"Ollama call timed out after {max_retries} attempts")
        return None
    except FileNotFoundError:
        logger.warning("Ollama not found. Install from https://ollama.ai/ or use --skip-llm")
        return None
    except Exception as e:
        logger.warning(f"Ollama call error: {e}")
        return None


def validate_pair_with_llm(emp1_name: str, emp1_city: str, emp1_state: str,
                           emp2_name: str, emp2_city: str, emp2_state: str,
                           similarity: float, skip_llm: bool = False) -> tuple[Optional[bool], Optional[str]]:
    """Use LLM to validate if two employers are the same company."""
    if skip_llm:
        # Fallback: Use similarity threshold heuristic
        # For high similarity (>0.95), assume same company
        # For lower similarity, assume different
        if similarity >= 0.95:
            return True, "High similarity heuristic (LLM unavailable)"
        elif similarity < 0.85:
            return False, "Low similarity heuristic (LLM unavailable)"
        else:
            # Ambiguous - return None to skip
            return None, "Ambiguous similarity (LLM unavailable)"
    
    prompt = f"""Are these two employer names referring to the same company?

Name 1: {emp1_name}
Location 1: {emp1_city}, {emp1_state}

Name 2: {emp2_name}
Location 2: {emp2_city}, {emp2_state}

Similarity score: {similarity:.3f}

Answer with only "YES" or "NO" followed by a brief explanation."""
    
    response = call_ollama(prompt)
    if not response:
        return None, None
    
    response_upper = response.upper()
    is_same = response_upper.startswith("YES")
    
    return is_same, response


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


def evaluate_samples(auto_sample: list, queue_sample: list, skip_llm: bool = False) -> tuple[dict, list, list]:
    """
    Evaluate sampled pairs using LLM validation.
    
    Returns: (metrics_dict, false_positive_samples, false_negative_samples)
    """
    logger.info(f"Evaluating {len(auto_sample)} auto-clustered pairs...")
    auto_tp = 0
    auto_fp = 0
    auto_total = 0
    auto_skipped = 0
    false_positives = []  # Store FP samples
    
    for pair in auto_sample:
        auto_total += 1
        is_same, response = validate_pair_with_llm(
            pair['emp1_name'], pair['emp1_city'], pair['emp1_state'],
            pair['emp2_name'], pair['emp2_city'], pair['emp2_state'],
            pair['similarity'],
            skip_llm=skip_llm
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
            logger.warning(f"✗ FP: {pair['emp1_name']} <-> {pair['emp2_name']} (similarity: {pair['similarity']:.3f})")
    
    logger.info(f"Evaluating {len(queue_sample)} queued pairs...")
    queue_tp = 0  # Should have been clustered (false negatives)
    queue_fp = 0  # Correctly queued (true negatives)
    queue_total = 0
    queue_skipped = 0
    false_negatives = []  # Store FN samples
    
    for pair in queue_sample:
        queue_total += 1
        is_same, response = validate_pair_with_llm(
            pair['emp1_name'], pair['emp1_city'], pair['emp1_state'],
            pair['emp2_name'], pair['emp2_city'], pair['emp2_state'],
            pair['similarity'],
            skip_llm=skip_llm
        )
        if is_same is None:
            queue_skipped += 1
            continue
        
        if is_same:
            queue_tp += 1  # False negative
            false_negatives.append({
                **pair,
                'llm_response': response,
                'reason': 'False negative - should be clustered'
            })
        else:
            queue_fp += 1  # True negative
    
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


def suggest_threshold_adjustment(metrics: dict, current_threshold: float, target_precision: float = 0.99) -> float:
    """
    Suggest new threshold based on metrics to achieve target precision (default 99%).
    
    Strategy:
    - If precision > target: Lower threshold to improve recall (but stay above target)
    - If precision < target: Raise threshold to improve precision
    - If precision == target: Fine-tune to stay at target
    """
    precision = metrics['overall']['precision']
    fp_count = metrics['auto_clustered']['false_positives']
    total_evaluated = metrics['auto_clustered']['total_evaluated']
    
    # Calculate precision with confidence interval (Wilson score interval approximation)
    # For small sample sizes, be more conservative
    if total_evaluated < 100:
        # With small samples, precision estimates are unreliable
        # Be conservative - if we see any FPs, assume precision is lower
        if fp_count > 0:
            estimated_precision = (total_evaluated - fp_count) / total_evaluated
        else:
            # No FPs observed, but sample too small to be confident
            estimated_precision = 0.99  # Assume we're at target, don't change much
    else:
        estimated_precision = precision
    
    precision_gap = target_precision - estimated_precision
    
    if abs(precision_gap) < 0.005:  # Within 0.5% of target
        # At target - fine-tune to stay there
        return current_threshold
    
    if precision > target_precision:
        # Precision too high - lower threshold to improve recall
        # Lower by amount proportional to how much we're above target
        excess = precision - target_precision
        threshold_decrease = min(0.02, excess * 0.05)  # Conservative decrease
        return max(0.85, current_threshold - threshold_decrease)
    else:
        # Precision too low - raise threshold
        # Raise by amount proportional to precision gap
        threshold_increase = min(0.05, abs(precision_gap) * 0.1)
        return min(1.0, current_threshold + threshold_increase)


def run_clustering(threshold: float, pairs_output: str) -> bool:
    """Run clustering script and capture pairs."""
    logger.info(f"Running clustering with threshold={threshold:.3f}...")
    
    # Get project root
    if 'BUILD_WORKSPACE_DIRECTORY' in os.environ:
        project_root = Path(os.environ['BUILD_WORKSPACE_DIRECTORY'])
    else:
        # Fallback: find project root
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
        '--pairs-output', pairs_output
    ]
    
    # Run from project root to avoid bazel directory issues
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root))
    if result.returncode != 0:
        logger.error(f"Clustering failed: {result.stderr}")
        return False
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Iterative clustering tuning for 99% precision")
    parser.add_argument('--iterations', type=int, default=4, help='Number of iterations')
    parser.add_argument('--sample-size', type=int, default=500, help='Sample size per category (default: 500 for 99% precision measurement)')
    parser.add_argument('--initial-threshold', type=float, default=0.95, help='Initial threshold')
    parser.add_argument('--target-precision', type=float, default=0.99, help='Target precision (default: 0.99)')
    parser.add_argument('--output-dir', default='/tmp/clustering_tuning', help='Output directory')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--skip-llm', action='store_true', help='Skip LLM validation, use heuristics instead')
    parser.add_argument('--max-runtime', type=int, default=600, help='Maximum runtime in seconds (default: 600 = 10 min)')
    
    args = parser.parse_args()
    
    random.seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)
    
    iterations = []
    current_threshold = args.initial_threshold
    start_time = time.time()
    
    for iteration in range(1, args.iterations + 1):
        # Check runtime limit
        elapsed = time.time() - start_time
        if elapsed > args.max_runtime:
            logger.warning(f"Maximum runtime ({args.max_runtime}s) reached. Stopping after {iteration - 1} iterations.")
            break
        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {iteration}/{args.iterations}")
        logger.info(f"{'='*60}")
        logger.info(f"Current threshold: {current_threshold:.3f}")
        
        # Run clustering
        pairs_file = f"{args.output_dir}/pairs_iter{iteration}.jsonl"
        if not run_clustering(current_threshold, pairs_file):
            logger.error("Clustering failed, stopping")
            break
        
        # Load pairs
        auto_clustered, queued = load_pairs_from_jsonl(pairs_file)
        logger.info(f"Found {len(auto_clustered):,} auto-clustered pairs")
        logger.info(f"Found {len(queued):,} queued pairs")
        
        if not auto_clustered and not queued:
            logger.warning("No pairs found, stopping")
            break
        
        # Sample pairs
        auto_sample = random.sample(auto_clustered, min(args.sample_size, len(auto_clustered))) if auto_clustered else []
        queue_sample = random.sample(queued, min(args.sample_size, len(queued))) if queued else []
        
        # Evaluate
        metrics, false_positives, false_negatives = evaluate_samples(
            auto_sample, queue_sample, skip_llm=args.skip_llm
        )
        
        # Print results
        print(f"\nIteration {iteration} Results:")
        print(f"  Precision: {metrics['overall']['precision']:.1%} (target: {args.target_precision:.1%})")
        print(f"  Recall: {metrics['overall']['recall']:.1%}")
        print(f"  F1 Score: {metrics['overall']['f1_score']:.3f}")
        print(f"  Auto-clustered: {metrics['auto_clustered']['true_positives']}/{metrics['auto_clustered']['total_evaluated']} correct")
        print(f"  False positives: {metrics['auto_clustered']['false_positives']}")
        print(f"  False negatives: {metrics['queued_for_review']['false_negatives']}")
        
        # Show sample false positives if any
        if false_positives:
            print(f"\n  False Positive Examples (showing first 5):")
            for fp in false_positives[:5]:
                print(f"    - {fp['emp1_name']} <-> {fp['emp2_name']} (similarity: {fp['similarity']:.3f})")
        
        # Show sample false negatives if any
        if false_negatives:
            print(f"\n  False Negative Examples (showing first 5):")
            for fn in false_negatives[:5]:
                print(f"    - {fn['emp1_name']} <-> {fn['emp2_name']} (similarity: {fn['similarity']:.3f})")
        
        # Save iteration results (including samples)
        iteration_data = {
            'iteration': iteration,
            'threshold': current_threshold,
            'metrics': metrics,
            'total_auto_clustered': len(auto_clustered),
            'total_queued': len(queued),
            'false_positive_samples': false_positives,
            'false_negative_samples': false_negatives,
            'auto_sample_size': len(auto_sample),
            'queue_sample_size': len(queue_sample),
        }
        iterations.append(iteration_data)
        
        # Check if we've reached target precision (within 0.5% tolerance)
        precision = metrics['overall']['precision']
        if abs(precision - args.target_precision) <= 0.005 and iteration >= 2:
            logger.info(f"✓ Target precision ({args.target_precision:.1%}) achieved after {iteration} iterations!")
            logger.info(f"  Precision: {precision:.1%} (target: {args.target_precision:.1%}, tolerance: ±0.5%)")
            break
        elif precision >= args.target_precision:
            logger.info(f"✓ Target precision ({args.target_precision:.1%}) achieved, but continuing to validate...")
        
        # Suggest new threshold
        new_threshold = suggest_threshold_adjustment(metrics, current_threshold, target_precision=args.target_precision)
        logger.info(f"Suggested new threshold: {new_threshold:.3f} (current: {current_threshold:.3f})")
        current_threshold = new_threshold
        
        # Exponential backoff between iterations: 1s, 2s, 4s, 8s (capped at 10s)
        # This gives system time to recover while not waiting too long
        wait_time = min(2 ** (iteration - 1), 10)
        if iteration < args.iterations:
            # Check if we have time left
            elapsed = time.time() - start_time
            remaining = args.max_runtime - elapsed
            if remaining < wait_time + 60:  # Need at least 60s for next iteration
                logger.warning(f"Not enough time remaining ({remaining:.0f}s). Stopping early.")
                break
            logger.debug(f"Waiting {wait_time}s before next iteration...")
            time.sleep(wait_time)
    
    # Generate final report
    report_file = f"{args.output_dir}/tuning_report.json"
    with open(report_file, 'w') as f:
        json.dump({
            'iterations': iterations,
            'final_threshold': current_threshold,
            'final_metrics': iterations[-1]['metrics'] if iterations else None,
        }, f, indent=2)
    
    # Print summary
    print(f"\n{'='*60}")
    print("FINAL REPORT")
    print(f"{'='*60}")
    if iterations:
        final = iterations[-1]
        print(f"Final threshold: {final['threshold']:.3f}")
        print(f"Final precision: {final['metrics']['overall']['precision']:.1%} (target: {args.target_precision:.1%})")
        print(f"Final recall: {final['metrics']['overall']['recall']:.1%}")
        print(f"Total auto-clustered: {final['total_auto_clustered']:,}")
        print(f"Total queued: {final['total_queued']:,}")
        print(f"\nSample size used: {final['auto_sample_size']} auto-clustered, {final['queue_sample_size']} queued")
        
        # Show false positives from final iteration
        if final.get('false_positive_samples'):
            print(f"\nFalse Positives in Final Iteration ({len(final['false_positive_samples'])}):")
            for fp in final['false_positive_samples'][:10]:  # Show first 10
                print(f"  - {fp['emp1_name']} <-> {fp['emp2_name']} (similarity: {fp['similarity']:.3f})")
        
        # Show false negatives from final iteration
        if final.get('false_negative_samples'):
            print(f"\nFalse Negatives in Final Iteration ({len(final['false_negative_samples'])}):")
            for fn in final['false_negative_samples'][:10]:  # Show first 10
                print(f"  - {fn['emp1_name']} <-> {fn['emp2_name']} (similarity: {fn['similarity']:.3f})")
    print(f"\nFull report saved to: {report_file}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())










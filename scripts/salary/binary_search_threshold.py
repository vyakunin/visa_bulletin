#!/usr/bin/env python3
"""
Automated binary search to find clustering threshold that achieves target precision.

Uses binary search algorithm to efficiently find the threshold where precision ≈ target_precision.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Setup Django FIRST (before any imports that might trigger model imports)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

# Add project root to path
if "BUILD_WORKSPACE_DIRECTORY" in os.environ:
    project_root = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
else:
    current = Path(__file__).parent
    while current != current.parent:
        if (current / "BUILD").exists() or (current / "MODULE.bazel").exists():
            project_root = current
            break
        current = current.parent
    else:
        project_root = Path(__file__).parent.parent.parent

sys.path.insert(0, str(project_root))

import django

django.setup()

from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def test_threshold(
    threshold: float, sample_size: int, min_pairs: int, output_dir: Path, seed: int
) -> dict | None:
    """
    Test a single threshold and return precision metrics.

    Returns:
        dict with precision and metrics, or None if test failed
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Testing threshold: {threshold:.4f}")
    logger.info(f"{'=' * 60}")

    # Run threshold evaluation
    result_file = output_dir / f"results_threshold_{threshold:.4f}.json"

    # Check if we already have results for this threshold
    if result_file.exists():
        logger.info(f"Found existing results for threshold {threshold:.4f}, loading...")
        try:
            with open(result_file) as f:
                data = json.load(f)
                precision = data["metrics"]["overall"]["precision"]
                logger.info(f"Loaded: Precision = {precision:.2%}")
                return {
                    "threshold": threshold,
                    "precision": precision,
                    "metrics": data["metrics"],
                    "result_file": str(result_file),
                }
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load existing results: {e}, re-running test...")

    # Run evaluation script
    cmd = [
        "bazel",
        "run",
        "//scripts/salary:evaluate_clustering_threshold",
        "--",
        "--threshold",
        str(threshold),
        "--sample-size",
        str(sample_size),
        "--min-pairs",
        str(min_pairs),
        "--output-dir",
        str(output_dir),
        "--seed",
        str(seed),
    ]

    logger.info(f"Running: {' '.join(cmd)}")
    start_time = time.time()

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_root))

    elapsed = time.time() - start_time

    if result.returncode != 0:
        logger.error(f"Threshold test failed (exit code {result.returncode})")
        logger.error(f"stderr: {result.stderr[:500]}")
        return None

    # Load results
    if not result_file.exists():
        logger.error(f"Results file not found: {result_file}")
        return None

    try:
        with open(result_file) as f:
            data = json.load(f)

        precision = data["metrics"]["overall"]["precision"]
        fp_count = data["metrics"]["auto_clustered"]["false_positives"]
        tp_count = data["metrics"]["auto_clustered"]["true_positives"]

        logger.info(
            f"✓ Threshold {threshold:.4f}: Precision = {precision:.2%} "
            f"(TP={tp_count}, FP={fp_count}) - {elapsed:.1f}s"
        )

        return {
            "threshold": threshold,
            "precision": precision,
            "metrics": data["metrics"],
            "result_file": str(result_file),
            "elapsed_seconds": elapsed,
        }
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse results: {e}")
        return None


def binary_search_threshold(
    target_precision: float,
    sample_size: int,
    min_pairs: int,
    output_dir: Path,
    seed: int,
    low: float = 0.50,
    high: float = 1.00,
    convergence_threshold: float = 0.01,
    max_iterations: int = 20,
) -> dict | None:
    """
    Perform binary search to find threshold achieving target precision.

    Returns:
        dict with optimal threshold and metrics, or None if search failed
    """
    logger.info("\n" + "=" * 60)
    logger.info("BINARY SEARCH FOR OPTIMAL THRESHOLD")
    logger.info("=" * 60)
    logger.info(f"Target precision: {target_precision:.1%}")
    logger.info(f"Search range: [{low:.3f}, {high:.3f}]")
    logger.info(f"Convergence threshold: {convergence_threshold:.3f}")
    logger.info(f"Sample size: {sample_size}")
    logger.info("=" * 60)

    # Check if Ollama is available
    ollama_check = subprocess.run(["which", "ollama"], capture_output=True)
    if ollama_check.returncode != 0:
        logger.error("=" * 60)
        logger.error("ERROR: Ollama not found!")
        logger.error("LLM validation is required for meaningful precision measurement.")
        logger.error("Install: brew install ollama && ollama pull llama3.2:3b")
        logger.error("=" * 60)
        return None

    iteration = 0
    best_result = None
    best_precision_diff = float("inf")

    while iteration < max_iterations:
        iteration += 1

        # Check convergence
        if high - low < convergence_threshold:
            logger.info(f"\n✓ Converged after {iteration - 1} iterations")
            logger.info(
                f"  Final range: [{low:.4f}, {high:.4f}] (width: {high - low:.4f})"
            )
            break

        # Test midpoint
        mid = (low + high) / 2

        logger.info(f"\n--- Iteration {iteration} ---")
        logger.info(f"Testing threshold: {mid:.4f} (range: [{low:.4f}, {high:.4f}])")

        result = test_threshold(mid, sample_size, min_pairs, output_dir, seed)

        if result is None:
            logger.error(f"Failed to test threshold {mid:.4f}, aborting search")
            return None

        precision = result["precision"]
        precision_diff = abs(precision - target_precision)

        # Track best result so far
        if precision_diff < best_precision_diff:
            best_precision_diff = precision_diff
            best_result = result

        # Update bounds based on precision
        if precision > target_precision:
            # Precision too high → threshold too high → lower it
            high = mid
            logger.info(
                f"Precision {precision:.2%} > target {target_precision:.1%} → "
                f"threshold too high, lowering to [{low:.4f}, {high:.4f}]"
            )
        elif precision < target_precision:
            # Precision too low → threshold too low → raise it
            low = mid
            logger.info(
                f"Precision {precision:.2%} < target {target_precision:.1%} → "
                f"threshold too low, raising to [{low:.4f}, {high:.4f}]"
            )
        else:
            # Exact match (unlikely but possible)
            logger.info(
                f"✓ Exact match! Precision = {precision:.2%} at threshold {mid:.4f}"
            )
            return result

    if iteration >= max_iterations:
        logger.warning(f"\n⚠ Reached max iterations ({max_iterations})")
        logger.warning(
            f"  Final range: [{low:.4f}, {high:.4f}] (width: {high - low:.4f})"
        )

    # Return best result found
    if best_result:
        logger.info(
            f"\n✓ Best result: threshold {best_result['threshold']:.4f} "
            f"with precision {best_result['precision']:.2%} "
            f"(diff: {abs(best_result['precision'] - target_precision):.2%})"
        )
        return best_result
    else:
        logger.error("No valid results found")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Binary search for clustering threshold achieving target precision"
    )
    parser.add_argument(
        "--target-precision",
        type=float,
        default=0.99,
        help="Target precision (default: 0.99 = 99%%)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=500,
        help="Sample size per category for evaluation (default: 500)",
    )
    parser.add_argument(
        "--min-pairs",
        type=int,
        default=1000,
        help="Minimum pairs to collect before stopping (default: 1000, should be ≥ sample_size*2)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/threshold_search"),
        help="Output directory for results (default: /tmp/threshold_search)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--low", type=float, default=0.50, help="Lower bound for search (default: 0.50)"
    )
    parser.add_argument(
        "--high",
        type=float,
        default=1.00,
        help="Upper bound for search (default: 1.00)",
    )
    parser.add_argument(
        "--convergence-threshold",
        type=float,
        default=0.01,
        help="Stop when search range < this value (default: 0.01)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="Maximum iterations (default: 20)",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.low >= args.high:
        logger.error(f"Invalid search range: low ({args.low}) >= high ({args.high})")
        return 1

    if args.target_precision <= 0 or args.target_precision >= 1:
        logger.error(
            f"Invalid target precision: {args.target_precision} (must be 0 < p < 1)"
        )
        return 1

    if args.min_pairs < args.sample_size * 2:
        logger.warning(
            f"min_pairs ({args.min_pairs}) < sample_size*2 ({args.sample_size * 2})"
        )
        logger.warning("Consider increasing min_pairs for better sampling")

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Run binary search
    start_time = time.time()
    result = binary_search_threshold(
        target_precision=args.target_precision,
        sample_size=args.sample_size,
        min_pairs=args.min_pairs,
        output_dir=args.output_dir,
        seed=args.seed,
        low=args.low,
        high=args.high,
        convergence_threshold=args.convergence_threshold,
        max_iterations=args.max_iterations,
    )
    total_elapsed = time.time() - start_time

    # Print final summary
    print("\n" + "=" * 60)
    print("BINARY SEARCH SUMMARY")
    print("=" * 60)

    if result:
        print(f"✓ Optimal threshold: {result['threshold']:.4f}")
        print(f"  Precision: {result['precision']:.2%}")
        print(f"  Target: {args.target_precision:.1%}")
        print(f"  Difference: {abs(result['precision'] - args.target_precision):.2%}")

        metrics = result["metrics"]
        print("\nDetailed Metrics:")
        print("  Auto-clustered:")
        print(f"    True positives: {metrics['auto_clustered']['true_positives']}")
        print(f"    False positives: {metrics['auto_clustered']['false_positives']}")
        print(f"    Precision: {metrics['auto_clustered']['precision']:.2%}")
        print("  Overall:")
        print(f"    Precision: {metrics['overall']['precision']:.2%}")
        print(f"    Recall: {metrics['overall']['recall']:.2%}")
        print(f"    F1 Score: {metrics['overall']['f1_score']:.3f}")

        print(f"\nResults saved to: {result['result_file']}")
    else:
        print("✗ Binary search failed - no optimal threshold found")
        print("  Check logs above for errors")
        return 1

    print(f"\nTotal time: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())

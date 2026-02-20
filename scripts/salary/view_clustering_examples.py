#!/usr/bin/env python3
"""
View clustering examples in a human-readable format.

Converts JSONL format to a readable table/markdown format for easy review.
"""

import argparse
import json

# Setup Django (for potential future use with database)
import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import logging

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def load_examples(jsonl_file: Path) -> list[dict]:
    """Load examples from JSONL file."""
    examples = []
    with open(jsonl_file) as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                example = json.loads(line)
                example["_line_num"] = line_num  # Track line number for reference
                examples.append(example)
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON on line {line_num}: {e}")
                continue
    return examples


def format_example(example: dict, index: int, show_details: bool = True) -> str:
    """
    Format a single example as human-readable text.

    Returns a formatted string showing the example in a readable way.
    """
    lines = []

    # Header with index and type
    example_type = example.get("type", "unknown")
    ground_truth = example.get("ground_truth", "unknown")

    # Color/icon based on type and ground truth
    type_icon = {
        "reviewed": "✓",
        "auto_clustered": "⚙",
        "different_companies": "✗",
    }.get(example_type, "?")

    truth_icon = {
        "same": "✅",
        "different": "❌",
    }.get(ground_truth, "❓")

    lines.append(f"\n{'=' * 80}")
    lines.append(
        f"Example #{index} {type_icon} [{example_type}] {truth_icon} [{ground_truth}]"
    )
    lines.append(f"{'=' * 80}")

    # Employer 1
    emp1_name = example.get("emp1_name", "N/A")
    emp1_city = example.get("emp1_city", "")
    emp1_state = example.get("emp1_state", "")
    emp1_location = f"{emp1_city}, {emp1_state}".strip(", ")

    lines.append("\nEmployer 1:")
    lines.append(f"  Name:     {emp1_name}")
    if emp1_location:
        lines.append(f"  Location: {emp1_location}")

    # Employer 2
    emp2_name = example.get("emp2_name", "N/A")
    emp2_city = example.get("emp2_city", "")
    emp2_state = example.get("emp2_state", "")
    emp2_location = f"{emp2_city}, {emp2_state}".strip(", ")

    lines.append("\nEmployer 2:")
    lines.append(f"  Name:     {emp2_name}")
    if emp2_location:
        lines.append(f"  Location: {emp2_location}")

    # Key metrics
    similarity = example.get("similarity")
    if similarity is not None:
        lines.append(f"\nSimilarity: {similarity:.3f}")

    # Additional details if requested
    if show_details:
        if example.get("cluster_id"):
            lines.append(f"Cluster ID: {example.get('cluster_id')}")
        if example.get("canonical_name"):
            lines.append(f"Canonical:  {example.get('canonical_name')}")
        if example.get("reviewed_by"):
            lines.append(f"Reviewed by: {example.get('reviewed_by')}")
        if example.get("match_reason"):
            lines.append(f"Reason:      {example.get('match_reason')}")
        if example.get("notes"):
            lines.append(f"Notes:       {example.get('notes')}")

    return "\n".join(lines)


def format_summary_table(examples: list[dict]) -> str:
    """Format a summary table of all examples."""
    lines = []

    lines.append("\n" + "=" * 120)
    lines.append("GOLDEN SET SUMMARY")
    lines.append("=" * 120)

    # Count by type
    by_type = {}
    by_truth = {}
    for ex in examples:
        ex_type = ex.get("type", "unknown")
        truth = ex.get("ground_truth", "unknown")
        by_type[ex_type] = by_type.get(ex_type, 0) + 1
        by_truth[truth] = by_truth.get(truth, 0) + 1

    lines.append(f"\nTotal Examples: {len(examples)}")
    lines.append("\nBy Type:")
    for ex_type, count in sorted(by_type.items()):
        lines.append(f"  {ex_type:20s}: {count:4d}")

    lines.append("\nBy Ground Truth:")
    for truth, count in sorted(by_truth.items()):
        lines.append(f"  {truth:20s}: {count:4d}")

    lines.append("\n" + "=" * 120)

    return "\n".join(lines)


def format_markdown_table(examples: list[dict]) -> str:
    """Format examples as a Markdown table."""
    lines = []

    lines.append("\n# Clustering Examples\n")
    lines.append(
        "| # | Type | Truth | Similarity | Employer 1 | Employer 2 | Location 1 | Location 2 |"
    )
    lines.append(
        "|---|------|-------|------------|-------------|------------|-----------|-------------|"
    )

    for i, ex in enumerate(examples, 1):
        ex_type = ex.get("type", "unknown")
        truth = ex.get("ground_truth", "unknown")
        similarity = ex.get("similarity", 0.0)
        sim_str = f"{similarity:.3f}" if similarity is not None else "N/A"

        emp1 = ex.get("emp1_name", "N/A").replace("|", "\\|")
        emp2 = ex.get("emp2_name", "N/A").replace("|", "\\|")

        loc1 = f"{ex.get('emp1_city', '')}, {ex.get('emp1_state', '')}".strip(", ")
        loc2 = f"{ex.get('emp2_city', '')}, {ex.get('emp2_state', '')}".strip(", ")

        lines.append(
            f"| {i} | {ex_type} | {truth} | {sim_str} | {emp1} | {emp2} | {loc1} | {loc2} |"
        )

    return "\n".join(lines)


def format_compact_table(examples: list[dict], max_width: int = 120) -> str:
    """Format examples as a compact table."""
    lines = []

    lines.append("\n" + "=" * max_width)
    lines.append("EXAMPLES (Compact View)")
    lines.append("=" * max_width)

    # Table header
    header = f"{'#':<4} {'Type':<15} {'Truth':<8} {'Similarity':<10} {'Employer 1':<35} {'Employer 2':<35}"
    lines.append(header)
    lines.append("-" * max_width)

    # Table rows
    for i, ex in enumerate(examples, 1):
        ex_type = ex.get("type", "unknown")[:14]
        truth = ex.get("ground_truth", "unknown")[:7]
        similarity = ex.get("similarity", 0.0)
        sim_str = f"{similarity:.3f}" if similarity is not None else "N/A"

        emp1 = ex.get("emp1_name", "N/A")[:34]
        emp2 = ex.get("emp2_name", "N/A")[:34]

        row = f"{i:<4} {ex_type:<15} {truth:<8} {sim_str:<10} {emp1:<35} {emp2:<35}"
        lines.append(row)

    lines.append("=" * max_width)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="View clustering examples in human-readable format"
    )
    parser.add_argument("examples_file", type=Path, help="JSONL file with examples")
    parser.add_argument(
        "--format",
        choices=["detailed", "compact", "summary", "markdown", "all"],
        default="all",
        help="Output format (default: all)",
    )
    parser.add_argument(
        "--filter-type",
        choices=["reviewed", "auto_clustered", "different_companies"],
        help="Filter by example type",
    )
    parser.add_argument(
        "--filter-truth", choices=["same", "different"], help="Filter by ground truth"
    )
    parser.add_argument("--limit", type=int, help="Limit number of examples to display")
    parser.add_argument(
        "--min-similarity", type=float, help="Minimum similarity score to include"
    )
    parser.add_argument(
        "--max-similarity", type=float, help="Maximum similarity score to include"
    )
    parser.add_argument("--output", type=Path, help="Output file (default: stdout)")

    args = parser.parse_args()

    # Log execution
    script_logger.log_call(
        args=vars(args), context="Viewing clustering examples in human-readable format"
    )

    # Load examples
    if not args.examples_file.exists():
        logger.error(f"Examples file not found: {args.examples_file}")
        sys.exit(1)

    logger.info(f"Loading examples from {args.examples_file}...")
    examples = load_examples(args.examples_file)
    logger.info(f"Loaded {len(examples)} examples")

    # Apply filters
    if args.filter_type:
        examples = [ex for ex in examples if ex.get("type") == args.filter_type]
        logger.info(f"After type filter: {len(examples)} examples")

    if args.filter_truth:
        examples = [
            ex for ex in examples if ex.get("ground_truth") == args.filter_truth
        ]
        logger.info(f"After truth filter: {len(examples)} examples")

    if args.min_similarity is not None:
        examples = [
            ex
            for ex in examples
            if ex.get("similarity") is not None
            and ex.get("similarity") >= args.min_similarity
        ]
        logger.info(f"After min similarity filter: {len(examples)} examples")

    if args.max_similarity is not None:
        examples = [
            ex
            for ex in examples
            if ex.get("similarity") is not None
            and ex.get("similarity") <= args.max_similarity
        ]
        logger.info(f"After max similarity filter: {len(examples)} examples")

    # Apply limit
    if args.limit and args.limit < len(examples):
        examples = examples[: args.limit]
        logger.info(f"Limited to {len(examples)} examples")

    if not examples:
        logger.error("No examples to display after filtering!")
        sys.exit(1)

    # Generate output
    output_lines = []

    if args.format in ("summary", "all"):
        output_lines.append(format_summary_table(examples))

    if args.format in ("compact", "all"):
        output_lines.append(format_compact_table(examples))

    if args.format in ("markdown", "all"):
        output_lines.append(format_markdown_table(examples))

    if args.format in ("detailed", "all"):
        output_lines.append("\n" + "=" * 80)
        output_lines.append("EXAMPLES (Detailed View)")
        output_lines.append("=" * 80)
        for i, ex in enumerate(examples, 1):
            output_lines.append(format_example(ex, i, show_details=True))

    # Write output
    output_text = "\n".join(output_lines)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_text)
        logger.info(f"Output written to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()

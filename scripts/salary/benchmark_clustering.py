#!/usr/bin/env python3
"""
Benchmark LLM verifier or production clustering algorithm with different settings.

Measures execution time, precision, and recall for detecting false positives
with different prompts and models (LLM mode) or rule-based matching (production mode).

By default, only uses hand-reviewed examples from the golden set for highest reliability.
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django
django.setup()

from lib.business.salary.llm_verifier import create_verifier, LLMVerifier, VerifierConfig
from lib.business.salary.clustering_evaluator import EmployerPair
from lib.business.salary.employer_clustering import match_employers, should_auto_cluster
from models.salary import Employer
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    config_name: str
    model: str
    prompt_template: str
    total_pairs: int
    execution_time_seconds: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    pairs_per_second: float
    errors: int  # Failed validations
    false_positive_cases: list[dict] = None  # Specific FP cases
    false_negative_cases: list[dict] = None  # Specific FN cases


def load_examples(jsonl_file: Path, only_reviewed: bool = True) -> list[dict]:
    """
    Load examples from JSONL file.
    
    Args:
        jsonl_file: Path to JSONL file with examples
        only_reviewed: If True, only load examples with type='reviewed' (hand-reviewed)
    
    Returns:
        List of example dicts
    """
    examples = []
    with open(jsonl_file, 'r') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                example = json.loads(line)
                # Filter to only reviewed examples by default
                if only_reviewed and example.get('type') != 'reviewed':
                    continue
                examples.append(example)
            except json.JSONDecodeError:
                continue
    
    if only_reviewed:
        logger.info(f"Filtered to {len(examples)} hand-reviewed examples (from {jsonl_file})")
    else:
        logger.info(f"Loaded {len(examples)} examples (all types) from {jsonl_file}")
    
    return examples


def convert_to_employer_pair(example: dict) -> EmployerPair:
    """Convert example dict to EmployerPair."""
    return EmployerPair(
        emp1_name=example['emp1_name'],
        emp1_city=example.get('emp1_city') or None,
        emp1_state=example.get('emp1_state') or None,
        emp2_name=example['emp2_name'],
        emp2_city=example.get('emp2_city') or None,
        emp2_state=example.get('emp2_state') or None,
        similarity=example.get('similarity', 0.0)
    )


def create_mock_employer(name: str, city: str = '', state: str = '') -> Employer:
    """
    Create a mock Employer object from example data for use with production algorithm.
    
    Note: This creates an in-memory object that's not saved to database.
    """
    # Create a mock Employer object (not saved to DB)
    employer = Employer(
        name=name,
        name_normalized=Employer.normalize_name(name),
        city=city or '',
        state=state or ''
    )
    return employer


def run_production_benchmark(
    examples: list[dict],
    config_name: str,
    threshold: float = 0.95,
    limit: int | None = None
) -> BenchmarkResult:
    """
    Run benchmark with production clustering algorithm.
    
    This exactly matches production logic:
    - Calls should_auto_cluster() which calls match_employers() (hybrid: rules + similarity)
    - Uses same threshold as production (default: 0.95)
    
    Note: Production clustering uses grouping by normalized name (hash-like optimization)
    to avoid n^2 complexity when clustering all employers. This benchmark doesn't need
    that optimization since it only tests pairs from the golden set.
    
    Args:
        examples: List of example dicts
        config_name: Name for this benchmark config
        threshold: Auto-cluster threshold (default: 0.95, matches production)
        limit: Optional limit on number of examples (for fast iteration)
    
    Returns:
        BenchmarkResult with metrics
    """
    # Limit examples for fast iteration
    if limit and limit < len(examples):
        examples = examples[:limit]
        logger.info(f"Limited to {limit} examples for fast iteration")
    
    logger.info(f"Running production algorithm benchmark: {config_name}")
    logger.info(f"  Threshold: {threshold}")
    logger.info(f"  Examples: {len(examples)}")
    
    # Detailed timing breakdown
    timing = {}
    phase_timings = {}
    
    # Phase 1: Convert examples to mock Employer objects
    convert_start = time.perf_counter()
    pairs = []
    employers1 = []
    employers2 = []
    for ex in examples:
        pair = convert_to_employer_pair(ex)
        pairs.append(pair)
        employers1.append(create_mock_employer(
            ex['emp1_name'],
            ex.get('emp1_city', ''),
            ex.get('emp1_state', '')
        ))
        employers2.append(create_mock_employer(
            ex['emp2_name'],
            ex.get('emp2_city', ''),
            ex.get('emp2_state', '')
        ))
    timing['convert_pairs'] = time.perf_counter() - convert_start
    phase_timings['convert'] = timing['convert_pairs']
    logger.info(f"  Phase 1 - Convert pairs: {timing['convert_pairs']:.3f}s")
    
    # Phase 2: Get ground truth
    ground_truth_start = time.perf_counter()
    ground_truth = [ex['ground_truth'] == 'same' for ex in examples]
    timing['ground_truth'] = time.perf_counter() - ground_truth_start
    phase_timings['ground_truth'] = timing['ground_truth']
    logger.info(f"  Phase 2 - Ground truth: {timing['ground_truth']:.3f}s")
    
    # Phase 3: Run production algorithm
    # Note: This exactly matches production logic - calls should_auto_cluster() which
    # uses match_employers() (hybrid: rule-based checks first, then similarity fallback)
    #
    # IMPORTANT: Production uses grouping by normalized name (hash buckets) to avoid n^2.
    # Only employers with the same normalized name are compared. We simulate this here
    # to catch false negatives where variants normalize to different buckets.
    verify_start = time.perf_counter()
    logger.info(f"  Phase 3 - Running production algorithm...")
    
    # Simple outcome class for production algorithm
    class ProductionOutcome:
        def __init__(self, is_same: bool | None, response: str):
            self.is_same = is_same
            self.response = response
    
    from models.salary import Employer
    from scripts.salary.cluster_existing_employers import (
        _build_lsh_index,
        _get_normalized_name_similarity
    )
    from datasketch import MinHash
    
    # Simulate production: Phase 1 uses same normalized names, Phase 2 uses LSH
    # Build LSH index for all normalized names (like Phase 2 does)
    all_normalized_names = set()
    for emp1, emp2 in zip(employers1, employers2):
        all_normalized_names.add(Employer.normalize_name(emp1.name))
        all_normalized_names.add(Employer.normalize_name(emp2.name))
    
    # Build LSH index (like Phase 2)
    lsh_threshold = 0.7  # Same as production Phase 2
    lsh, minhashes = _build_lsh_index(list(all_normalized_names), threshold=lsh_threshold)
    
    outcomes = []
    skipped_different_buckets = 0
    all_bucket_mismatches = []  # Track all pairs in different buckets (for detailed logging)
    for emp1, emp2, example in zip(employers1, employers2, examples):
        # Simulate production: Phase 1 (same normalized) vs Phase 2 (LSH for different normalized)
        norm1 = Employer.normalize_name(emp1.name)
        norm2 = Employer.normalize_name(emp2.name)
        
        # Phase 1: Same normalized name - would be compared in Phase 1
        if norm1 == norm2:
            # Same bucket - would be compared in Phase 1
            should_cluster, confidence, reason = should_auto_cluster(emp1, emp2, threshold=threshold)
            outcomes.append(ProductionOutcome(
                is_same=should_cluster,
                response=reason or f"Confidence: {confidence:.3f}"
            ))
            continue
        
        # Phase 2: Different normalized names - check if LSH would find them
        # Query LSH to see if these normalized names would be compared in Phase 2
        m1 = minhashes[norm1]
        lsh_candidates = lsh.query(m1)
        
        if norm2 in lsh_candidates:
            # LSH found this pair - would be compared in Phase 2
            # Verify similarity matches Phase 2 criteria (>= 0.7)
            similarity = _get_normalized_name_similarity(norm1, norm2)
            if similarity >= 0.7:
                # Would be processed in Phase 2 - run should_auto_cluster
                should_cluster, confidence, reason = should_auto_cluster(emp1, emp2, threshold=threshold)
                outcomes.append(ProductionOutcome(
                    is_same=should_cluster,
                    response=reason or f"Confidence: {confidence:.3f}"
                ))
            else:
                # LSH false positive - similarity too low, wouldn't be processed in Phase 2
                skipped_different_buckets += 1
                all_bucket_mismatches.append({
                    'emp1_name': emp1.name,
                    'emp1_city': emp1.city or '',
                    'emp1_state': emp1.state or '',
                    'emp2_name': emp2.name,
                    'emp2_city': emp2.city or '',
                    'emp2_state': emp2.state or '',
                    'normalized1': norm1,
                    'normalized2': norm2,
                    'ground_truth': example.get('ground_truth', 'unknown'),
                    'reason': f'LSH found but similarity {similarity:.3f} < 0.7 (Phase 2 threshold)'
                })
                outcomes.append(ProductionOutcome(
                    is_same=False,
                    response=f"LSH candidate but similarity {similarity:.3f} < 0.7 (would not be processed in Phase 2)"
                ))
        else:
            # LSH didn't find this pair - would never be compared in production Phase 2
            skipped_different_buckets += 1
            all_bucket_mismatches.append({
                'emp1_name': emp1.name,
                'emp1_city': emp1.city or '',
                'emp1_state': emp1.state or '',
                'emp2_name': emp2.name,
                'emp2_city': emp2.city or '',
                'emp2_state': emp2.state or '',
                'normalized1': norm1,
                'normalized2': norm2,
                'ground_truth': example.get('ground_truth', 'unknown'),
                'reason': 'Not found by LSH (Phase 2)'
            })
            outcomes.append(ProductionOutcome(
                is_same=False,  # Production Phase 2 would never compare these
                response=f"Different normalized buckets: '{norm1}' vs '{norm2}' (not found by LSH - would not be compared in Phase 2)"
            ))
    timing['verification'] = time.perf_counter() - verify_start
    phase_timings['verification'] = timing['verification']
    logger.info(f"  Phase 3 - Production algorithm: {timing['verification']:.3f}s")
    if skipped_different_buckets > 0:
        logger.warning(f"  ⚠️  {skipped_different_buckets} pairs not found by LSH (would not be compared in production Phase 2)")
        # Categorize by ground truth
        bucket_mismatch_same = [m for m in all_bucket_mismatches if m['ground_truth'] == 'same']
        bucket_mismatch_different = [m for m in all_bucket_mismatches if m['ground_truth'] == 'different']
        logger.warning(f"      - {len(bucket_mismatch_same)} pairs marked as 'same' (false negatives - LSH didn't find them)")
        logger.warning(f"      - {len(bucket_mismatch_different)} pairs marked as 'different' (true negatives - correctly not compared)")
        
        # Show examples of false negatives (same company not found by LSH)
        if bucket_mismatch_same:
            logger.warning(f"      Examples of false negatives (same company, LSH didn't find):")
            for case in bucket_mismatch_same[:5]:
                reason = case.get('reason', 'Not found by LSH')
                logger.warning(f"        - '{case['emp1_name']}' ({case['normalized1']}) vs '{case['emp2_name']}' ({case['normalized2']}) - {reason}")
            if len(bucket_mismatch_same) > 5:
                logger.warning(f"        ... and {len(bucket_mismatch_same) - 5} more")
        
        # Show examples of true negatives (different companies not found by LSH - this is expected)
        if bucket_mismatch_different:
            logger.info(f"      Examples of true negatives (different companies, not found by LSH - expected):")
            for case in bucket_mismatch_different[:5]:
                logger.info(f"        - '{case['emp1_name']}' ({case['normalized1']}) vs '{case['emp2_name']}' ({case['normalized2']})")
            if len(bucket_mismatch_different) > 5:
                logger.info(f"        ... and {len(bucket_mismatch_different) - 5} more")
    
    # Phase 4: Calculate metrics (same as LLM benchmark)
    metrics_start = time.perf_counter()
    execution_time = time.perf_counter() - convert_start
    
    # Calculate metrics
    true_positives = 0
    false_positives = 0
    true_negatives = 0
    false_negatives = 0
    errors = 0
    false_positive_cases = []
    false_negative_cases = []
    bucket_mismatch_cases = []  # Pairs in different normalized buckets (wouldn't be compared in production)
    
    metrics_calc_start = time.perf_counter()
    
    for i, (outcome, is_same_ground_truth, pair) in enumerate(zip(outcomes, ground_truth, pairs)):
        if outcome.is_same is None:
            errors += 1
            continue
        
        predicted_same = outcome.is_same
        
        if is_same_ground_truth and predicted_same:
            true_positives += 1
        elif is_same_ground_truth and not predicted_same:
            false_negatives += 1
            # Check if this is a bucket mismatch (different normalized names)
            from models.salary import Employer
            norm1 = Employer.normalize_name(pair.emp1_name)
            norm2 = Employer.normalize_name(pair.emp2_name)
            is_bucket_mismatch = norm1 != norm2
            
            # Save false negative case
            case_data = {
                'emp1_name': pair.emp1_name,
                'emp1_city': pair.emp1_city,
                'emp1_state': pair.emp1_state,
                'emp2_name': pair.emp2_name,
                'emp2_city': pair.emp2_city,
                'emp2_state': pair.emp2_state,
                'similarity': pair.similarity,
                'algorithm_response': outcome.response,
                'ground_truth': 'same',
                'predicted': 'different',
                'bucket_mismatch': is_bucket_mismatch,
                'normalized1': norm1,
                'normalized2': norm2,
            }
            false_negative_cases.append(case_data)
            
            if is_bucket_mismatch:
                bucket_mismatch_cases.append(case_data)
        elif not is_same_ground_truth and predicted_same:
            false_positives += 1
            # Save false positive case
            false_positive_cases.append({
                'emp1_name': pair.emp1_name,
                'emp1_city': pair.emp1_city,
                'emp1_state': pair.emp1_state,
                'emp2_name': pair.emp2_name,
                'emp2_city': pair.emp2_city,
                'emp2_state': pair.emp2_state,
                'similarity': pair.similarity,
                'algorithm_response': outcome.response,
                'ground_truth': 'different',
                'predicted': 'same'
            })
        else:  # not is_same_ground_truth and not predicted_same
            true_negatives += 1
    
    # Calculate precision, recall, F1
    precision = (true_positives / (true_positives + false_positives) 
                if (true_positives + false_positives) > 0 else 0.0)
    recall = (true_positives / (true_positives + false_negatives)
             if (true_positives + false_negatives) > 0 else 0.0)
    f1_score = (2 * (precision * recall) / (precision + recall)
               if (precision + recall) > 0 else 0.0)
    
    pairs_per_second = len(pairs) / execution_time if execution_time > 0 else 0.0
    timing['metrics_calc'] = time.perf_counter() - metrics_calc_start
    phase_timings['metrics'] = timing['metrics_calc']
    
    # Log detailed timing breakdown
    logger.info(f"  Detailed timing breakdown:")
    logger.info(f"    Convert pairs: {timing['convert_pairs']:.3f}s ({timing['convert_pairs']/len(pairs)*1000:.1f}ms/pair)")
    logger.info(f"    Ground truth: {timing['ground_truth']:.3f}s")
    logger.info(f"    Production algorithm: {timing['verification']:.3f}s ({timing['verification']/len(pairs):.3f}s per pair)")
    logger.info(f"    Metrics calculation: {timing['metrics_calc']:.3f}s")
    logger.info(f"    Total: {execution_time:.3f}s")
    logger.info(f"    Throughput: {pairs_per_second:.1f} pairs/second")
    
    # Log bucket mismatch summary (false negatives due to LSH not finding them)
    if bucket_mismatch_cases:
        logger.warning(f"  ⚠️  {len(bucket_mismatch_cases)} false negatives due to LSH not finding similar pairs:")
        logger.warning(f"      These pairs would never be compared in production Phase 2 (LSH didn't find them)")
        logger.warning(f"      This indicates LSH may need tuning or normalization needs refinement")
        # Show first few examples
        for case in bucket_mismatch_cases[:5]:
            logger.warning(f"        - '{case['emp1_name']}' ({case['normalized1']}) vs '{case['emp2_name']}' ({case['normalized2']})")
        if len(bucket_mismatch_cases) > 5:
            logger.warning(f"        ... and {len(bucket_mismatch_cases) - 5} more")
    
    # Identify bottleneck
    max_phase = max(phase_timings.items(), key=lambda x: x[1])
    logger.info(f"  ⚠️  Bottleneck: {max_phase[0]} ({max_phase[1]:.3f}s, {max_phase[1]/execution_time*100:.1f}% of total)")
    
    return BenchmarkResult(
        config_name=config_name,
        model=f"production-threshold-{threshold}",
        prompt_template=f"rule-based (threshold={threshold})",
        total_pairs=len(pairs),
        execution_time_seconds=execution_time,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        pairs_per_second=pairs_per_second,
        errors=errors,
        false_positive_cases=false_positive_cases,
        false_negative_cases=false_negative_cases
    )


async def run_llm_benchmark(
    verifier: LLMVerifier,
    examples: list[dict],
    config_name: str,
    limit: int | None = None
) -> BenchmarkResult:
    """
    Run benchmark with given verifier and examples.
    
    Args:
        verifier: LLM verifier instance
        examples: List of example dicts
        config_name: Name for this benchmark config
        limit: Optional limit on number of examples (for fast iteration)
    
    Returns:
        BenchmarkResult with metrics
    """
    # Limit examples for fast iteration
    if limit and limit < len(examples):
        examples = examples[:limit]
        logger.info(f"Limited to {limit} examples for fast iteration")
    
    logger.info(f"Running benchmark: {config_name}")
    logger.info(f"  Model: {verifier.config.model}")
    logger.info(f"  Examples: {len(examples)}")
    
    # Detailed timing breakdown
    timing = {}
    phase_timings = {}
    
    # Phase 1: Convert examples to EmployerPair objects
    convert_start = time.perf_counter()
    pairs = [convert_to_employer_pair(ex) for ex in examples]
    timing['convert_pairs'] = time.perf_counter() - convert_start
    phase_timings['convert'] = timing['convert_pairs']
    logger.info(f"  Phase 1 - Convert pairs: {timing['convert_pairs']:.3f}s")
    
    # Phase 2: Get ground truth
    ground_truth_start = time.perf_counter()
    ground_truth = [ex['ground_truth'] == 'same' for ex in examples]
    timing['ground_truth'] = time.perf_counter() - ground_truth_start
    phase_timings['ground_truth'] = timing['ground_truth']
    logger.info(f"  Phase 2 - Ground truth: {timing['ground_truth']:.3f}s")
    
    # Phase 3: Run verification (this is where most time is spent)
    verify_start = time.perf_counter()
    logger.info(f"  Phase 3 - Starting LLM verification...")
    outcomes = await verifier.verify_batch_async(pairs)
    timing['verification'] = time.perf_counter() - verify_start
    phase_timings['verification'] = timing['verification']
    logger.info(f"  Phase 3 - LLM verification: {timing['verification']:.3f}s")
    
    # Phase 4: Calculate metrics
    metrics_start = time.perf_counter()
    execution_time = time.perf_counter() - convert_start
    
    # Calculate metrics
    true_positives = 0
    false_positives = 0
    true_negatives = 0
    false_negatives = 0
    errors = 0
    false_positive_cases = []
    false_negative_cases = []
    
    metrics_calc_start = time.perf_counter()
    
    for i, (outcome, is_same_ground_truth, pair) in enumerate(zip(outcomes, ground_truth, pairs)):
        if outcome.is_same is None:
            errors += 1
            continue
        
        predicted_same = outcome.is_same
        
        if is_same_ground_truth and predicted_same:
            true_positives += 1
        elif is_same_ground_truth and not predicted_same:
            false_negatives += 1
            # Save false negative case
            false_negative_cases.append({
                'emp1_name': pair.emp1_name,
                'emp1_city': pair.emp1_city,
                'emp1_state': pair.emp1_state,
                'emp2_name': pair.emp2_name,
                'emp2_city': pair.emp2_city,
                'emp2_state': pair.emp2_state,
                'similarity': pair.similarity,
                'llm_response': outcome.response,
                'ground_truth': 'same',
                'predicted': 'different'
            })
        elif not is_same_ground_truth and predicted_same:
            false_positives += 1
            # Save false positive case
            false_positive_cases.append({
                'emp1_name': pair.emp1_name,
                'emp1_city': pair.emp1_city,
                'emp1_state': pair.emp1_state,
                'emp2_name': pair.emp2_name,
                'emp2_city': pair.emp2_city,
                'emp2_state': pair.emp2_state,
                'similarity': pair.similarity,
                'llm_response': outcome.response,
                'ground_truth': 'different',
                'predicted': 'same'
            })
        else:  # not is_same_ground_truth and not predicted_same
            true_negatives += 1
    
    # Calculate precision, recall, F1
    precision = (true_positives / (true_positives + false_positives) 
                if (true_positives + false_positives) > 0 else 0.0)
    recall = (true_positives / (true_positives + false_negatives)
             if (true_positives + false_negatives) > 0 else 0.0)
    f1_score = (2 * (precision * recall) / (precision + recall)
               if (precision + recall) > 0 else 0.0)
    
    pairs_per_second = len(pairs) / execution_time if execution_time > 0 else 0.0
    timing['metrics_calc'] = time.perf_counter() - metrics_calc_start
    phase_timings['metrics'] = timing['metrics_calc']
    
    # Log detailed timing breakdown
    logger.info(f"  Detailed timing breakdown:")
    logger.info(f"    Convert pairs: {timing['convert_pairs']:.3f}s ({timing['convert_pairs']/len(pairs)*1000:.1f}ms/pair)")
    logger.info(f"    Ground truth: {timing['ground_truth']:.3f}s")
    logger.info(f"    LLM verification: {timing['verification']:.3f}s ({timing['verification']/len(pairs):.3f}s per pair)")
    logger.info(f"    Metrics calculation: {timing['metrics_calc']:.3f}s")
    logger.info(f"    Total: {execution_time:.3f}s")
    logger.info(f"    Throughput: {pairs_per_second:.1f} pairs/second")
    
    # Identify bottleneck
    max_phase = max(phase_timings.items(), key=lambda x: x[1])
    logger.info(f"  ⚠️  Bottleneck: {max_phase[0]} ({max_phase[1]:.3f}s, {max_phase[1]/execution_time*100:.1f}% of total)")
    
    return BenchmarkResult(
        config_name=config_name,
        model=verifier.config.model,
        prompt_template=verifier.config.prompt_template or str(verifier.config.prompt_template_path) or 'default',
        total_pairs=len(pairs),
        execution_time_seconds=execution_time,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        pairs_per_second=pairs_per_second,
        errors=errors,
        false_positive_cases=false_positive_cases,
        false_negative_cases=false_negative_cases
    )


def print_results(results: list[BenchmarkResult]):
    """Print benchmark results in a table."""
    print("\n" + "=" * 100)
    print("BENCHMARK RESULTS")
    print("=" * 100)
    
    # Header
    print(f"{'Config':<20} {'Model':<15} {'Precision':<10} {'Recall':<10} {'F1':<10} "
          f"{'Time (s)':<10} {'Pairs/s':<10} {'Errors':<8}")
    print("-" * 100)
    
    # Results
    for r in results:
        print(f"{r.config_name:<20} {r.model:<15} {r.precision:<10.3f} {r.recall:<10.3f} "
              f"{r.f1_score:<10.3f} {r.execution_time_seconds:<10.2f} "
              f"{r.pairs_per_second:<10.1f} {r.errors:<8}")
    
    print("=" * 100)
    
    # Detailed breakdown
    print("\nDETAILED BREAKDOWN:")
    for r in results:
        print(f"\n{r.config_name}:")
        print(f"  Model: {r.model}")
        print(f"  Prompt: {r.prompt_template[:50]}..." if len(r.prompt_template) > 50 else f"  Prompt: {r.prompt_template}")
        print(f"  Total pairs: {r.total_pairs}")
        print(f"  Execution time: {r.execution_time_seconds:.2f}s")
        print(f"  Throughput: {r.pairs_per_second:.1f} pairs/second")
        print(f"  True positives: {r.true_positives}")
        print(f"  False positives: {r.false_positives}")
        print(f"  True negatives: {r.true_negatives}")
        print(f"  False negatives: {r.false_negatives}")
        print(f"  Errors (failed): {r.errors}")
        print(f"  Precision: {r.precision:.3f}")
        print(f"  Recall: {r.recall:.3f}")
        print(f"  F1 Score: {r.f1_score:.3f}")
        
        # Show sample false positives/negatives
        if r.false_positive_cases:
            print(f"\n  FALSE POSITIVES ({len(r.false_positive_cases)}):")
            for i, fp in enumerate(r.false_positive_cases[:5], 1):
                print(f"    {i}. '{fp['emp1_name']}' vs '{fp['emp2_name']}' (similarity: {fp['similarity']:.3f})")
                if fp.get('llm_response'):
                    print(f"       LLM: {fp['llm_response'][:100]}...")
                elif fp.get('algorithm_response'):
                    print(f"       Algorithm: {fp['algorithm_response'][:100]}...")
            if len(r.false_positive_cases) > 5:
                print(f"    ... and {len(r.false_positive_cases) - 5} more")
        
        if r.false_negative_cases:
            print(f"\n  FALSE NEGATIVES ({len(r.false_negative_cases)}):")
            for i, fn in enumerate(r.false_negative_cases[:5], 1):
                print(f"    {i}. '{fn['emp1_name']}' vs '{fn['emp2_name']}' (similarity: {fn['similarity']:.3f})")
                if fn.get('llm_response'):
                    print(f"       LLM: {fn['llm_response'][:100]}...")
                elif fn.get('algorithm_response'):
                    print(f"       Algorithm: {fn['algorithm_response'][:100]}...")
            if len(r.false_negative_cases) > 5:
                print(f"    ... and {len(r.false_negative_cases) - 5} more")


def save_results(results: list[BenchmarkResult], output_file: Path):
    """Save results to JSON file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    results_dict = [
        {
            'config_name': r.config_name,
            'model': r.model,
            'prompt_template': r.prompt_template,
            'total_pairs': r.total_pairs,
            'execution_time_seconds': r.execution_time_seconds,
            'true_positives': r.true_positives,
            'false_positives': r.false_positives,
            'true_negatives': r.true_negatives,
            'false_negatives': r.false_negatives,
            'precision': r.precision,
            'recall': r.recall,
            'f1_score': r.f1_score,
            'pairs_per_second': r.pairs_per_second,
            'errors': r.errors,
            'false_positive_cases': r.false_positive_cases or [],
            'false_negative_cases': r.false_negative_cases or [],
        }
        for r in results
    ]
    
    with open(output_file, 'w') as f:
        json.dump(results_dict, f, indent=2)
    
    logger.info(f"Saved results to {output_file}")


def get_stable_models_dir() -> Path:
    """
    Get stable directory for caching models between benchmark runs.
    
    Uses a fixed location outside Bazel execution root so models persist.
    """
    # Use ~/.cache/ollama_benchmark/models (stable across Bazel invocations)
    cache_dir = Path.home() / ".cache" / "ollama_benchmark" / "models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


async def start_ollama_server() -> Optional[subprocess.Popen]:
    """
    Start Ollama server using Bazel-provided binary.
    
    Uses stable models directory so models persist between runs.
    
    Returns:
        subprocess.Popen process object, or None if failed
    """
    start_time = time.perf_counter()
    logger.info("Starting Ollama server...")
    
    # Check if server is already running
    check_start = time.perf_counter()
    try:
        import httpx
        response = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code == 200:
            # Check if server actually has models
            models_data = response.json()
            available_models = [m.get('name') for m in models_data.get('models', [])]
            elapsed = time.perf_counter() - check_start
            if available_models:
                logger.info(f"Ollama server already running with {len(available_models)} models (checked in {elapsed:.3f}s)")
                return None
            else:
                logger.warning(f"Ollama server running but has no models (checked in {elapsed:.3f}s)")
                logger.warning(f"  This may be a Bazel-provided server with empty models directory")
                logger.warning(f"  Will attempt to use system ollama CLI to pull models")
                # Continue to start our own server or use system one
    except Exception as e:
        pass  # Server not running, continue to start it
    check_elapsed = time.perf_counter() - check_start
    
    # Get stable models directory
    models_dir = get_stable_models_dir()
    logger.info(f"Using models directory: {models_dir}")
    
    # Find Bazel binary path
    workspace_dir = os.environ.get('BUILD_WORKSPACE_DIRECTORY', os.getcwd())
    
    # Start Ollama server in background with stable models directory
    spawn_start = time.perf_counter()
    try:
        log_file = Path("/tmp/ollama_benchmark.log")
        env = os.environ.copy()
        env['OLLAMA_MODELS'] = str(models_dir)
        
        # Try system ollama CLI first (more reliable)
        # Don't set OLLAMA_MODELS - use system default so models are accessible
        import shutil
        ollama_cli = shutil.which('ollama')
        if ollama_cli:
            # Use system ollama CLI without custom OLLAMA_MODELS (use system default)
            # This ensures models pulled via system ollama are accessible
            system_env = os.environ.copy()  # Don't override OLLAMA_MODELS
            with open(log_file, 'w') as f:
                process = subprocess.Popen(
                    [ollama_cli, 'serve'],
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    env=system_env
                )
        else:
            # Fallback to Bazel (may not work if @ollama target missing)
            with open(log_file, 'w') as f:
                process = subprocess.Popen(
                    ['bazel', 'run', '@ollama//:ollama', '--', 'serve'],
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    cwd=workspace_dir,
                    env=env
                )
        
        spawn_elapsed = time.perf_counter() - spawn_start
        logger.info(f"Started Ollama server (PID: {process.pid}, spawn: {spawn_elapsed:.3f}s)")
        logger.info(f"Server logs: {log_file}")
        logger.info(f"Models cached at: {models_dir}")
        
        # Wait for server to be ready
        wait_start = time.perf_counter()
        logger.info("Waiting for Ollama server to be ready...")
        for i in range(10):  # Wait up to 10 seconds (reduced from 30)
            await asyncio.sleep(1)
            try:
                import httpx
                response = httpx.get("http://localhost:11434/api/tags", timeout=2)
                if response.status_code == 200:
                    wait_elapsed = time.perf_counter() - wait_start
                    total_elapsed = time.perf_counter() - start_time
                    logger.info(f"✓ Ollama server is ready (wait: {wait_elapsed:.3f}s, total: {total_elapsed:.3f}s)")
                    return process
            except Exception as e:
                if i % 2 == 0:
                    logger.info(f"  Waiting... ({i+1}/10)")
        
        wait_elapsed = time.perf_counter() - wait_start
        total_elapsed = time.perf_counter() - start_time
        logger.error(f"Ollama server failed to start within 10 seconds (wait: {wait_elapsed:.3f}s, total: {total_elapsed:.3f}s)")
        if process.poll() is not None:
            logger.error(f"Server process exited with code: {process.returncode}")
            with open(log_file, 'r') as f:
                logger.error(f"Server output: {f.read()[-500:]}")
        process.terminate()
        return None
        
    except Exception as e:
        total_elapsed = time.perf_counter() - start_time
        logger.error(f"Failed to start Ollama server (total: {total_elapsed:.3f}s): {e}", exc_info=True)
        return None


async def ensure_model_available(model: str):
    """
    Ensure model is available, pull if needed.
    
    Uses stable models directory so models are cached between runs.
    Verifies model is detected by Ollama after pull.
    """
    start_time = time.perf_counter()
    logger.info(f"Ensuring model {model} is available...")
    
    # Check if model exists
    check_start = time.perf_counter()
    try:
        import httpx
        response = httpx.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models_data = response.json()
            models = [m.get('name') for m in models_data.get('models', [])]
            check_elapsed = time.perf_counter() - check_start
            if model in models:
                total_elapsed = time.perf_counter() - start_time
                logger.info(f"✓ Model {model} is already available (cached) (check: {check_elapsed:.3f}s, total: {total_elapsed:.3f}s)")
                return True
    except Exception as e:
        check_elapsed = time.perf_counter() - check_start
        logger.warning(f"Failed to check models (check: {check_elapsed:.3f}s): {e}")
    
    # Pull model with stable models directory
    pull_start = time.perf_counter()
    logger.info(f"Pulling model {model} (will be cached for future runs)...")
    try:
        workspace_dir = os.environ.get('BUILD_WORKSPACE_DIRECTORY', os.getcwd())
        models_dir = get_stable_models_dir()
        env = os.environ.copy()
        env['OLLAMA_MODELS'] = str(models_dir)
        
        # Try system ollama CLI first (more reliable)
        import shutil
        ollama_cli = shutil.which('ollama')
        if ollama_cli:
            # Don't override OLLAMA_MODELS - use system default
            system_env = os.environ.copy()
            result = subprocess.run(
                [ollama_cli, 'pull', model],
                capture_output=True,
                text=True,
                timeout=120,  # 2 minutes for model pull
                env=system_env
            )
        else:
            # Fallback to Bazel (may not work if @ollama target missing)
            result = subprocess.run(
                ['bazel', 'run', '@ollama//:ollama', '--', 'pull', model],
                capture_output=True,
                text=True,
                timeout=30,  # 30 seconds timeout (models should be pre-pulled)
                cwd=workspace_dir,
                env=env
            )
        pull_elapsed = time.perf_counter() - pull_start
        total_elapsed = time.perf_counter() - start_time
        if result.returncode == 0:
            logger.info(f"✓ Successfully pulled model {model} (pull: {pull_elapsed:.2f}s, total: {total_elapsed:.2f}s)")
            logger.info(f"  Model cached at: {models_dir}")
            
            # Verify model is detected by Ollama after pull
            verify_start = time.perf_counter()
            try:
                import httpx
                # Wait a moment for Ollama to register the model
                await asyncio.sleep(1)
                response = httpx.get("http://localhost:11434/api/tags", timeout=5)
                if response.status_code == 200:
                    models_data = response.json()
                    models = [m.get('name') for m in models_data.get('models', [])]
                    verify_elapsed = time.perf_counter() - verify_start
                    if model in models:
                        logger.info(f"✓ Model {model} verified in Ollama after pull (verify: {verify_elapsed:.3f}s)")
                        return True
                    else:
                        logger.warning(f"⚠ Model {model} not found in /api/tags after pull (verify: {verify_elapsed:.3f}s)")
                        logger.warning(f"  Available models: {models}")
                        logger.warning(f"  This may indicate Ollama is not using OLLAMA_MODELS={models_dir}")
                        # Still return True - model was pulled, may work anyway
                        return True
                else:
                    logger.warning(f"⚠ Failed to verify model after pull (status {response.status_code})")
                    return True  # Assume success if pull succeeded
            except Exception as e:
                verify_elapsed = time.perf_counter() - verify_start
                logger.warning(f"⚠ Failed to verify model after pull (verify: {verify_elapsed:.3f}s): {e}")
                return True  # Assume success if pull succeeded
            
            return True
        else:
            logger.warning(f"Failed to pull model {model} via Bazel (pull: {pull_elapsed:.2f}s, total: {total_elapsed:.2f}s)")
            logger.warning(f"  Error: {result.stderr[:200] if result.stderr else 'Unknown error'}")
            # Check if model is actually available via direct Ollama CLI (not Bazel)
            # This handles cases where model was pulled outside Bazel
            try:
                import httpx
                response = httpx.get("http://localhost:11434/api/tags", timeout=5)
                if response.status_code == 200:
                    models_data = response.json()
                    available_models = [m.get('name') for m in models_data.get('models', [])]
                    if model in available_models:
                        logger.info(f"✓ Model {model} is available via Ollama server (even though Bazel pull failed)")
                        return True
                    else:
                        # Try pulling via system ollama CLI (not Bazel)
                        logger.info(f"Model {model} not in server. Attempting to pull via system ollama CLI...")
                        import shutil
                        ollama_cli = shutil.which('ollama')
                        if ollama_cli:
                            pull_result = subprocess.run(
                                [ollama_cli, 'pull', model],
                                capture_output=True,
                                text=True,
                                timeout=120  # 2 minutes for model pull
                            )
                            if pull_result.returncode == 0:
                                # Wait a moment for server to register
                                await asyncio.sleep(2)
                                # Check again
                                response2 = httpx.get("http://localhost:11434/api/tags", timeout=5)
                                if response2.status_code == 200:
                                    models_data2 = response2.json()
                                    available_models2 = [m.get('name') for m in models_data2.get('models', [])]
                                    if model in available_models2:
                                        logger.info(f"✓ Model {model} successfully pulled via system ollama CLI")
                                        return True
                        logger.error(f"✗ Model {model} is NOT available in Ollama server")
                        logger.error(f"  Available models: {available_models}")
                        return False
            except Exception as e:
                logger.error(f"Failed to check model availability after pull failure: {e}")
                return False
    except subprocess.TimeoutExpired:
        pull_elapsed = time.perf_counter() - pull_start
        total_elapsed = time.perf_counter() - start_time
        logger.error(f"Timeout pulling model {model} (pull: {pull_elapsed:.2f}s, total: {total_elapsed:.2f}s)")
        return False
    except Exception as e:
        pull_elapsed = time.perf_counter() - pull_start
        total_elapsed = time.perf_counter() - start_time
        logger.error(f"Error pulling model {model} (pull: {pull_elapsed:.2f}s, total: {total_elapsed:.2f}s): {e}", exc_info=True)
        return False


async def main_async(args):
    """Main async function."""
    main_start = time.perf_counter()
    
    # Start Ollama server if needed (only for LLM mode)
    ollama_process = None
    if args.mode in ('llm', 'both'):
        server_start = time.perf_counter()
        ollama_process = await start_ollama_server()
        server_elapsed = time.perf_counter() - server_start
        
        # Fast fail if server startup took too long
        if server_elapsed > 15.0:
            logger.error(f"Server startup took {server_elapsed:.3f}s (exceeded 15s limit)")
            if ollama_process is not None:
                ollama_process.terminate()
            return
        
        if server_elapsed > 1.0:
            logger.info(f"Server startup took {server_elapsed:.3f}s")
        
        # Ensure models are available (only for LLM mode)
        model_check_start = time.perf_counter()
        models_to_check = [args.model]
        if args.models:
            models_to_check.extend(args.models)
        
        for model in set(models_to_check):  # Remove duplicates
            model_available = await ensure_model_available(model)
            if not model_available:
                logger.error(f"Model {model} is not available and could not be pulled. Exiting.")
                return  # Return from async function, let main() handle exit
        model_check_elapsed = time.perf_counter() - model_check_start
        if model_check_elapsed > 1.0:
            logger.info(f"Model availability checks took {model_check_elapsed:.3f}s")
    
    try:
        
        # Load examples (filter to hand-reviewed by default)
        logger.info(f"Loading examples from {args.examples_file}...")
        examples = load_examples(args.examples_file, only_reviewed=args.only_reviewed)
        logger.info(f"Loaded {len(examples)} examples")
        
        if not examples:
            logger.error("No examples loaded!")
            if args.only_reviewed:
                logger.error("  Try --include-all-types to include auto-clustered and different-company pairs")
            return
        
        # Load prompt templates if specified
        prompt_templates = {}
        if args.prompt_templates:
            for prompt_file in args.prompt_templates:
                name = prompt_file.stem
                with open(prompt_file, 'r') as f:
                    prompt_templates[name] = f.read().strip()
                logger.info(f"Loaded prompt template: {name} from {prompt_file}")
        
        # Run benchmarks
        results = []
        
        if args.mode == 'production':
            # Benchmark production algorithm
            logger.info("Running production algorithm benchmark...")
            result = run_production_benchmark(
                examples,
                "production-default",
                threshold=args.production_threshold,
                limit=args.limit
            )
            results.append(result)
            
            # Test different thresholds if specified
            if args.production_thresholds:
                for threshold in args.production_thresholds:
                    result = run_production_benchmark(
                        examples,
                        f"production-threshold-{threshold}",
                        threshold=threshold,
                        limit=args.limit
                    )
                    results.append(result)
        
        elif args.mode == 'llm':
            # Benchmark LLM verifier (original functionality)
            # Start Ollama server if needed
            if ollama_process is None:
                logger.error("Ollama server not available for LLM mode")
                return
            
            # Default prompt (from template file)
            # Disable auto_pull_model since models are pre-pulled at startup
            if not args.skip_default:
                verifier = create_verifier(
                    model=args.model,
                    prompt_template_path=args.prompt_template_path,
                    timeout=args.timeout,
                    max_concurrent=args.max_concurrent,
                    auto_pull_model=False,  # Models already pulled at startup
                    fallback_model=None  # Disable fallback to avoid errors
                )
                result = await run_llm_benchmark(verifier, examples, "default", limit=args.limit)
                results.append(result)
            
            # Custom prompt templates
            for name, template in prompt_templates.items():
                verifier = create_verifier(
                    model=args.model,
                    prompt_template=template,
                    timeout=args.timeout,
                    max_concurrent=args.max_concurrent,
                    auto_pull_model=False,  # Models already pulled at startup
                    fallback_model=None  # Disable fallback to avoid errors
                )
                result = await run_llm_benchmark(verifier, examples, name, limit=args.limit)
                results.append(result)
            
            # Multiple models if specified
            if args.models:
                for model in args.models:
                    verifier = create_verifier(
                        model=model,
                        prompt_template_path=args.prompt_template_path,
                        timeout=args.timeout,
                        max_concurrent=args.max_concurrent,
                        auto_pull_model=False,  # Models already pulled at startup
                        fallback_model=None  # Disable fallback to avoid errors
                    )
                    result = await run_llm_benchmark(verifier, examples, f"model_{model.replace(':', '_')}", limit=args.limit)
                    results.append(result)
        
        else:  # both
            # Run both production and LLM benchmarks
            logger.info("Running both production and LLM benchmarks...")
            
            # Production first (no server needed)
            result = run_production_benchmark(
                examples,
                "production-default",
                threshold=args.production_threshold,
                limit=args.limit
            )
            results.append(result)
            
            # Then LLM (requires server)
            if ollama_process is None:
                logger.warning("Ollama server not available, skipping LLM benchmark")
            else:
                if not args.skip_default:
                    verifier = create_verifier(
                        model=args.model,
                        prompt_template_path=args.prompt_template_path,
                        timeout=args.timeout,
                        max_concurrent=args.max_concurrent,
                        auto_pull_model=False,
                        fallback_model=None
                    )
                    result = await run_llm_benchmark(verifier, examples, "llm-default", limit=args.limit)
                    results.append(result)
        
        # Print results
        print_results(results)
        
        # Save results
        if args.output:
            save_results(results, args.output)
        
        total_elapsed = time.perf_counter() - main_start
        logger.info(f"Benchmark completed in {total_elapsed:.2f}s")
    
    finally:
        # Clean up Ollama server if we started it
        if ollama_process is not None:
            cleanup_start = time.perf_counter()
            logger.info("Stopping Ollama server...")
            ollama_process.terminate()
            try:
                ollama_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ollama_process.kill()
            cleanup_elapsed = time.perf_counter() - cleanup_start
            logger.info(f"Ollama server stopped (cleanup: {cleanup_elapsed:.3f}s)")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark LLM verifier or production clustering algorithm with different settings"
    )
    parser.add_argument(
        '--mode',
        type=str,
        choices=['llm', 'production', 'both'],
        default='production',
        help='Benchmark mode: llm (LLM verifier), production (rule-based algorithm), or both (default: production)'
    )
    parser.add_argument(
        '--examples-file',
        type=Path,
        required=True,
        help='JSONL file with examples (from collect_clustering_examples.py)'
    )
    parser.add_argument(
        '--only-reviewed',
        action='store_true',
        default=True,
        help='Only use hand-reviewed examples (default: True, highest reliability)'
    )
    parser.add_argument(
        '--include-all-types',
        action='store_true',
        help='Include all example types (auto-clustered, different-company) in addition to reviewed'
    )
    parser.add_argument(
        '--production-threshold',
        type=float,
        default=0.95,
        help='Auto-cluster threshold for production algorithm (default: 0.95)'
    )
    parser.add_argument(
        '--production-thresholds',
        nargs='+',
        type=float,
        help='Multiple thresholds to test (e.g., 0.90 0.95 0.98)'
    )
    parser.add_argument(
        '--model',
        type=str,
        default='llama3.2:1b',
        help='Model to use (default: llama3.2:1b)'
    )
    parser.add_argument(
        '--models',
        nargs='+',
        help='Multiple models to test (e.g., llama3.2:1b llama3.2:3b)'
    )
    parser.add_argument(
        '--prompt-template-path',
        type=Path,
        default=None,
        help='Path to default prompt template file'
    )
    parser.add_argument(
        '--prompt-templates',
        nargs='+',
        type=Path,
        help='Additional prompt template files to test'
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=60.0,
        help='Request timeout in seconds (default: 60.0)'
    )
    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=4,
        help='Maximum concurrent requests (default: 4)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output JSON file for results (optional)'
    )
    parser.add_argument(
        '--skip-default',
        action='store_true',
        help='Skip default prompt template benchmark'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Limit number of examples for fast iteration (default: 10 for quick testing)'
    )
    parser.add_argument(
        '--max-total-time',
        type=float,
        default=300.0,
        help='Maximum total execution time in seconds (default: 300.0 = 5 minutes)'
    )
    
    args = parser.parse_args()
    
    # Handle --include-all-types flag (overrides --only-reviewed)
    if args.include_all_types:
        args.only_reviewed = False
    
    # Log execution
    context = f'Benchmarking {args.mode} mode'
    if args.only_reviewed:
        context += ' (hand-reviewed examples only)'
    else:
        context += ' (all example types)'
    script_logger.log_call(
        args=vars(args),
        context=context
    )
    
    # Run async main with timeout
    try:
        result = asyncio.run(asyncio.wait_for(main_async(args), timeout=args.max_total_time))
        if result is None:
            # main_async returned None, which means it completed successfully
            pass
        else:
            # main_async returned early (model unavailable, etc.)
            sys.exit(1)
    except asyncio.TimeoutError:
        logger.error(f"Benchmark exceeded maximum time limit of {args.max_total_time}s")
        sys.exit(1)


if __name__ == '__main__':
    main()

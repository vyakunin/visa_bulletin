"""
Evaluator for employer clustering precision/recall metrics.

Uses LLM validation to determine if auto-clustered pairs are true/false positives
and if queued pairs are true/false negatives.

Supports parallel async validation for 2-4x performance improvement.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EvaluationOutcome:
    """Result of LLM validation for a pair of employers."""

    is_same: (
        bool | None
    )  # True if same company, False if different, None if validation failed
    response: str | None  # LLM response text, or None if validation failed

    @classmethod
    def same(cls, response: str) -> "EvaluationOutcome":
        """Create outcome for same company."""
        return cls(is_same=True, response=response)

    @classmethod
    def different(cls, response: str) -> "EvaluationOutcome":
        """Create outcome for different companies."""
        return cls(is_same=False, response=response)

    @classmethod
    def failed(cls) -> "EvaluationOutcome":
        """Create outcome for failed validation."""
        return cls(is_same=None, response=None)


@dataclass
class EmployerPair:
    """Pair of employers to validate."""

    emp1_name: str
    emp1_city: str | None
    emp1_state: str | None
    emp2_name: str
    emp2_city: str | None
    emp2_state: str | None
    similarity: float


@dataclass
class PairEvaluationStats:
    """Statistics from evaluating a set of pairs."""

    true_positives: int
    false_positives: int
    skipped: int
    total: int
    error_pairs: list  # List of pairs with errors (false positives or false negatives)


@dataclass
class EvaluationResults:
    """Results of evaluating clustering samples."""

    metrics: dict  # Precision, recall, F1 metrics
    false_positives: list  # List of false positive pairs
    false_negatives: list  # List of false negative pairs


class ClusteringEvaluator:
    """Evaluates clustering pairs using LLM validation."""

    def __init__(
        self,
        llm_validator=None,
        prompt_template_path: Path | None = None,
        use_parallel: bool = True,
        max_concurrent: int = 4,
    ):
        """
        Initialize evaluator.

        Args:
            llm_validator: Optional function that takes EmployerPair and returns EvaluationOutcome
                If None, uses async HTTP API with parallel processing
            prompt_template_path: Optional path to prompt template file
            use_parallel: If True, use parallel async validation (default: True)
            max_concurrent: Maximum concurrent LLM calls (default: 4)
        """
        self.llm_validator = llm_validator
        self.prompt_template_path = prompt_template_path
        self.use_parallel = use_parallel
        self.max_concurrent = max_concurrent

    def _evaluate_single_pair(
        self, pair: EmployerPair | dict, pair_type: str, pair_index: int, total: int
    ) -> EvaluationOutcome:
        """
        Evaluate a single employer pair using LLM validation.

        Args:
            pair: EmployerPair dataclass or dictionary with employer pair data
            pair_type: Type of pair ('auto-clustered' or 'queued')
            pair_index: Index of pair in sample (1-based)
            total: Total number of pairs in sample

        Returns:
            EvaluationOutcome from LLM validation
        """
        # Convert dict to EmployerPair if needed
        if isinstance(pair, dict):
            employer_pair = EmployerPair(
                emp1_name=pair["emp1_name"],
                emp1_city=pair["emp1_city"],
                emp1_state=pair["emp1_state"],
                emp2_name=pair["emp2_name"],
                emp2_city=pair["emp2_city"],
                emp2_state=pair["emp2_state"],
                similarity=pair["similarity"],
            )
        else:
            employer_pair = pair

        logger.debug(
            f"Evaluating {pair_type} pair {pair_index}/{total}: "
            f"{employer_pair.emp1_name} vs {employer_pair.emp2_name} "
            f"(similarity={employer_pair.similarity:.3f})"
        )

        return self.llm_validator(employer_pair)

    def _evaluate_auto_clustered_pairs(self, auto_sample: list) -> PairEvaluationStats:
        """
        Evaluate auto-clustered pairs (should be same company).

        Returns:
            PairEvaluationStats with counts and false positives list
        """
        logger.info(f"Evaluating {len(auto_sample)} auto-clustered pairs...")
        auto_tp = 0
        auto_fp = 0
        auto_skipped = 0
        false_positives = []

        for i, pair in enumerate(auto_sample, 1):
            # Log progress every 20 pairs
            if i % 20 == 0 or i == 1:
                logger.info(
                    f"Progress: Evaluating auto-clustered pair {i}/{len(auto_sample)} ({i / len(auto_sample) * 100:.1f}%)"
                )

            outcome = self._evaluate_single_pair(
                pair, "auto-clustered", i, len(auto_sample)
            )

            if outcome.is_same is None:
                auto_skipped += 1
                logger.warning(
                    f"Skipped auto-clustered pair {i}: LLM validation failed"
                )
                continue

            # Extract pair data for logging/error tracking
            pair_dict = (
                pair
                if isinstance(pair, dict)
                else {
                    "emp1_name": pair.emp1_name,
                    "emp1_city": pair.emp1_city,
                    "emp1_state": pair.emp1_state,
                    "emp2_name": pair.emp2_name,
                    "emp2_city": pair.emp2_city,
                    "emp2_state": pair.emp2_state,
                    "similarity": pair.similarity,
                }
            )

            if outcome.is_same:
                auto_tp += 1
                logger.debug(
                    f"True positive: {pair_dict['emp1_name']} = {pair_dict['emp2_name']}"
                )
            else:
                auto_fp += 1
                false_positives.append(
                    {
                        **pair_dict,
                        "llm_response": outcome.response,
                        "reason": "False positive - should not be clustered",
                    }
                )
                logger.warning(
                    f"False positive {auto_fp}: {pair_dict['emp1_name']} ≠ {pair_dict['emp2_name']} "
                    f"(similarity={pair_dict['similarity']:.3f})"
                )

        return PairEvaluationStats(
            true_positives=auto_tp,
            false_positives=auto_fp,
            skipped=auto_skipped,
            total=len(auto_sample),
            error_pairs=false_positives,
        )

    async def _evaluate_auto_clustered_pairs_async(
        self, auto_sample: list
    ) -> PairEvaluationStats:
        """
        Evaluate auto-clustered pairs in parallel (async).

        Returns:
            PairEvaluationStats with counts and false positives list
        """
        from lib.business.salary.llm_verifier import validate_pairs_parallel_async

        # Convert to EmployerPair objects if needed
        pairs = []
        for pair in auto_sample:
            if isinstance(pair, dict):
                pairs.append(
                    EmployerPair(
                        emp1_name=pair["emp1_name"],
                        emp1_city=pair.get("emp1_city"),
                        emp1_state=pair.get("emp1_state"),
                        emp2_name=pair["emp2_name"],
                        emp2_city=pair.get("emp2_city"),
                        emp2_state=pair.get("emp2_state"),
                        similarity=pair["similarity"],
                    )
                )
            else:
                pairs.append(pair)

        # Validate all pairs in parallel
        logger.info(
            f"Validating {len(pairs)} pairs in parallel (max_concurrent={self.max_concurrent})..."
        )
        outcomes = await validate_pairs_parallel_async(
            pairs,
            prompt_template_path=self.prompt_template_path,
            max_concurrent=self.max_concurrent,
        )

        # Process results
        auto_tp = 0
        auto_fp = 0
        auto_skipped = 0
        false_positives = []

        for i, (pair, outcome) in enumerate(zip(auto_sample, outcomes), 1):
            # Log progress every 20 pairs
            if i % 20 == 0 or i == 1:
                logger.info(
                    f"Progress: Processed {i}/{len(auto_sample)} auto-clustered pairs ({i / len(auto_sample) * 100:.1f}%)"
                )

            if outcome.is_same is None:
                auto_skipped += 1
                logger.warning(
                    f"Skipped auto-clustered pair {i}: LLM validation failed"
                )
                continue

            # Extract pair data for logging/error tracking
            pair_dict = (
                pair
                if isinstance(pair, dict)
                else {
                    "emp1_name": pair.emp1_name,
                    "emp1_city": pair.emp1_city,
                    "emp1_state": pair.emp1_state,
                    "emp2_name": pair.emp2_name,
                    "emp2_city": pair.emp2_city,
                    "emp2_state": pair.emp2_state,
                    "similarity": pair.similarity,
                }
            )

            if outcome.is_same:
                auto_tp += 1
                logger.debug(
                    f"True positive: {pair_dict['emp1_name']} = {pair_dict['emp2_name']}"
                )
            else:
                auto_fp += 1
                false_positives.append(
                    {
                        **pair_dict,
                        "llm_response": outcome.response,
                        "reason": "False positive - should not be clustered",
                    }
                )
                logger.warning(
                    f"False positive {auto_fp}: {pair_dict['emp1_name']} ≠ {pair_dict['emp2_name']} "
                    f"(similarity={pair_dict['similarity']:.3f})"
                )

        return PairEvaluationStats(
            true_positives=auto_tp,
            false_positives=auto_fp,
            skipped=auto_skipped,
            total=len(auto_sample),
            error_pairs=false_positives,
        )

    def _evaluate_queued_pairs(self, queue_sample: list) -> PairEvaluationStats:
        """
        Evaluate queued pairs (uncertain, need review).

        Note: For queued pairs, true_positives field represents false_negatives
        (pairs that should have been clustered), and false_positives field
        represents true_negatives (correctly identified as different).

        Uses parallel async validation if enabled for 2-4x speedup.

        Returns:
            PairEvaluationStats with counts and false negatives list
        """
        logger.info(f"Evaluating {len(queue_sample)} queued pairs...")

        # Use parallel async validation if enabled
        if self.use_parallel and self.llm_validator is None:
            return asyncio.run(self._evaluate_queued_pairs_async(queue_sample))

        # Fallback to sequential validation
        queue_tp = 0  # False negatives (should have been clustered)
        queue_fp = 0  # True negatives (correctly identified as different)
        queue_skipped = 0
        false_negatives = []

        for i, pair in enumerate(queue_sample, 1):
            # Log progress every 20 pairs
            if i % 20 == 0 or i == 1:
                logger.info(
                    f"Progress: Evaluating queued pair {i}/{len(queue_sample)} ({i / len(queue_sample) * 100:.1f}%)"
                )

            outcome = self._evaluate_single_pair(pair, "queued", i, len(queue_sample))

            if outcome.is_same is None:
                queue_skipped += 1
                logger.warning(f"Skipped queued pair {i}: LLM validation failed")
                continue

            # Extract pair data for logging/error tracking
            pair_dict = (
                pair
                if isinstance(pair, dict)
                else {
                    "emp1_name": pair.emp1_name,
                    "emp1_city": pair.emp1_city,
                    "emp1_state": pair.emp1_state,
                    "emp2_name": pair.emp2_name,
                    "emp2_city": pair.emp2_city,
                    "emp2_state": pair.emp2_state,
                    "similarity": pair.similarity,
                }
            )

            if outcome.is_same:
                queue_tp += 1  # False negative
                false_negatives.append(
                    {
                        **pair_dict,
                        "llm_response": outcome.response,
                        "reason": "False negative - should be clustered",
                    }
                )
                logger.warning(
                    f"False negative {queue_tp}: {pair_dict['emp1_name']} = {pair_dict['emp2_name']} "
                    f"(similarity={pair_dict['similarity']:.3f})"
                )
            else:
                queue_fp += 1  # True negative
                logger.debug(
                    f"True negative: {pair_dict['emp1_name']} ≠ {pair_dict['emp2_name']}"
                )

        return PairEvaluationStats(
            true_positives=queue_tp,  # Represents false negatives for queued pairs
            false_positives=queue_fp,  # Represents true negatives for queued pairs
            skipped=queue_skipped,
            total=len(queue_sample),
            error_pairs=false_negatives,
        )

    async def _evaluate_queued_pairs_async(
        self, queue_sample: list
    ) -> PairEvaluationStats:
        """
        Evaluate queued pairs in parallel (async).

        Returns:
            PairEvaluationStats with counts and false negatives list
        """
        from lib.business.salary.llm_verifier import validate_pairs_parallel_async

        # Convert to EmployerPair objects if needed
        pairs = []
        for pair in queue_sample:
            if isinstance(pair, dict):
                pairs.append(
                    EmployerPair(
                        emp1_name=pair["emp1_name"],
                        emp1_city=pair.get("emp1_city"),
                        emp1_state=pair.get("emp1_state"),
                        emp2_name=pair["emp2_name"],
                        emp2_city=pair.get("emp2_city"),
                        emp2_state=pair.get("emp2_state"),
                        similarity=pair["similarity"],
                    )
                )
            else:
                pairs.append(pair)

        # Validate all pairs in parallel
        logger.info(
            f"Validating {len(pairs)} queued pairs in parallel (max_concurrent={self.max_concurrent})..."
        )
        outcomes = await validate_pairs_parallel_async(
            pairs,
            prompt_template_path=self.prompt_template_path,
            max_concurrent=self.max_concurrent,
        )

        # Process results
        queue_tp = 0  # False negatives (should have been clustered)
        queue_fp = 0  # True negatives (correctly identified as different)
        queue_skipped = 0
        false_negatives = []

        for i, (pair, outcome) in enumerate(zip(queue_sample, outcomes), 1):
            # Log progress every 20 pairs
            if i % 20 == 0 or i == 1:
                logger.info(
                    f"Progress: Processed {i}/{len(queue_sample)} queued pairs ({i / len(queue_sample) * 100:.1f}%)"
                )

            if outcome.is_same is None:
                queue_skipped += 1
                logger.warning(f"Skipped queued pair {i}: LLM validation failed")
                continue

            # Extract pair data for logging/error tracking
            pair_dict = (
                pair
                if isinstance(pair, dict)
                else {
                    "emp1_name": pair.emp1_name,
                    "emp1_city": pair.emp1_city,
                    "emp1_state": pair.emp1_state,
                    "emp2_name": pair.emp2_name,
                    "emp2_city": pair.emp2_city,
                    "emp2_state": pair.emp2_state,
                    "similarity": pair.similarity,
                }
            )

            if outcome.is_same:
                queue_tp += 1  # False negative
                false_negatives.append(
                    {
                        **pair_dict,
                        "llm_response": outcome.response,
                        "reason": "False negative - should be clustered",
                    }
                )
                logger.warning(
                    f"False negative {queue_tp}: {pair_dict['emp1_name']} = {pair_dict['emp2_name']} "
                    f"(similarity={pair_dict['similarity']:.3f})"
                )
            else:
                queue_fp += 1  # True negative
                logger.debug(
                    f"True negative: {pair_dict['emp1_name']} ≠ {pair_dict['emp2_name']}"
                )

        return PairEvaluationStats(
            true_positives=queue_tp,  # Represents false negatives for queued pairs
            false_positives=queue_fp,  # Represents true negatives for queued pairs
            skipped=queue_skipped,
            total=len(queue_sample),
            error_pairs=false_negatives,
        )

    async def _evaluate_queued_pairs_async(
        self, queue_sample: list
    ) -> PairEvaluationStats:
        """
        Evaluate queued pairs in parallel (async).

        Returns:
            PairEvaluationStats with counts and false negatives list
        """
        from lib.business.salary.llm_verifier import validate_pairs_parallel_async

        # Convert to EmployerPair objects if needed
        pairs = []
        for pair in queue_sample:
            if isinstance(pair, dict):
                pairs.append(
                    EmployerPair(
                        emp1_name=pair["emp1_name"],
                        emp1_city=pair.get("emp1_city"),
                        emp1_state=pair.get("emp1_state"),
                        emp2_name=pair["emp2_name"],
                        emp2_city=pair.get("emp2_city"),
                        emp2_state=pair.get("emp2_state"),
                        similarity=pair["similarity"],
                    )
                )
            else:
                pairs.append(pair)

        # Validate all pairs in parallel
        logger.info(
            f"Validating {len(pairs)} queued pairs in parallel (max_concurrent={self.max_concurrent})..."
        )
        outcomes = await validate_pairs_parallel_async(
            pairs,
            prompt_template_path=self.prompt_template_path,
            max_concurrent=self.max_concurrent,
        )

        # Process results
        queue_tp = 0  # False negatives (should have been clustered)
        queue_fp = 0  # True negatives (correctly identified as different)
        queue_skipped = 0
        false_negatives = []

        for i, (pair, outcome) in enumerate(zip(queue_sample, outcomes), 1):
            # Log progress every 20 pairs
            if i % 20 == 0 or i == 1:
                logger.info(
                    f"Progress: Processed {i}/{len(queue_sample)} queued pairs ({i / len(queue_sample) * 100:.1f}%)"
                )

            if outcome.is_same is None:
                queue_skipped += 1
                logger.warning(f"Skipped queued pair {i}: LLM validation failed")
                continue

            # Extract pair data for logging/error tracking
            pair_dict = (
                pair
                if isinstance(pair, dict)
                else {
                    "emp1_name": pair.emp1_name,
                    "emp1_city": pair.emp1_city,
                    "emp1_state": pair.emp1_state,
                    "emp2_name": pair.emp2_name,
                    "emp2_city": pair.emp2_city,
                    "emp2_state": pair.emp2_state,
                    "similarity": pair.similarity,
                }
            )

            if outcome.is_same:
                queue_tp += 1  # False negative
                false_negatives.append(
                    {
                        **pair_dict,
                        "llm_response": outcome.response,
                        "reason": "False negative - should be clustered",
                    }
                )
                logger.warning(
                    f"False negative {queue_tp}: {pair_dict['emp1_name']} = {pair_dict['emp2_name']} "
                    f"(similarity={pair_dict['similarity']:.3f})"
                )
            else:
                queue_fp += 1  # True negative
                logger.debug(
                    f"True negative: {pair_dict['emp1_name']} ≠ {pair_dict['emp2_name']}"
                )

        return PairEvaluationStats(
            true_positives=queue_tp,  # Represents false negatives for queued pairs
            false_positives=queue_fp,  # Represents true negatives for queued pairs
            skipped=queue_skipped,
            total=len(queue_sample),
            error_pairs=false_negatives,
        )

    def _calculate_metrics(
        self, auto_stats: PairEvaluationStats, queue_stats: PairEvaluationStats
    ) -> dict:
        """Calculate precision, recall, and F1 metrics."""
        auto_precision = (
            auto_stats.true_positives
            / (auto_stats.true_positives + auto_stats.false_positives)
            if (auto_stats.true_positives + auto_stats.false_positives) > 0
            else 0.0
        )

        queue_precision = (
            queue_stats.true_positives
            / (queue_stats.true_positives + queue_stats.false_positives)
            if (queue_stats.true_positives + queue_stats.false_positives) > 0
            else 0.0
        )

        # Overall precision = TP / (TP + FP) across both categories
        total_tp = auto_stats.true_positives + queue_stats.true_positives
        total_fp = auto_stats.false_positives + queue_stats.false_positives
        overall_precision = (
            total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        )

        # Overall recall = TP / (TP + FN)
        # TP = auto-clustered pairs that are same (auto_stats.true_positives)
        # FN = queued pairs that are same (queue_stats.true_positives, which are false negatives)
        overall_recall = (
            auto_stats.true_positives
            / (auto_stats.true_positives + queue_stats.true_positives)
            if (auto_stats.true_positives + queue_stats.true_positives) > 0
            else 0.0
        )

        # F1 score
        f1_score = (
            2
            * (overall_precision * overall_recall)
            / (overall_precision + overall_recall)
            if (overall_precision + overall_recall) > 0
            else 0.0
        )

        return {
            "auto_clustered": {
                "true_positives": auto_stats.true_positives,
                "false_positives": auto_stats.false_positives,
                "skipped": auto_stats.skipped,
                "total": auto_stats.total,
                "precision": auto_precision,
            },
            "queued_for_review": {
                "true_negatives": queue_stats.false_positives,  # Correctly identified as different
                "false_negatives": queue_stats.true_positives,  # Should have been clustered
                "skipped": queue_stats.skipped,
                "total": queue_stats.total,
                "precision": queue_precision,
            },
            "overall": {
                "precision": overall_precision,
                "recall": overall_recall,
                "f1_score": f1_score,
                "true_positives": total_tp,
                "false_positives": total_fp,
            },
        }

    def evaluate_samples(
        self, auto_sample: list, queue_sample: list
    ) -> EvaluationResults:
        """
        Evaluate auto-clustered and queued pairs.

        Args:
            auto_sample: List of auto-clustered pairs (should be same company)
            queue_sample: List of queued pairs (uncertain, need review)

        Returns:
            EvaluationResults with metrics, false_positives, and false_negatives
        """
        # Evaluate auto-clustered pairs
        auto_stats = self._evaluate_auto_clustered_pairs(auto_sample)

        # Evaluate queued pairs
        queue_stats = self._evaluate_queued_pairs(queue_sample)

        # Calculate metrics
        metrics = self._calculate_metrics(auto_stats, queue_stats)

        # Log summary
        logger.info("Evaluation complete:")
        logger.info(
            f"  Auto-clustered: {auto_stats.true_positives} TP, {auto_stats.false_positives} FP, {auto_stats.skipped} skipped"
        )
        logger.info(
            f"  Queued: {queue_stats.true_positives} FN, {queue_stats.false_positives} TN, {queue_stats.skipped} skipped"
        )
        logger.info(
            f"  Overall: Precision={metrics['overall']['precision']:.2%}, "
            f"Recall={metrics['overall']['recall']:.2%}, "
            f"F1={metrics['overall']['f1_score']:.3f}"
        )

        return EvaluationResults(
            metrics=metrics,
            false_positives=auto_stats.error_pairs,
            false_negatives=queue_stats.error_pairs,
        )

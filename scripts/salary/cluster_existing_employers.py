#!/usr/bin/env python3
"""
Cluster existing employers in the database

Compares all employer pairs and:
- Auto-clusters high-confidence matches
- Queues ambiguous cases for review
"""

import os
import sys
import time
import difflib
import json
import logging
import random
from collections import defaultdict
from typing import Optional, Tuple, Set
from pathlib import Path

# Import tqdm for progress bars (optional - gracefully handles if not available)
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    # Create a dummy tqdm class if not available
    class tqdm:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def update(self, n=1):
            pass
        def set_description(self, desc):
            pass

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django
django.setup()

from django.db import transaction
from datasketch import MinHash, MinHashLSH
from models.salary import Employer, EmployerCluster, EmployerClusteringReview
from lib.business.salary.employer_clustering import (
    match_employers,
    fuzzy_match,
    should_auto_cluster,
    assign_to_cluster,
)
from lib.utils.logging_utils import ScriptLogger
from lib.utils.rate_limited_logger import RateLimitedLogger
from lib.utils.db_utils import bulk_update_batched, bulk_create_batched, BatchedUpdates
from django_config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

# Rate limited logger for auto-cluster messages
auto_cluster_logger = RateLimitedLogger(
    initial_count=5,
    min_interval_seconds=5.0,
    logger=logger,
    log_level=logging.INFO  # Changed to INFO to be visible but rate limited
)

# Checkpoint file path (default: /tmp/clustering_checkpoint.json)
CHECKPOINT_FILE = os.environ.get('CLUSTERING_CHECKPOINT_FILE', '/tmp/clustering_checkpoint.json')


def save_checkpoint_incremental(
    phase1_new: set[str],
    phase2_new: set[tuple[str, str]],
    checkpoint_file: str = CHECKPOINT_FILE
):
    """
    Save checkpoint incrementally using database (memory-efficient, no file I/O).
    
    Uses database table to store checkpoint items, avoiding:
    - Memory accumulation (checkpoint items stored in DB, not memory)
    - File I/O overhead (database is optimized for this)
    - Full file rewrites (incremental inserts)
    """
    if not phase1_new and not phase2_new:
        return  # Nothing to save
    
    try:
        from django.db import transaction
        from models.salary import ClusteringCheckpoint
        
        with transaction.atomic():
            # Bulk create checkpoint entries (database handles deduplication via unique constraint)
            checkpoint_entries = []
            for name in phase1_new:
                checkpoint_entries.append(
                    ClusteringCheckpoint(phase='phase1', item_key=name)
                )
            for norm1, norm2 in phase2_new:
                # Store pair as sorted tuple string for consistency
                pair_key = f"{norm1}|{norm2}" if norm1 < norm2 else f"{norm2}|{norm1}"
                checkpoint_entries.append(
                    ClusteringCheckpoint(phase='phase2', item_key=pair_key)
                )
            
            # Bulk create with ignore_conflicts to handle duplicates gracefully
            ClusteringCheckpoint.objects.bulk_create(
                checkpoint_entries,
                ignore_conflicts=True
            )
        
        logger.debug(f"Checkpoint updated: +{len(phase1_new)} phase1, +{len(phase2_new)} phase2")
    except Exception as e:
        logger.warning(f"Failed to save checkpoint: {e}")


def load_checkpoint() -> Optional[dict]:
    """
    Load checkpoint data from database.
    
    Loads all processed items into memory sets for fast O(1) lookups.
    This is more efficient than querying the database for each item.
    
    Note: Checkpoint is now stored in database, not files, so no file path needed.
    """
    try:
        from models.salary import ClusteringCheckpoint
        
        # Load all processed items into sets (one-time cost, then O(1) lookups)
        phase1_processed = set(
            ClusteringCheckpoint.objects.filter(phase='phase1')
            .values_list('item_key', flat=True)
        )
        phase2_processed = set(
            ClusteringCheckpoint.objects.filter(phase='phase2')
            .values_list('item_key', flat=True)
        )
        
        if len(phase1_processed) == 0 and len(phase2_processed) == 0:
            return None
        
        logger.info(f"Loaded checkpoint from database")
        logger.info(f"  Phase 1 processed: {len(phase1_processed):,} normalized names")
        logger.info(f"  Phase 2 processed: {len(phase2_processed):,} candidate pairs")
        
        return {
            'phase1_processed': phase1_processed,
            'phase2_processed': phase2_processed,
        }
    except Exception as e:
        logger.warning(f"Failed to load checkpoint: {e}")
        return None


def is_phase1_processed(normalized_name: str, checkpoint: Optional[dict]) -> bool:
    """Check if normalized name is already processed (using in-memory set)"""
    if not checkpoint:
        return False
    return normalized_name in checkpoint.get('phase1_processed', set())


def is_phase2_processed(norm1: str, norm2: str, checkpoint: Optional[dict]) -> bool:
    """Check if candidate pair is already processed (using in-memory set)"""
    if not checkpoint:
        return False
    # Store pair as sorted tuple string for consistency (matches how we save it)
    pair_key = f"{norm1}|{norm2}" if norm1 < norm2 else f"{norm2}|{norm1}"
    return pair_key in checkpoint.get('phase2_processed', set())


def save_checkpoint(checkpoint_data: dict, checkpoint_file: str = CHECKPOINT_FILE):
    """
    Legacy full checkpoint save (for backward compatibility).
    
    Note: This rewrites the entire file. Use save_checkpoint_incremental() for better performance.
    """
    try:
        checkpoint_dir = Path(checkpoint_file).parent
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f, indent=2)
        logger.debug(f"Checkpoint saved to {checkpoint_file}")
    except Exception as e:
        logger.warning(f"Failed to save checkpoint: {e}")


def clear_checkpoint(checkpoint_file: str = CHECKPOINT_FILE):
    """Clear checkpoint (database table)"""
    try:
        from models.salary import ClusteringCheckpoint
        deleted_count, _ = ClusteringCheckpoint.objects.all().delete()
        logger.info(f"Checkpoint cleared: {deleted_count:,} entries removed from database")
    except Exception as e:
        logger.warning(f"Failed to clear checkpoint: {e}")


class ProgressTracker:
    """Track progress with ETA calculation and optional tqdm progress bar"""
    
    def __init__(self, total: int, phase_name: str, use_progress_bar: bool = True):
        self.total = total
        self.processed = 0
        self.phase_name = phase_name
        self.start_time = time.time()
        self.last_log_time = self.start_time
        self.last_log_count = 0
        self.use_progress_bar = use_progress_bar and TQDM_AVAILABLE
        
        # Initialize tqdm progress bar if available and enabled
        if self.use_progress_bar and total > 0:
            # Use tqdm with file=sys.stderr to avoid interfering with logging
            self.pbar = tqdm(
                total=total,
                desc=phase_name,
                unit="pairs",
                unit_scale=False,
                file=sys.stderr,  # Write to stderr so it doesn't interfere with log files
                ncols=100,  # Progress bar width
                mininterval=1.0,  # Update at least once per second
            )
        else:
            self.pbar = None
    
    def update(self, count: int = 1):
        """Update progress counter"""
        self.processed += count
        if self.pbar:
            self.pbar.update(count)
    
    def log_progress(self, batch_size: int = 1000):
        """Log progress with ETA if at batch interval (for non-tqdm logging)"""
        # If using tqdm, it handles display automatically - just log periodically
        if self.pbar:
            # Update tqdm description with rate info
            elapsed = time.time() - self.start_time
            rate = self.processed / elapsed if elapsed > 0 else 0
            if rate > 0 and self.total > 0:
                remaining = self.total - self.processed
                eta_seconds = remaining / rate
                eta_minutes = eta_seconds / 60
                self.pbar.set_description(
                    f"{self.phase_name} | {rate:.0f} pairs/sec | ETA: {eta_minutes:.1f}m"
                )
            # Log to file periodically for monitoring (at most once per 5 sec, at least once per 1000 pairs)
            current_time = time.time()
            pairs_since_last_log = self.processed - self.last_log_count
            time_since_last_log = current_time - self.last_log_time
            
            should_log = (
                pairs_since_last_log >= 1000 or
                time_since_last_log >= 5.0
            )
            
            if should_log:
                logger.info(
                    f"[{self.phase_name}] Processed {self.processed:,}/{self.total:,} pairs "
                    f"({self.processed/self.total*100:.1f}%) | Rate: {rate:.0f} pairs/sec | ETA: {eta_minutes:.1f} min"
                )
                self.last_log_time = current_time
                self.last_log_count = self.processed
            return
        
        # Original logging logic (when tqdm not available)
        if self.processed % batch_size != 0:
            return
        
        elapsed = time.time() - self.start_time
        rate = self.processed / elapsed if elapsed > 0 else 0
        
        if rate > 0:
            if self.total > 0:
                # Known total - show percentage and ETA
                remaining = self.total - self.processed
                eta_seconds = remaining / rate
                eta_minutes = eta_seconds / 60
                percentage = (self.processed / self.total) * 100
                
                logger.info(
                    f"[{self.phase_name}] Processed {self.processed:,}/{self.total:,} pairs "
                    f"({percentage:.1f}%) | Rate: {rate:.0f} pairs/sec | ETA: {eta_minutes:.1f} min"
                )
            else:
                # Unknown total (dynamic ETA) - estimate based on recent rate trend
                # For Phase 2, estimate remaining based on normalized name pairs processed
                # Rough estimate: if we've processed X pairs, estimate 10X-50X more (depends on employer pairs per normalized name)
                if self.processed >= batch_size * 2:  # Need at least 2 data points for trend
                    # Estimate: assume similar rate continues, estimate 10x-20x more pairs
                    # This is rough but gives some sense of progress
                    estimated_remaining = self.processed * 10  # Conservative estimate
                    eta_seconds = estimated_remaining / rate if rate > 0 else 0
                    eta_minutes = eta_seconds / 60
                    logger.info(
                        f"[{self.phase_name}] Processed {self.processed:,} pairs | "
                        f"Rate: {rate:.0f} pairs/sec | "
                        f"Est. ETA: {eta_minutes:.1f} min (rough estimate)"
                    )
                else:
                    # Not enough data yet - just show rate
                    logger.info(
                        f"[{self.phase_name}] Processed {self.processed:,} pairs | Rate: {rate:.0f} pairs/sec"
                    )
        else:
            logger.info(f"[{self.phase_name}] Processed {self.processed:,} pairs...")
    
    def close(self):
        """Close progress bar if using tqdm"""
        if self.pbar:
            self.pbar.close()
    
    def get_summary(self) -> dict:
        """Get progress summary"""
        elapsed = time.time() - self.start_time
        rate = self.processed / elapsed if elapsed > 0 else 0
        percentage = (self.processed / self.total) * 100 if self.total > 0 else 0
        return {
            'processed': self.processed,
            'total': self.total,
            'percentage': percentage,
            'elapsed_seconds': elapsed,
            'rate_per_second': rate
        }


def calculate_phase1_total_pairs(employers_by_normalized: dict) -> int:
    """Calculate total pairs for phase 1 (same normalized names)"""
    total = 0
    for employers in employers_by_normalized.values():
        n = len(employers)
        if n > 1:
            # Number of pairs = n*(n-1)/2
            total += n * (n - 1) // 2
    return total


def _load_and_group_employers(
    shuffle: bool = False, 
    seed: Optional[int] = None,
    limit: Optional[int] = None
) -> Tuple[list[Employer], dict[str, list[Employer]]]:
    """
    Load employers and group by normalized name.
    
    Note: Re-normalizes names on-the-fly from original 'name' field to ensure
    we use the latest normalization logic (with generic word filtering).
    Existing name_normalized values in DB may be outdated.
    
    Args:
        shuffle: If True, shuffle employers before grouping (for random sampling)
        seed: Random seed for shuffling (for reproducibility)
        limit: Limit number of employers to load (for fast debugging)
    """
    logger.info("Loading employers...")
    # Load only fields needed for clustering to reduce memory (critical for 2GB instances)
    # Fields needed: id, name, city, state, canonical_cluster (for matching logic)
    # Skip: name_normalized, slug, created_at, updated_at (not used in clustering)
    qs = Employer.objects.all().select_related('canonical_cluster').only(
        'id', 'name', 'city', 'state', 'canonical_cluster'
    )
    
    if limit and not shuffle:
        # If limiting and not shuffling, we can limit at DB level for speed
        qs = qs[:limit]
        
    all_employers = list(qs)
    total = len(all_employers)
    logger.info(f"Found {total:,} employers to process")
    
    if total == 0:
        return [], {}
    
    # Shuffle for random sampling if requested
    if shuffle:
        if seed is not None:
            random.seed(seed)
        random.shuffle(all_employers)
        if limit:
            all_employers = all_employers[:limit]
            logger.info(f"Selected {len(all_employers):,} random employers (limit={limit})")
        else:
            logger.info(f"Shuffled {len(all_employers):,} employers (seed={seed})")
    elif limit and total > limit:
        # Should have been handled by DB limit, but just in case
        all_employers = all_employers[:limit]
    
    logger.info("Grouping employers by normalized name (re-normalizing from original names)...")
    employers_by_normalized = defaultdict(list)
    for emp in all_employers:
        # Re-normalize from original name to ensure we use latest normalization logic
        # (with generic word filtering). Don't use stored name_normalized which may be outdated.
        normalized = Employer.normalize_name(emp.name)
        employers_by_normalized[normalized].append(emp)
    
    unique_normalized = len(employers_by_normalized)
    logger.info(f"Found {unique_normalized:,} unique normalized names")
    
    return all_employers, dict(employers_by_normalized)


def _process_single_employer_cluster(
    emp: Employer,
    auto_approve_threshold: float,
    dry_run: bool,
    batched_updates: Optional['BatchedUpdates'] = None
) -> int:
    """Process single employer (no matches with same normalized name)"""
    if not emp.canonical_cluster:
        if not dry_run:
            if batched_updates:
                # Use batched cluster creation
                cluster = batched_updates.get_or_queue_cluster(emp.name)
                emp.canonical_cluster = cluster
                batched_updates.add_employer_update(emp)
            else:
                # Fallback: direct creation (for backward compatibility)
                from models.salary import EmployerCluster
                cluster = EmployerCluster.objects.create(canonical_name=emp.name)
                emp.canonical_cluster = cluster
                emp.save(update_fields=['canonical_cluster'])
        return 1
    return 0


# Module-level variables for pair logging and early stopping
_process_employer_pair_output_file = None
_process_employer_pair_min_pairs = None  # Stop when we have this many pairs
_process_employer_pair_pairs_collected = {'auto': 0}  # Track collected pairs

def _process_employer_pair(
    emp1: Employer,
    emp2: Employer,
    auto_approve_threshold: float,
    dry_run: bool,
    batched_updates: BatchedUpdates
) -> int:
    """
    Process a pair of employers - cluster if matches rules.
    
    PERFORMANCE NOTE: This function calls `should_auto_cluster` which calls `match_employers`.
    `match_employers` re-normalizes both names, which is redundant since we already have
    normalized names in the calling functions.
    
    Optimization hint: Pass `norm1` and `norm2` down from caller to avoid re-normalization.
    This would save 2 normalization calls per pair (regex + string ops).
    
    Returns: auto_clustered_count (1 or 0)
    """
    # Check early stopping condition
    global _process_employer_pair_min_pairs, _process_employer_pair_pairs_collected
    if _process_employer_pair_min_pairs is not None:
        total_collected = _process_employer_pair_pairs_collected['auto']
        if total_collected >= _process_employer_pair_min_pairs:
            # Signal to stop (return special value or raise exception)
            raise StopIteration("Enough pairs collected for sampling")
    
    # Skip if already in same cluster
    if emp1.canonical_cluster and emp2.canonical_cluster:
        if emp1.canonical_cluster.id == emp2.canonical_cluster.id:
            return 0
    
    # Check if should auto-cluster
    should_cluster, confidence, reason = should_auto_cluster(
        emp1, emp2, threshold=auto_approve_threshold
    )
    
    if should_cluster:
        # Auto-cluster
        if not dry_run:
            # Optimized: We already know these employers match, so we don't need to search
            # for existing clusters via assign_to_cluster (which loads all employers).
            # Instead, reuse existing cluster or queue for batch creation.
            from models.salary import EmployerCluster
            
            # Get or queue cluster for emp1
            if not emp1.canonical_cluster:
                # Queue cluster creation (will be batch created)
                cluster = batched_updates.get_or_queue_cluster(emp1.name)
                emp1.canonical_cluster = cluster
                batched_updates.add_employer_update(emp1)
            else:
                cluster = emp1.canonical_cluster
            
            # Assign emp2 to same cluster
            emp2.canonical_cluster = cluster
            batched_updates.add_employer_update(emp2)
        
        auto_cluster_logger.log(f"Auto-clustered: {emp1.name} <-> {emp2.name} ({confidence:.3f})")
        
        # Increment counter regardless of output file
        _process_employer_pair_pairs_collected['auto'] += 1
        
        # Also log to structured output file if requested
        if _process_employer_pair_output_file:
            _process_employer_pair_output_file.write(
                json.dumps({
                    'type': 'auto_clustered',
                    'emp1_id': emp1.id,
                    'emp1_name': emp1.name,
                    'emp1_city': emp1.city or '',
                    'emp1_state': emp1.state or '',
                    'emp2_id': emp2.id,
                    'emp2_name': emp2.name,
                    'emp2_city': emp2.city or '',
                    'emp2_state': emp2.state or '',
                    'similarity': confidence,
                    'reason': reason
                }) + '\n'
            )
        return 1
        
    return 0


def _process_employer_pairs_batch(
    employers: list[Employer],
    auto_approve_threshold: float,
    dry_run: bool,
    batched_updates: BatchedUpdates,
    progress: ProgressTracker,
    batch_size: int
) -> int:
    """
    Process all pairs of employers in a list (shared logic for phase 1 and phase 2)
    
    Returns: auto_clustered_count
    """
    auto_clustered = 0
    
    # Note: We don't catch StopIteration here so it propagates to the caller
    # (e.g. _process_same_normalized_name_matches) which handles early stopping
    # for the entire phase.
    for i in range(len(employers)):
        for j in range(i + 1, len(employers)):
            emp1 = employers[i]
            emp2 = employers[j]
            
            pair_auto = _process_employer_pair(
                emp1, emp2, auto_approve_threshold, dry_run, batched_updates
            )
            auto_clustered += pair_auto
            
            progress.update()
            progress.log_progress(batch_size)
    
    return auto_clustered


def _process_cross_employer_pairs(
    employers1: list[Employer],
    employers2: list[Employer],
    auto_approve_threshold: float,
    dry_run: bool,
    batched_updates: BatchedUpdates,
    norm1: Optional[str] = None,
    norm2: Optional[str] = None
) -> Tuple[int, int]:
    """
    Process all pairs between two lists of employers (cartesian product)
    Skips pairs that are already in the same cluster.
    
    Returns: (auto_clustered, processed_pairs)
    """
    auto_clustered = 0
    processed_pairs = 0
    
    for emp1 in employers1:
        for emp2 in employers2:
            # Skip if already in same cluster
            if emp1.canonical_cluster and emp2.canonical_cluster:
                if emp1.canonical_cluster.id == emp2.canonical_cluster.id:
                    processed_pairs += 1
                    continue
            
            # Process employer pair (normalization happens inside _process_employer_pair)
            pair_auto = _process_employer_pair(
                emp1, emp2, auto_approve_threshold, dry_run, batched_updates
            )
            auto_clustered += pair_auto
            processed_pairs += 1
    
    return auto_clustered, processed_pairs


def _process_same_normalized_name_matches(
    employers_by_normalized: dict[str, list[Employer]],
    auto_approve_threshold: float,
    batch_size: int,
    dry_run: bool,
    checkpoint_file: Optional[str] = None
) -> Tuple[int, int]:
    """
    Phase 1: Process employers with same normalized name
    
    Returns: (auto_clustered, clusters_created)
    """
    logger.info("\n" + "="*60)
    logger.info("PHASE 1: Processing same normalized name matches")
    logger.info("="*60)
    
    # Load checkpoint if resuming (loads all processed items into memory sets)
    checkpoint = load_checkpoint() if checkpoint_file else None
    
    if checkpoint:
        phase1_processed = checkpoint.get('phase1_processed', set())
        if phase1_processed:
            logger.info(f"Resuming Phase 1: {len(phase1_processed):,} already-processed normalized names")
    
    # Pre-calculate total pairs for phase 1 (only count unprocessed)
    # Filter out already-processed names using in-memory set lookups (O(1) per lookup)
    unprocessed_employers = {
        k: v for k, v in employers_by_normalized.items()
        if not is_phase1_processed(k, checkpoint)
    }
    phase1_total = calculate_phase1_total_pairs(unprocessed_employers)
    if checkpoint:
        phase1_count = len(checkpoint.get('phase1_processed', set()))
        logger.info(f"Phase 1: Will process {phase1_total:,} pairs ({phase1_count:,} already done)")
    else:
        logger.info(f"Phase 1: Will process {phase1_total:,} pairs")
    
    progress = ProgressTracker(phase1_total, "Phase 1")
    batched_updates = BatchedUpdates(batch_size=batch_size, dry_run=dry_run)
    
    auto_clustered = 0
    clusters_created = 0
    
    checkpoint_interval = 100  # Save checkpoint every 100 normalized names
    names_processed_since_checkpoint = 0
    pending_checkpoint_names = set()  # Batch checkpoint saves for efficiency
    
    try:
        for normalized_name, employers in employers_by_normalized.items():
            # Skip if already processed (uses in-memory set lookup, O(1))
            if is_phase1_processed(normalized_name, checkpoint):
                continue
            
            if len(employers) == 1:
                # Single employer - create cluster if needed
                clusters_created += _process_single_employer_cluster(
                    employers[0], auto_approve_threshold, dry_run, batched_updates
                )
            else:
                # Multiple employers with same normalized name - compare all pairs
                # Note: We still need to process pairs to handle cases where employers might already
                # be in different clusters (from previous runs or Phase 2 matches)
                pair_auto = _process_employer_pairs_batch(
                    employers, auto_approve_threshold, dry_run, batched_updates, progress, batch_size
                )
                auto_clustered += pair_auto
            
            # Mark as processed and batch checkpoint saves (incremental, DB-backed, memory-efficient)
            # Note: We don't maintain phase1_processed set anymore - DB queries handle membership checks
            pending_checkpoint_names.add(normalized_name)
            names_processed_since_checkpoint += 1
            
            if checkpoint_file and names_processed_since_checkpoint >= checkpoint_interval:
                # Save batched new items incrementally (append-only, no full file rewrite)
                save_checkpoint_incremental(pending_checkpoint_names, set(), checkpoint_file)
                pending_checkpoint_names.clear()
                names_processed_since_checkpoint = 0
    except StopIteration:
        logger.info(f"Early stopping in Phase 1: Collected enough pairs for sampling")
        batched_updates.flush_all()
    
    # Final checkpoint save (incremental) - save any remaining batched items
    if checkpoint_file and pending_checkpoint_names:
        save_checkpoint_incremental(pending_checkpoint_names, set(), checkpoint_file)
    
    # Final bulk operations for phase 1
    batched_updates.flush_all(employer_fields=['canonical_cluster'])
    
    phase1_summary = progress.get_summary()
    progress.close()  # Close progress bar
    logger.info(f"\nPhase 1 complete: {phase1_summary['processed']:,} pairs in {phase1_summary['elapsed_seconds']:.1f}s "
                f"({phase1_summary['rate_per_second']:.0f} pairs/sec)")
    
    return auto_clustered, clusters_created


def _get_normalized_name_similarity(norm1: str, norm2: str) -> float:
    """
    Get similarity between two normalized names.
    
    Generic words are already removed during normalization, so we can use normalized names directly.
    
    Note: No caching needed - each normalized name pair is compared exactly once
    in the Phase 2 iteration, so cache would never be reused.
    """
    return difflib.SequenceMatcher(None, norm1, norm2).ratio()


def _build_lsh_index(normalized_names: list[str], threshold: float = 0.7) -> Tuple[MinHashLSH, dict[str, MinHash]]:
    """
    Build LSH index for fast similarity search.
    
    Returns: (LSH index, mapping of normalized_name -> MinHash)
    """
    logger.info(f"Building LSH index for {len(normalized_names):,} normalized names...")
    start_time = time.time()
    
    # Create LSH index with threshold
    # num_perm controls precision: higher = more accurate but slower
    # 128 is a good balance for string similarity (provides good accuracy)
    lsh = MinHashLSH(threshold=threshold, num_perm=128)
    minhashes = {}
    
    # Progress tracking
    last_log = 0
    log_interval = max(10000, len(normalized_names) // 20)  # Log ~20 times
    
    for idx, norm_name in enumerate(normalized_names):
        # Create MinHash for this normalized name
        m = MinHash(num_perm=128)
        
        # Add words to MinHash (split by space)
        words = norm_name.split()
        for word in words:
            if word:  # Skip empty strings
                m.update(word.encode('utf8'))
        
        # Add character 3-grams for better matching of similar strings
        # Limit to avoid excessive computation for very long names
        max_ngrams = min(50, len(norm_name) - 2)  # Cap at 50 n-grams per name
        for i in range(max_ngrams):
            m.update(norm_name[i:i+3].encode('utf8'))
        
        minhashes[norm_name] = m
        lsh.insert(norm_name, m)
        
        # Progress logging
        if (idx + 1) - last_log >= log_interval:
            elapsed = time.time() - start_time
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            logger.info(f"  Processed {idx + 1:,}/{len(normalized_names):,} names "
                       f"({(idx + 1) / len(normalized_names) * 100:.1f}%) | "
                       f"Rate: {rate:.0f} names/sec")
            last_log = idx + 1
    
    elapsed = time.time() - start_time
    logger.info(f"LSH index built in {elapsed:.1f}s ({len(normalized_names):,} names, "
               f"{len(normalized_names) / elapsed:.0f} names/sec)")
    
    return lsh, minhashes


def _process_cross_normalized_name_matches(
    normalized_names: list[str],
    employers_by_normalized: dict[str, list[Employer]],
    auto_approve_threshold: float,
    batch_size: int,
    dry_run: bool,
    checkpoint_file: Optional[str] = None
) -> int:
    """
    Phase 2: Check employers with different normalized names but high similarity
    Uses LSH (Locality-Sensitive Hashing) to find candidate pairs efficiently.
    
    PERFORMANCE BOTTLENECK:
    This function processes O(K) candidate pairs where K is ~400k for the full dataset.
    The bottleneck is the CPU-bound string comparison logic in match_employers() which runs for every pair.
    
    Processing time: ~30-40 minutes for full dataset (~200 pairs/sec).
    
    Optimization opportunities:
    1. Pass normalized names to match_employers() to avoid re-normalization (regex/string ops)
       - Currently match_employers() re-calls normalize_name() internally
    2. Reduce candidate set size by increasing LSH threshold (trade-off with recall)
    3. Parallelize pair processing (multiprocessing)
    
    Returns: auto_clustered
    """
    logger.info("\n" + "="*60)
    logger.info("PHASE 2: Processing cross-normalized-name matches (LSH-based)")
    logger.info("="*60)
    
    # Build LSH index for fast similarity search
    lsh_threshold = 0.7  # LSH threshold (should match similarity threshold)
    lsh, minhashes = _build_lsh_index(normalized_names, threshold=lsh_threshold)
    
    # Track candidate pairs found by LSH
    candidate_pairs: Set[Tuple[str, str]] = set()
    
    logger.info("Querying LSH index for candidate pairs...")
    query_start = time.time()
    
    # Query LSH for each normalized name to find similar candidates
    for norm_name in normalized_names:
        m = minhashes[norm_name]
        candidates = lsh.query(m)
        
        # Add candidate pairs (avoid duplicates by using sorted tuple)
        for candidate in candidates:
            if candidate != norm_name:  # Skip self
                # Use sorted tuple to ensure (a, b) == (b, a)
                pair = tuple(sorted([norm_name, candidate]))
                candidate_pairs.add(pair)
    
    query_elapsed = time.time() - query_start
    logger.info(f"Found {len(candidate_pairs):,} candidate normalized name pairs via LSH in {query_elapsed:.1f}s")
    logger.info(f"  (Compared to {len(normalized_names) * (len(normalized_names) - 1) // 2:,} total pairs - "
                f"{len(normalized_names) * (len(normalized_names) - 1) // 2 / max(len(candidate_pairs), 1):.0f}x reduction)")
    
    # Load checkpoint if resuming (uses DB queries, not memory sets)
    checkpoint = load_checkpoint() if checkpoint_file else None
    
    if checkpoint:
        phase2_processed = checkpoint.get('phase2_processed', set())
        if phase2_processed:
            logger.info(f"Resuming Phase 2: {len(phase2_processed):,} already-processed candidate pairs")
            # Filter out already-processed pairs using in-memory set lookups (O(1) per lookup)
            remaining_pairs = set()
            for norm1, norm2 in candidate_pairs:
                pair_key = f"{norm1}|{norm2}" if norm1 < norm2 else f"{norm2}|{norm1}"
                if pair_key not in phase2_processed:
                    remaining_pairs.add((norm1, norm2))
            candidate_pairs = remaining_pairs
            logger.info(f"  Remaining candidate pairs: {len(candidate_pairs):,}")
    
    # Track progress through candidate pairs
    candidate_progress = ProgressTracker(len(candidate_pairs), "Phase 2 (candidates)")
    batched_updates = BatchedUpdates(batch_size=batch_size, dry_run=dry_run)
    
    auto_clustered = 0
    processed_pairs = 0
    
    checkpoint_interval = 1000  # Save checkpoint every 1000 candidate pairs
    pairs_processed_since_checkpoint = 0
    pending_checkpoint_pairs = set()  # Batch checkpoint saves for efficiency
    
    try:
        # Process candidate pairs (much smaller set than all pairs)
        for norm1, norm2 in candidate_pairs:
            candidate_progress.update()
            candidate_progress.log_progress(batch_size=1000)  # Log every 1k candidate pairs
            
            # Verify similarity with exact calculation (LSH may have false positives)
            similarity = _get_normalized_name_similarity(norm1, norm2)
            
            # Only process if similarity is actually >= 0.7 (filter false positives)
            if similarity >= 0.7:
                employers1 = employers_by_normalized[norm1]
                employers2 = employers_by_normalized[norm2]
                
                # Process all employer pairs between these two normalized names
                # Optimization: Pass normalized names to avoid re-normalization in inner loop
                pair_auto, pair_count = _process_cross_employer_pairs(
                    employers1, employers2, auto_approve_threshold, dry_run, batched_updates,
                    norm1=norm1, norm2=norm2
                )
                auto_clustered += pair_auto
                processed_pairs += pair_count
                
                # Mark as processed and batch checkpoint saves (incremental, DB-backed, memory-efficient)
                # Note: We don't maintain phase2_processed set anymore - DB queries handle membership checks
                pending_checkpoint_pairs.add((norm1, norm2))
                pairs_processed_since_checkpoint += 1
            
            if checkpoint_file and pairs_processed_since_checkpoint >= checkpoint_interval:
                # Save batched new items incrementally (append-only, no full file rewrite)
                save_checkpoint_incremental(set(), pending_checkpoint_pairs, checkpoint_file)
                pending_checkpoint_pairs.clear()
                pairs_processed_since_checkpoint = 0
    except StopIteration:
        logger.info(f"Early stopping in Phase 2: Collected enough pairs for sampling")
        batched_updates.flush_all()
    
    # Final checkpoint save (incremental) - save any remaining batched items
    if checkpoint_file and pending_checkpoint_pairs:
        save_checkpoint_incremental(set(), pending_checkpoint_pairs, checkpoint_file)
    
    # Final bulk operations for phase 2
    batched_updates.flush_all(employer_fields=['canonical_cluster'])
    
    candidate_summary = candidate_progress.get_summary()
    candidate_progress.close()  # Close progress bar
    logger.info(f"\nPhase 2 complete:")
    logger.info(f"  Candidate pairs processed: {candidate_summary['processed']:,}/{candidate_summary['total']:,}")
    logger.info(f"  Employer pairs processed: {processed_pairs:,}")
    logger.info(f"  Time: {candidate_summary['elapsed_seconds']:.1f}s")
    logger.info(f"  Rate: {candidate_summary['rate_per_second']:.0f} candidate pairs/sec")
    
    return auto_clustered


def _update_cluster_statistics(batch_size: int, dry_run: bool):
    """Update cluster statistics (optimized with prefetch)"""
    if dry_run:
        return
    
    logger.info("\n" + "="*60)
    logger.info("Updating cluster statistics...")
    logger.info("="*60)
    
    # Count total clusters first
    total_clusters = EmployerCluster.objects.count()
    logger.info(f"Total clusters to update: {total_clusters:,}")
    
    logger.info("Loading clusters with employers (prefetch)...")
    start_time = time.time()
    clusters = list(EmployerCluster.objects.prefetch_related('employers').all())
    logger.info(f"Loaded {len(clusters):,} clusters in {time.time() - start_time:.1f}s")
    
    logger.info("Calculating statistics for each cluster...")
    start_time = time.time()
    clusters_to_update = []
    
    for i, cluster in enumerate(clusters):
        employers_list = list(cluster.employers.all())
        cluster.total_lca_count = sum(e.total_lca_count for e in employers_list)
        cluster.total_perm_count = sum(e.total_perm_count for e in employers_list)
        
        salaries = [float(e.avg_salary) for e in employers_list if e.avg_salary]
        if salaries:
            cluster.avg_salary = sum(salaries) / len(salaries)
        else:
            cluster.avg_salary = None
        
        clusters_to_update.append(cluster)
        
        # Progress logging every 10,000 clusters
        if (i + 1) % 10000 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total_clusters - i - 1) / rate if rate > 0 else 0
            logger.info(f"  Processed {i + 1:,}/{total_clusters:,} clusters "
                       f"({(i + 1) / total_clusters * 100:.1f}%) - "
                       f"Rate: {rate:.0f}/s - ETA: {eta:.0f}s")
    
    logger.info(f"Calculated stats for {len(clusters_to_update):,} clusters in {time.time() - start_time:.1f}s")
    
    if clusters_to_update:
        logger.info("Bulk updating cluster statistics...")
        start_time = time.time()
        bulk_update_batched(
            clusters_to_update,
            batch_size=batch_size,
            fields=['total_lca_count', 'total_perm_count', 'avg_salary']
        )
        logger.info(f"Bulk update completed in {time.time() - start_time:.1f}s")
    
    logger.info(f"Updated statistics for {len(clusters_to_update):,} clusters")


def cluster_existing_employers(
    auto_approve_threshold: float = 0.95,
    batch_size: int = 1000,
    dry_run: bool = False,
    pairs_output_file: Optional[str] = None,
    min_pairs_needed: Optional[int] = None,
    shuffle_employers: bool = False,
    shuffle_seed: Optional[int] = None,
    checkpoint_file: Optional[str] = None,
    employer_limit: Optional[int] = None
):
    """
    Cluster all existing employers
    
    1. Load all employers (or a limit)
    2. Compare pairs using rule-based + fuzzy matching
    3. Auto-cluster high-confidence matches
    4. Add ambiguous cases to review queue
    5. Update canonical_cluster FK on Employer records
    """
    start_time = time.time()
    logger.info("="*60)
    logger.info("Starting employer clustering...")
    logger.info(f"Auto-approve threshold: {auto_approve_threshold}")
    logger.info(f"Batch size: {batch_size}")
    logger.info(f"Dry run: {dry_run}")
    if employer_limit:
        logger.info(f"Employer limit: {employer_limit:,}")
    if checkpoint_file:
        logger.info(f"Checkpoint file: {checkpoint_file}")
        checkpoint = load_checkpoint()
        if checkpoint:
            phase1_count = len(checkpoint.get('phase1_processed', set()))
            phase2_count = len(checkpoint.get('phase2_processed', set()))
            logger.info(f"  Resuming from checkpoint (Phase 1: {phase1_count:,} names, "
                       f"Phase 2: {phase2_count:,} pairs)")
        else:
            logger.info("  No existing checkpoint found - starting fresh")
    logger.info("="*60)
    
    # Open pairs output file if requested
    global _process_employer_pair_output_file, _process_employer_pair_min_pairs, _process_employer_pair_pairs_collected
    pairs_file = None
    if pairs_output_file:
        pairs_file = open(pairs_output_file, 'w')
        _process_employer_pair_output_file = pairs_file
        logger.info(f"Writing pairs to: {pairs_output_file}")
    
    # Set up early stopping if requested
    if min_pairs_needed is not None:
        _process_employer_pair_min_pairs = min_pairs_needed
        _process_employer_pair_pairs_collected = {'auto': 0, 'queued': 0}
        logger.info(f"Early stopping enabled: Will stop when {min_pairs_needed:,} pairs collected")
    else:
        _process_employer_pair_min_pairs = None
        _process_employer_pair_pairs_collected = {'auto': 0, 'queued': 0}
    
    try:
        # Load and group employers (with optional shuffling and limit)
        all_employers, employers_by_normalized = _load_and_group_employers(
            shuffle=shuffle_employers,
            seed=shuffle_seed,
            limit=employer_limit
        )
        if not all_employers:
            logger.info("No employers to cluster")
            return
        
        total = len(all_employers)
        
        # Phase 1: Process same normalized names
        phase1_auto, clusters_created = _process_same_normalized_name_matches(
            employers_by_normalized, auto_approve_threshold, batch_size, dry_run,
            checkpoint_file=checkpoint_file
        )
        
        # Phase 2: Process cross-normalized matches
        # PERFORMANCE NOTE: This is the main bottleneck for full runs (O(K * P)).
        # K = candidate pairs (approx 400k for full dataset), P = processing cost.
        # Processing rate is ~200 pairs/sec due to:
        # 1. Re-normalization in match_employers (redundant, could be optimized by passing normalized names)
        # 2. CPU-bound string comparison logic (difflib, regex)
        # 
        # For debugging/development, use --limit-employers to reduce N (and thus K).
        normalized_names = list(employers_by_normalized.keys())
        phase2_auto = _process_cross_normalized_name_matches(
            normalized_names, employers_by_normalized,
            auto_approve_threshold, batch_size, dry_run,
            checkpoint_file=checkpoint_file
        )
        
        # Clear checkpoint on successful completion
        if checkpoint_file:
            clear_checkpoint()
            logger.info(f"Checkpoint cleared after successful completion")
    finally:
        if pairs_file:
            pairs_file.close()
            _process_employer_pair_output_file = None
        _process_employer_pair_min_pairs = None
        _process_employer_pair_pairs_collected = {'auto': 0}
    
    # Update cluster statistics
    _update_cluster_statistics(batch_size, dry_run)
    
    # Final summary
    total_auto = phase1_auto + phase2_auto
    total_elapsed = time.time() - start_time
    
    logger.info("\n" + "="*60)
    logger.info("CLUSTERING SUMMARY")
    logger.info("="*60)
    logger.info(f"  Total employers: {total:,}")
    logger.info(f"  Auto-clustered pairs: {total_auto:,}")
    logger.info(f"  Clusters created: {clusters_created:,}")
    logger.info(f"  Total time: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    logger.info("="*60)
    
    if dry_run:
        logger.info("\nDRY RUN - No changes made to database")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Cluster existing employers')
    parser.add_argument('--threshold', type=float, default=0.95,
                       help='Auto-approve threshold (default: 0.95)')
    parser.add_argument('--batch-size', type=int, default=1000,
                       help='Batch size for processing (default: 1000)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run - show what would be done without making changes')
    parser.add_argument('--pairs-output', help='Output file for pairs (JSONL format)')
    parser.add_argument('--min-pairs', type=int, help='Stop early when this many pairs collected (for fast testing)')
    parser.add_argument('--shuffle', action='store_true', help='Shuffle employers before processing (for random sampling)')
    parser.add_argument('--shuffle-seed', type=int, help='Random seed for shuffling (for reproducibility)')
    parser.add_argument('--checkpoint-file', type=str, default=CHECKPOINT_FILE,
                       help=f'Checkpoint file path for resuming (default: {CHECKPOINT_FILE})')
    parser.add_argument('--resume', action='store_true',
                       help='Resume from checkpoint if available (uses --checkpoint-file)')
    parser.add_argument('--clear-checkpoint', action='store_true',
                       help='Clear checkpoint file before starting (start fresh)')
    parser.add_argument('--reset-clustering', action='store_true',
                       help='Reset all clustering state before starting (removes all clusters and assignments)')
    parser.add_argument('--limit-employers', type=int, help='Limit number of employers to process (for fast debugging)')
    parser.add_argument('--stats-only', action='store_true',
                       help='Only update cluster statistics (skip clustering)')
    
    args = parser.parse_args()
    
    # Handle clustering reset if requested
    if args.reset_clustering:
        logger.info("Resetting clustering state...")
        from models.salary import Employer, EmployerCluster
        from django.db import transaction
        
        with transaction.atomic():
            # Reset employer cluster assignments
            updated_count = Employer.objects.exclude(canonical_cluster__isnull=True).update(canonical_cluster=None)
            logger.info(f"  Reset {updated_count:,} employer cluster assignments")
            
            # Delete all clusters
            deleted_count, _ = EmployerCluster.objects.all().delete()
            logger.info(f"  Deleted {deleted_count:,} clusters")
            
            # Note: Reviews table is deprecated/unused now
        
        logger.info("Clustering state reset complete. Starting fresh clustering...")
    
    # Handle checkpoint clearing
    if args.clear_checkpoint:
        clear_checkpoint()
        logger.info("Checkpoint cleared - starting fresh")
    
    # Determine checkpoint file usage
    checkpoint_file = args.checkpoint_file if args.resume or args.checkpoint_file != CHECKPOINT_FILE else None
    if args.resume and not checkpoint_file:
        checkpoint_file = CHECKPOINT_FILE
    
    script_logger.log_call(
        args=vars(args),
        context='Cluster existing employers'
    )
    
    # Stats-only mode: just update cluster statistics without clustering
    if args.stats_only:
        logger.info("Running in stats-only mode - updating cluster statistics...")
        _update_cluster_statistics(batch_size=args.batch_size, dry_run=args.dry_run)
        logger.info("Stats update complete!")
        return
    
    cluster_existing_employers(
        auto_approve_threshold=args.threshold,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        pairs_output_file=args.pairs_output,
        min_pairs_needed=args.min_pairs,
        shuffle_employers=args.shuffle,
        shuffle_seed=args.shuffle_seed,
        checkpoint_file=checkpoint_file,
        employer_limit=args.limit_employers
    )


if __name__ == '__main__':
    main()








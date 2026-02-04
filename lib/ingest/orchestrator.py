"""Pipeline orchestrator - coordinates stages with resumption support"""

import logging
import time
import traceback
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Optional
from django.db import transaction, connection, models
from django.core.exceptions import FieldDoesNotExist
from django.utils import timezone

from models.ingest.enums import IngestStatus, IngestStage, SourceType
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.ingest.ingest_version import IngestVersion
from models.salary import SalaryRecord
from models.visa_cutoff_date import VisaCutoffDate
from lib.utils.rate_limited_logger import RateLimitedLogger
from lib.utils.data_source_utils import get_data_source_filepath, count_file_rows, get_source_file_date
from lib.utils.exception_utils import handle_unrecoverable_errors
from .base import DataSourcePlugin, ValidationResult
from .registry import PluginRegistry
from .rejection_tracker import RejectionTracker
from .schema import ModelCopySchema
from .versioning import create_version, activate_version

logger = logging.getLogger(__name__)

# When upserting, don't overwrite existing non-null date with null (same case in two files with different completeness)
MERGE_PRESERVE_FIELDS = frozenset({'case_submitted', 'decision_date'})


def get_optimal_batch_size(model_class, current_count: int) -> int:
    """Calculate optimal batch size based on database size"""
    if current_count < 100_000:
        return 5_000  # Small DB: larger batches (less transaction overhead)
    elif current_count < 1_000_000:
        return 2_000  # Medium DB: medium batches
    else:
        return 1_000  # Large DB: smaller batches (current default)


def _identify_new_and_existing(
    records: list,
    batch_size: int = 10000
) -> tuple[list, dict]:
    """
    Identify new and existing records using efficient batch queries.
    
    Args:
        records: List of model instances to check
        batch_size: Batch size for IN clause queries
        
    Returns:
        Tuple of (new_records: list, existing_records: dict[case_number, SalaryRecord])
        existing_records dict contains records with their source_file_date for comparison
    """
    if not records:
        return [], {}
    
    # Get model class from first record
    model_class = type(records[0])
    
    # Extract case numbers (assuming case_number field exists)
    if not hasattr(records[0], 'case_number'):
        # No case_number field, can't identify existing (e.g., VisaCutoffDate)
        return records, {}
    
    case_numbers = [r.case_number for r in records]
    
    # Query in batches to avoid huge IN clauses
    # Fetch existing records with source_file_date for comparison when available
    existing_records_dict = {}
    try:
        model_class._meta.get_field('source_file_date')
        only_fields = ['case_number', 'source_file_date']
    except Exception:
        only_fields = ['case_number']
    for i in range(0, len(case_numbers), batch_size):
        batch_cases = case_numbers[i:i+batch_size]
        existing = model_class.objects.filter(
            case_number__in=batch_cases
        ).only(*only_fields)
        
        for existing_record in existing:
            existing_records_dict[existing_record.case_number] = existing_record
    
    # Separate new and existing records
    new_records = [r for r in records if r.case_number not in existing_records_dict]
    
    return new_records, existing_records_dict


class PipelineOrchestrator:
    """Coordinates pipeline stages with resumption support"""
    
    def __init__(
        self,
        batch_size: int = 1000,
        adaptive_batch: bool = True,
        use_copy: bool = False,
        prefilter_existing: bool = True,
        update_mode: bool = False,
        update_fields: list[str] | None = None,
        update_filter: dict | None = None
    ):
        """
        Args:
            batch_size: Initial batch size (will adapt if adaptive_batch=True)
            adaptive_batch: Automatically adjust batch size based on DB state
            use_copy: Use PostgreSQL COPY instead of bulk_create (faster, PostgreSQL-only)
            prefilter_existing: Pre-filter existing cases before insert (faster)
            update_mode: If True, update existing records instead of creating new ones
            update_fields: List of field names to update (required if update_mode=True)
            update_filter: Dict of filters to apply when finding existing records to update
                          (e.g., {'wage_annual__isnull': True} to only update records with missing salary)
        """
        self.adaptive_batch = adaptive_batch
        self.use_copy = use_copy
        self.prefilter_existing = prefilter_existing
        self.update_mode = update_mode
        self.update_fields = update_fields
        self.update_filter = update_filter or {}
        self.initial_batch_size = batch_size
        self.batch_size = batch_size
        if self.use_copy:
            self.batch_size = max(self.batch_size, 10000)
            self.initial_batch_size = self.batch_size
        # Track stage timings for performance analysis
        self.stage_timings = {}
        # Track pipeline-wide stats for ETA
        self.pipeline_start_time = None
        self.pending_sources_count = 0
        self.completed_sources_count = 0
        # Rate-limited logger for prefilter logging
        self._prefilter_rate_logger = RateLimitedLogger(
            initial_count=5,
            min_interval_seconds=5.0,
            logger=logger,
            log_level=logging.INFO
        )
        self._copy_preflight_done = False
        
        # Validate update_mode configuration
        if self.update_mode:
            if not self.update_fields:
                raise ValueError("update_fields must be specified when update_mode=True")
    
    def run(self, source: DataSource, resume: bool = True, pipeline_context: dict | None = None) -> IngestRun:
        """
        Execute full pipeline, resuming from checkpoint if interrupted.
        
        Args:
            source: DataSource to ingest
            resume: Whether to resume from checkpoint if run exists
            pipeline_context: Optional dict with pipeline-wide stats for ETA calculation
                {'pending_count': int, 'completed_count': int, 'start_time': float}
            
        Returns:
            IngestRun instance
        """
        run = self._get_or_create_run(source, resume)
        plugin = PluginRegistry.get_plugin(source.domain, source.source_type)
        
        if not plugin:
            raise ValueError(f"No plugin found for {source.domain}:{source.source_type}")
        
        # Initialize rejection tracker for this run
        rejection_tracker = RejectionTracker(run)
        
        # Set rejection tracker on plugin (plugins can optionally use it)
        if hasattr(plugin, 'set_rejection_tracker'):
            plugin.set_rejection_tracker(rejection_tracker)
        
        # Initialize pipeline context if provided
        if pipeline_context:
            self.pending_sources_count = pipeline_context.get('pending_count', 0)
            self.completed_sources_count = pipeline_context.get('completed_count', 0)
            self.pipeline_start_time = pipeline_context.get('start_time', time.time())
            self._skip_records = pipeline_context.get('skip_records', 0)
        else:
            self._skip_records = 0
        
        # Reset stage timings for this run
        self.stage_timings = {}
        run_start_time = time.time()
        
        logger.info(f"[Run {run.id}] Starting pipeline for source: {source.url}")
        logger.info(f"[Run {run.id}] Current stage: {run.stage}, status: {run.status}")
        
        total_expected_records = None
        # Estimate total records if possible (for ETA)
        logger.info(f"[Run {run.id}] Estimating total records in file...")
        filepath = get_data_source_filepath(source)
        if filepath:
            logger.info(f"[Run {run.id}] Estimating row count from {filepath.suffix.upper()} file...")
            total_expected_records = count_file_rows(filepath, logger_instance=logger)
            if total_expected_records is not None:
                logger.info(f"[Run {run.id}] Estimated {total_expected_records:,} data rows")
                # Store in checkpoint for ETA calculation during load stage
                run.checkpoint['total_expected_records'] = total_expected_records
                run.save(update_fields=['checkpoint'])
            else:
                logger.info(f"[Run {run.id}] Could not estimate total records (will proceed without ETA)")
        else:
            logger.info(f"[Run {run.id}] Could not estimate total records (will proceed without ETA)")
        
        try:
            # Use select_for_update to prevent concurrent execution
            # Refresh run with lock to ensure we have latest state
            with transaction.atomic():
                run = IngestRun.objects.select_for_update().get(id=run.id)
                # Check if another process already started it
                if run.status == IngestStatus.RUNNING:
                    raise RuntimeError(f"Run {run.id} is already running in another process")
                run.status = IngestStatus.RUNNING
                run.save()
            
            # Stage 1: Download
            if run.stage in [IngestStage.PENDING, IngestStage.DOWNLOADING]:
                filepath = self._download_stage(plugin, source, run)
            else:
                # Resume: get filepath from checkpoint
                filepath = Path(run.checkpoint.get('filepath', ''))
                if not filepath or not filepath.exists():
                    raise FileNotFoundError(f"Checkpoint filepath not found: {filepath}")
            
            # Stage 2: Parse
            if run.stage in [IngestStage.DOWNLOADING, IngestStage.PARSING]:
                records = self._parse_stage(plugin, filepath, run)
            else:
                # Resume: need to re-parse from checkpoint
                records = self._parse_stage(plugin, filepath, run)
            
            # Stage 3: Transform
            if run.stage in [IngestStage.PARSING, IngestStage.TRANSFORMING]:
                models = self._transform_stage(plugin, records, run)
            else:
                # Resume: need to re-transform from checkpoint
                models = self._transform_stage(plugin, records, run)
            
            # Stage 4: Load to Database
            if run.stage in [IngestStage.TRANSFORMING, IngestStage.LOADING]:
                self._load_to_db_stage(models, run)
            
            # Stage 5: Post-Ingest Validation
            validation_result = self._validate_post_ingest(plugin, run)
            
            # Abort if validation found critical errors
            if not validation_result.passed:
                error_msg = f"Validation failed with {len(validation_result.errors)} error(s): " + "; ".join(validation_result.errors[:3])
                if len(validation_result.errors) > 3:
                    error_msg += f" ... and {len(validation_result.errors) - 3} more"
                raise ValueError(error_msg)
            
            # Log warnings if any
            if validation_result.warnings:
                for warning in validation_result.warnings:
                    logger.warning(f"[Run {run.id}] Validation warning: {warning}")
            
            # Versioning: Only create versions for insert mode (updates modify existing records)
            if not self.update_mode:
                # Create and activate version for rollback support
                version_tag = self._generate_version_tag(run)
                version = create_version(run, version_tag)
                
                # Link records to version (update all records created in this run)
                self._link_records_to_version(run, version)
                
                # Activate version (makes records visible to serving queries)
                activate_version(version)
            else:
                logger.info(f"[Run {run.id}] Update mode: Skipping versioning (updates modify existing records)")
            
            # Save rejection statistics to database
            rejection_tracker.save_to_db()
            
            run.mark_completed()
            
            # Log performance summary
            total_duration = time.time() - run_start_time
            self._log_performance_summary(run, total_duration, total_expected_records)
            
            if not self.update_mode:
                logger.info(f"[Run {run.id}] Pipeline completed successfully (version: {version_tag})")
            else:
                logger.info(f"[Run {run.id}] Pipeline completed successfully (update mode)")
            
            # Update pipeline context if provided
            if pipeline_context:
                self.completed_sources_count += 1
                self._log_pipeline_eta()
        except Exception as e:
            run.mark_failed(e)
            logger.error(f"[Run {run.id}] Pipeline failed at stage {run.stage}: {e}")
            raise
        finally:
            run.save()
        
        return run
    
    def _get_or_create_run(self, source: DataSource, resume: bool) -> IngestRun:
        """
        Get existing run or create new one with concurrency protection.
        
        Uses SELECT FOR UPDATE to prevent concurrent runs from picking the same run.
        """
        if resume:
            # Try to find existing incomplete run with row-level lock
            # This prevents concurrent processes from picking the same run
            with transaction.atomic():
                existing = IngestRun.objects.select_for_update().filter(
                    source=source,
                    status__in=[IngestStatus.PENDING, IngestStatus.RUNNING]
                ).order_by('-started_at').first()
                
                if existing:
                    # Check if another process already started it
                    existing.refresh_from_db()
                    if existing.status == IngestStatus.RUNNING:
                        # Another process is running, create new run instead
                        logger.warning(f"[Run {existing.id}] Another process is running, creating new run")
                    else:
                        logger.info(f"[Run {existing.id}] Resuming existing run from stage: {existing.stage}")
                        return existing
        
        # Create new run
        run = IngestRun.objects.create(
            source=source,
            status=IngestStatus.PENDING,
            stage=IngestStage.PENDING
        )
        logger.info(f"[Run {run.id}] Created new ingest run")
        return run
    
    def _download_stage(self, plugin: DataSourcePlugin, source: DataSource, run: IngestRun) -> Path:
        """Download stage with resume support"""
        stage_start = time.time()
        run.stage = IngestStage.DOWNLOADING
        run.checkpoint['stage'] = IngestStage.DOWNLOADING.value
        run.save()
        logger.info(f"[Run {run.id}] Stage: DOWNLOADING")
        
        filepath = plugin.download(source, run)
        
        # Extract and store source file date for duplicate resolution
        source_file_date = get_source_file_date(filepath, source)
        if source_file_date:
            # Convert to timezone-aware datetime if needed
            if timezone.is_naive(source_file_date):
                source_file_date = timezone.make_aware(source_file_date)
            run.checkpoint['source_file_date'] = source_file_date.isoformat()
            logger.debug(f"[Run {run.id}] Extracted source file date: {source_file_date}")
        else:
            logger.warning(f"[Run {run.id}] Could not extract source file date from {filepath}")
        
        # Store filepath in checkpoint for later stages
        run.checkpoint['filepath'] = str(filepath)
        run.checkpoint['stage'] = IngestStage.PARSING.value
        run.stage = IngestStage.PARSING
        source.downloaded_at = timezone.now()
        source.local_file_path = str(filepath)
        source.save()
        run.save()
        
        stage_duration = time.time() - stage_start
        self.stage_timings['download'] = stage_duration
        logger.info(f"[Run {run.id}] Download completed in {stage_duration:.2f}s: {filepath}")
        return filepath
    
    def _parse_stage(self, plugin: DataSourcePlugin, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Parse stage with checkpoint resumption"""
        stage_start = time.time()
        run.stage = IngestStage.PARSING
        run.save()
        logger.info(f"[Run {run.id}] Stage: PARSING")
        
        # Resume from checkpoint if present
        checkpoint = run.checkpoint.get('last_row', 0)
        if checkpoint > 0:
            logger.info(f"[Run {run.id}] Resuming from row {checkpoint:,}")
        
        records = plugin.parse(filepath, run)
        
        # Skip to checkpoint if resuming
        if checkpoint > 0:
            for _ in range(checkpoint):
                try:
                    next(records)
                except StopIteration:
                    break
        
        run.stage = IngestStage.TRANSFORMING
        run.checkpoint['stage'] = IngestStage.TRANSFORMING.value  # Store integer in JSON
        run.save()
        
        stage_duration = time.time() - stage_start
        self.stage_timings['parse'] = stage_duration
        logger.info(f"[Run {run.id}] Parse stage ready (duration: {stage_duration:.2f}s)")
        return records
    
    def _transform_stage(self, plugin: DataSourcePlugin, records: Iterator[dict], run: IngestRun) -> Iterator:
        """Transform stage with progress tracking"""
        stage_start = time.time()
        run.stage = IngestStage.TRANSFORMING
        run.checkpoint['stage'] = IngestStage.TRANSFORMING.value
        run.save()
        logger.info(f"[Run {run.id}] Stage: TRANSFORMING")
        
        # Check if we should skip records (for debugging)
        skip_records = getattr(self, '_skip_records', 0)
        if skip_records > 0:
            logger.warning(f"[Run {run.id}] DEBUG MODE: Skipping first {skip_records:,} records")
        
        transform_error_count = 0
        records_processed_count = 0
        transform_rate_logger = RateLimitedLogger(
            initial_count=5,
            min_interval_seconds=5.0,
            logger=logger,
            log_level=logging.INFO
        )
        
        for record_num, record in enumerate(records, start=1):
            # Skip records if in debug mode
            if skip_records > 0 and record_num <= skip_records:
                continue
            # Log progress: every 1000 records, with rate limiting
            if record_num % 1000 == 0:
                transform_rate_logger.log(f"[Run {run.id}] Transforming record {record_num:,}...")
            
            def handle_recoverable_error(e: Exception) -> None:
                """Handle recoverable transform errors with rate-limited logging"""
                nonlocal transform_error_count
                transform_error_count += 1
                if transform_error_count <= 5:  # Log first 5 errors in detail
                    logger.error(f"[Run {run.id}] Transform failed for record {record_num}: {e}", exc_info=True)
                elif transform_error_count == 6:
                    logger.error(f"[Run {run.id}] Transform errors continuing, suppressing detailed logs...")
            
            @handle_unrecoverable_errors(
                log_message=f"[Run {run.id}] Unrecoverable error transforming record {record_num}",
                logger_instance=logger,
                on_recoverable=handle_recoverable_error,
                suppress_recoverable=True
            )
            def _transform_record() -> object | None:
                """Transform record - extracted for decorator usage"""
                return plugin.transform(record)
            
            model = _transform_record()
            if model:
                yield model
                run.records_processed += 1
                records_processed_count += 1
                if records_processed_count % 10000 == 0:
                    logger.debug(f"[Run {run.id}] Transformed {records_processed_count:,} records")
                    run.save(update_fields=['records_processed'])
        
        # Report transform stage completion with error count
        if transform_error_count > 0:
            logger.warning(
                f"[Run {run.id}] Transform stage completed: {records_processed_count:,} models yielded from {record_num:,} records "
                f"({transform_error_count:,} errors encountered)"
            )
        else:
            logger.info(f"[Run {run.id}] Transform stage completed: {records_processed_count:,} models yielded from {record_num:,} records")
        
        run.stage = IngestStage.LOADING
        run.checkpoint['stage'] = IngestStage.LOADING.value
        run.save()
        
        stage_duration = time.time() - stage_start
        if transform_error_count > 0:
            logger.warning(
                f"[Run {run.id}] Transform completed: {run.records_processed:,} records in {stage_duration:.2f}s "
                f"({transform_error_count:,} transform errors)"
            )
        else:
            logger.info(f"[Run {run.id}] Transform completed: {run.records_processed:,} records in {stage_duration:.2f}s")
    
    def _load_to_db_stage(self, models: Iterator, run: IngestRun):
        """Batched streaming insert/update to database with checkpoint updates"""
        stage_start = time.time()
        run.stage = IngestStage.LOADING
        run.checkpoint['stage'] = IngestStage.LOADING.value
        run.save()
        
        if self.update_mode:
            logger.info(f"[Run {run.id}] Stage: UPDATING DATABASE (update_mode=True, fields={self.update_fields})")
        else:
            logger.info(f"[Run {run.id}] Stage: LOADING TO DATABASE")
        
        # Adjust batch size based on current DB size if adaptive
        if self.adaptive_batch:
            # Get model class from first item (peek)
            try:
                first_model = next(models)
                model_class = type(first_model)
                # Put it back by creating new iterator
                models = self._prepend_iterator(first_model, models)
                
                logger.info(f"[Run {run.id}] Counting existing {model_class.__name__} records to determine batch size...")
                count_start = time.time()
                current_count = model_class.objects.count()
                count_duration = time.time() - count_start
                logger.info(f"[Run {run.id}] Found {current_count:,} existing {model_class.__name__} records (count took {count_duration:.2f}s)")
                
                self.batch_size = get_optimal_batch_size(model_class, current_count)
                if self.use_copy:
                    self.batch_size = max(self.batch_size, 10000)
                logger.info(f"[Run {run.id}] Adaptive batch size: {self.batch_size} (based on {model_class.__name__})")
            except StopIteration:
                logger.warning(f"[Run {run.id}] No models to load")
                return
        
        batch = []
        recent_batch_times = []
        last_logged_count = 0
        load_rate_logger = RateLimitedLogger(
            initial_count=5,
            min_interval_seconds=5.0,
            logger=logger,
            log_level=logging.INFO
        )
        
        logger.info(f"[Run {run.id}] Starting to process models from iterator...")
        
        for i, model in enumerate(models):
            # Log progress: every 100 records for first 5 times, then at most once per 5 seconds OR every 1000 records
            # This ensures we see progress even if processing is slow
            should_log = False
            current_count = i + 1
            
            # First 5 logs: every 100 records
            if load_rate_logger.log_count < 5:
                if current_count % 100 == 0 and current_count - last_logged_count >= 100:
                    should_log = True
            else:
                # After first 5: log at most once per 5 seconds (time-based) OR every 1000 records (count-based)
                if current_count - last_logged_count >= 1000:
                    should_log = True
            
            if should_log and load_rate_logger.should_log():
                load_rate_logger.log(f"[Run {run.id}] Processed {current_count:,} models from iterator...")
                last_logged_count = current_count
            
            batch.append(model)
            
            if len(batch) >= self.batch_size:
                batch_start = time.time()
                self._insert_batch_to_db(batch, run)
                batch_time = time.time() - batch_start
                
                # Adaptive adjustment: if batches getting slow, reduce size
                recent_batch_times.append(batch_time)
                if len(recent_batch_times) > 10:
                    recent_batch_times = recent_batch_times[-10:]  # Keep last 10
                    avg_time = sum(recent_batch_times) / len(recent_batch_times)
                    if avg_time > 1.0 and self.adaptive_batch:  # Slower than 1 second
                        old_batch_size = self.batch_size
                        self.batch_size = max(500, self.batch_size - 100)
                        # Only log if batch size actually changed
                        if self.batch_size != old_batch_size:
                            logger.info(f"[Run {run.id}] Reduced batch size to {self.batch_size} (avg: {avg_time:.2f}s)")
                
                run.checkpoint = {
                    'stage': IngestStage.LOADING.value,  # Store integer value in JSON
                    'last_row': i,
                    'batch': i // self.batch_size,
                    'filepath': run.checkpoint.get('filepath'),
                    'batch_size': self.batch_size,
                    'total_expected_records': run.checkpoint.get('total_expected_records')  # Preserve for ETA
                }
                run.records_processed = i + 1
                run.save(update_fields=['checkpoint', 'records_processed'])
                
                # Log progress: more frequently at start, then every 10k records
                # First 5 batches: log every batch (for immediate feedback)
                # After that: log every 10 batches (every 10k records with batch_size=1000)
                if (i + 1) <= (self.batch_size * 5) or (i + 1) % (self.batch_size * 10) == 0:
                    rate = (i + 1) / (time.time() - stage_start)
                    # Calculate ETA for current file
                    total_expected = run.checkpoint.get('total_expected_records')
                    eta_msg = ""
                    if total_expected and total_expected > i + 1:
                        remaining = total_expected - (i + 1)
                        eta_seconds = remaining / rate if rate > 0 else 0
                        eta_minutes = eta_seconds / 60
                        eta_msg = f", ETA: {eta_minutes:.1f} min"
                    
                    # Log appropriate message based on mode
                    if self.update_mode:
                        logger.info(f"[Run {run.id}] Processed {i + 1:,} records, updated {run.records_updated:,} ({rate:,.0f} rec/sec{eta_msg})")
                    else:
                        logger.info(f"[Run {run.id}] Loaded {i + 1:,} records ({rate:,.0f} rec/sec{eta_msg})")
                
                batch = []
        
        # Insert remaining records
        if batch:
            self._insert_batch_to_db(batch, run)
        
        stage_duration = time.time() - stage_start
        self.stage_timings['load'] = stage_duration
        
        # Log appropriate message based on mode
        if self.update_mode:
            logger.info(f"[Run {run.id}] Database update completed: {run.records_updated:,} records updated, {run.records_skipped:,} skipped in {stage_duration:.2f}s")
        else:
            logger.info(f"[Run {run.id}] Database load completed: {run.records_created:,} records in {stage_duration:.2f}s")
    
    def _prepend_iterator(self, first_item, rest_iterator):
        """Helper to prepend an item to an iterator"""
        yield first_item
        yield from rest_iterator
    
    def _log_performance_summary(self, run: IngestRun, total_duration: float, total_expected: int | None):
        """Log performance summary with stage breakdown and bottleneck analysis"""
        if not self.stage_timings:
            return
        
        total_stage_time = sum(self.stage_timings.values())
        
        logger.info(f"[Run {run.id}] Performance Summary:")
        logger.info(f"[Run {run.id}]   Total duration: {total_duration:.2f}s ({total_duration/60:.1f} min)")
        
        # Stage breakdown
        for stage_name, duration in self.stage_timings.items():
            percentage = (duration / total_duration * 100) if total_duration > 0 else 0
            logger.info(f"[Run {run.id}]   {stage_name.capitalize()}: {duration:.2f}s ({percentage:.1f}%)")
        
        # Identify bottleneck
        if self.stage_timings:
            bottleneck_stage = max(self.stage_timings.items(), key=lambda x: x[1])[0]
            bottleneck_time = self.stage_timings[bottleneck_stage]
            bottleneck_pct = (bottleneck_time / total_duration * 100) if total_duration > 0 else 0
            logger.info(f"[Run {run.id}]   Bottleneck: {bottleneck_stage} stage ({bottleneck_pct:.1f}% of total)")
        
        # Throughput and record counts
        if self.update_mode:
            if run.records_updated > 0 and total_duration > 0:
                throughput = run.records_updated / total_duration
                logger.info(f"[Run {run.id}]   Throughput: {throughput:,.0f} rec/sec")
            logger.info(f"[Run {run.id}]   Records: {run.records_updated:,} updated, {run.records_skipped:,} skipped, {run.records_failed:,} failed")
        else:
            if run.records_created > 0 and total_duration > 0:
                throughput = run.records_created / total_duration
                logger.info(f"[Run {run.id}]   Throughput: {throughput:,.0f} rec/sec")
            
            # Accuracy check if we had an estimate
            if total_expected and run.records_created > 0:
                accuracy = (run.records_created / total_expected * 100) if total_expected > 0 else 0
                logger.info(f"[Run {run.id}]   Records: {run.records_created:,} created (estimated: {total_expected:,}, {accuracy:.1f}%)")
    
    def _log_pipeline_eta(self):
        """Log pipeline-wide ETA for all pending sources"""
        if not self.pipeline_start_time or self.pending_sources_count == 0:
            return
        
        elapsed_time = time.time() - self.pipeline_start_time
        if self.completed_sources_count == 0:
            return
        
        # Calculate average time per source
        avg_time_per_source = elapsed_time / self.completed_sources_count
        remaining_sources = self.pending_sources_count - self.completed_sources_count
        
        if remaining_sources > 0:
            estimated_remaining = avg_time_per_source * remaining_sources
            estimated_total = elapsed_time + estimated_remaining
            logger.info(f"Pipeline Progress: {self.completed_sources_count}/{self.pending_sources_count} sources completed")
            logger.info(f"Pipeline ETA: {estimated_remaining/60:.1f} min remaining ({estimated_total/60:.1f} min total)")
    
    def _deduplicate_batch(self, batch: list) -> list:
        """
        Remove duplicate records within a batch based on case_number.
        
        bulk_create with ignore_conflicts=True only ignores conflicts with existing
        DB records, NOT conflicts within the same batch. If a batch contains
        duplicate case_numbers, bulk_create will fail.
        
        Args:
            batch: List of model instances
            
        Returns:
            Deduplicated list (keeps first occurrence of each case_number)
        """
        if not batch:
            return batch
        
        # Check if model has case_number field
        if not hasattr(batch[0], 'case_number'):
            # No case_number field, can't deduplicate (e.g., VisaCutoffDate)
            return batch
        
        # Use dict to keep first occurrence of each case_number
        seen = {}
        deduplicated = []
        skipped_count = 0
        duplicate_cases = []  # Track which case_numbers are duplicated
        
        for record in batch:
            case_number = record.case_number
            if case_number not in seen:
                seen[case_number] = True
                deduplicated.append(record)
            else:
                skipped_count += 1
                if case_number not in duplicate_cases:
                    duplicate_cases.append(case_number)
        
        if skipped_count > 0:
            # Show sample of duplicate case_numbers (limit to 5 for log readability)
            sample_cases = duplicate_cases[:5]
            cases_str = ', '.join(sample_cases)
            if len(duplicate_cases) > 5:
                cases_str += f" ... and {len(duplicate_cases) - 5} more"
            logger.warning(
                f"Deduplicated {skipped_count} duplicate case_numbers within batch. "
                f"Sample duplicates: {cases_str}"
            )
        
        return deduplicated
    
    def _insert_batch_to_db(self, batch: list, run: IngestRun):
        """Insert or update batch to database with error handling and optimizations"""
        if not batch:
            return
        
        if self.update_mode:
            self._update_batch_to_db(batch, run)
        else:
            self._upsert_batch_to_db(batch, run)
    
    def _insert_batch_to_db_only(self, batch: list, run: IngestRun):
        """Insert batch to database with error handling and optimizations"""
        if not batch:
            return
        
        try:
            # Split batch by model type first (handles mixed batches from plugins that create multiple model types)
            from collections import defaultdict
            batches_by_type = defaultdict(list)
            for record in batch:
                batches_by_type[type(record)].append(record)
            
            # Pre-filter existing cases if enabled (must be done per model type)
            if self.prefilter_existing:
                source_file = run.checkpoint.get('filepath', '')
                if source_file:
                    prefilter_start = time.time()
                    filtered_batches = {}
                    type_stats = {}  # Track stats per model type
                    for model_class, type_batch in batches_by_type.items():
                        before_count = len(type_batch)
                        filtered = _prefilter_existing_cases(type_batch, source_file)
                        after_count = len(filtered)
                        if filtered:  # Only add if there are records to insert
                            filtered_batches[model_class] = filtered
                        type_stats[model_class] = {
                            'before': before_count,
                            'after': after_count,
                            'removed': before_count - after_count
                        }
                    prefilter_duration = time.time() - prefilter_start
                    
                    # Log only if significant filtering occurred or if it's slow, with rate limiting
                    total_before = sum(len(b) for b in batches_by_type.values())
                    total_after = sum(len(b) for b in filtered_batches.values())
                    removed = total_before - total_after
                    
                    # Log if significant filtering (>50%) or slow (>0.1s), with rate limiting
                    # High duplicate rates (>90%) are normal when re-running imports, so rate limiting applies
                    if removed > total_before * 0.5 or prefilter_duration > 0.1:
                        # Build per-type breakdown
                        type_breakdown = []
                        for model_class, stats in type_stats.items():
                            model_name = model_class.__name__
                            type_breakdown.append(
                                f"{model_name}: {stats['before']} -> {stats['after']} "
                                f"({stats['removed']} removed)"
                            )
                        
                        # Main log message
                        log_msg = (
                            f"[Run {run.id}] Pre-filtered {total_before} -> {total_after} records "
                            f"(removed {removed} duplicates, {prefilter_duration:.2f}s)"
                        )
                        
                        # Add per-type breakdown if multiple types or significant filtering
                        if len(type_stats) > 1 or removed > 0:
                            log_msg += f" | Types: {', '.join(type_breakdown)}"
                        
                        self._prefilter_rate_logger.log(log_msg)
                    
                    batches_by_type = filtered_batches
                    if not batches_by_type:
                        # Only log skipping if it's not happening constantly (every batch)
                        if not hasattr(self, '_skip_logged') or (time.time() - getattr(self, '_last_skip_log_time', 0)) > 30:
                            logger.debug(f"[Run {run.id}] All records already exist, skipping batch")
                            self._skip_logged = True
                            self._last_skip_log_time = time.time()
                        run.records_skipped += len(batch)
                        return
            
            # Deduplicate within each type batch (bulk_create fails on within-batch duplicates even with ignore_conflicts=True)
            # ignore_conflicts only handles conflicts with existing DB records, not within-batch duplicates
            filtered_batches = {}
            for model_class, type_batch in batches_by_type.items():
                deduplicated = self._deduplicate_batch(type_batch)
                if deduplicated:  # Only add if there are records to insert
                    filtered_batches[model_class] = deduplicated
            batches_by_type = filtered_batches
            if not batches_by_type:
                run.records_skipped += len(batch)
                return
            
            # Insert each model type separately
            @handle_unrecoverable_errors(
                log_message=f"[Run {run.id}] Unrecoverable error in batch insert",
                logger_instance=logger,
                on_unrecoverable=lambda e: setattr(run, 'records_failed', run.records_failed + len(batch))
            )
            def _insert_batches() -> int:
                """Insert batches to database - extracted for decorator usage"""
                total_created = 0
                with transaction.atomic():
                    for model_class, type_batch in batches_by_type.items():
                        if self.use_copy:
                            # Use PostgreSQL COPY for fastest inserts
                            self._bulk_insert_via_copy(type_batch, model_class)
                        else:
                            # Standard Django ORM
                            # Always use ignore_conflicts=True as safety net (prefilter may miss edge cases)
                            model_class.objects.bulk_create(type_batch, ignore_conflicts=True)
                        total_created += len(type_batch)
                return total_created
            
            total_created = _insert_batches()
            run.records_created += total_created
        except Exception as e:
            # Recoverable errors: database constraint violations, connection issues
            # Re-raise to let caller decide (may want to retry or abort)
            run.records_failed += len(batch)
            logger.error(f"[Run {run.id}] Batch insert failed: {e}")
            raise
    
    def _upsert_batch_to_db(self, batch: list, run: IngestRun):
        """Upsert batch to database: create new records or update existing with latest data"""
        if not batch:
            return
        
        try:
            # Split batch by model type first (handles mixed batches from plugins that create multiple model types)
            from collections import defaultdict
            batches_by_type = defaultdict(list)
            for record in batch:
                batches_by_type[type(record)].append(record)
            
            # Get source_file_date from checkpoint
            source_file_date_str = run.checkpoint.get('source_file_date')
            source_file_date = None
            if source_file_date_str:
                try:
                    source_file_date = datetime.fromisoformat(source_file_date_str)
                    if timezone.is_naive(source_file_date):
                        source_file_date = timezone.make_aware(source_file_date)
                except (ValueError, TypeError):
                    logger.warning(f"[Run {run.id}] Could not parse source_file_date from checkpoint: {source_file_date_str}")
            
            # Set source_file_date on all incoming records
            if source_file_date:
                for record in batch:
                    if hasattr(record, 'source_file_date'):
                        record.source_file_date = source_file_date
            
            # Deduplicate within each type batch first (bulk_create fails on within-batch duplicates)
            deduplicated_batches = {}
            for model_class, type_batch in batches_by_type.items():
                deduplicated = self._deduplicate_batch(type_batch)
                if deduplicated:
                    deduplicated_batches[model_class] = deduplicated
            batches_by_type = deduplicated_batches
            if not batches_by_type:
                run.records_skipped += len(batch)
                return
            
            # Identify new and existing records per model type
            records_to_create = defaultdict(list)
            records_to_update = defaultdict(list)
            records_to_skip = 0
            
            for model_class, type_batch in batches_by_type.items():
                # Check if model has case_number field (required for upsert logic)
                if not hasattr(type_batch[0], 'case_number'):
                    # No case_number field, can't upsert - just create (e.g., VisaCutoffDate)
                    records_to_create[model_class] = type_batch
                    continue
                
                # Identify new and existing records
                new_records, existing_records_dict = _identify_new_and_existing(type_batch)
                
                # Add new records to create list
                records_to_create[model_class].extend(new_records)
                
                # Compare existing records with incoming to determine updates
                # Only iterate over records that exist in existing_records_dict
                for incoming_record in type_batch:
                    case_number = incoming_record.case_number
                    if case_number in existing_records_dict:
                        existing_record = existing_records_dict[case_number]
                        
                        # Compare source_file_date to determine if incoming is newer
                        incoming_date = getattr(incoming_record, 'source_file_date', None)
                        existing_date = getattr(existing_record, 'source_file_date', None)
                        
                        if self._is_newer_than_existing(incoming_date, existing_date):
                            # Incoming is newer - update existing record with all fields from incoming
                            # For merge-preserve fields (e.g. case_submitted, decision_date), keep existing
                            # value if incoming is null so we don't lose data when the same case appears
                            # in two files with different date completeness
                            for field in incoming_record._meta.fields:
                                if field.name in ['id', 'pk'] or field.primary_key:
                                    continue
                                # Skip auto timestamp fields - Django sets these automatically
                                if isinstance(field, models.DateTimeField) and (field.auto_now or field.auto_now_add):
                                    continue
                                incoming_val = getattr(incoming_record, field.name, None)
                                if field.name in MERGE_PRESERVE_FIELDS and incoming_val is None:
                                    existing_val = getattr(existing_record, field.name, None)
                                    setattr(existing_record, field.name, existing_val)
                                else:
                                    setattr(existing_record, field.name, incoming_val)
                            records_to_update[model_class].append(existing_record)
                        else:
                            # Existing is newer or equal - skip (keep existing)
                            records_to_skip += 1
            
            # Perform bulk operations
            @handle_unrecoverable_errors(
                log_message=f"[Run {run.id}] Unrecoverable error in batch upsert",
                logger_instance=logger,
                on_unrecoverable=lambda e: setattr(run, 'records_failed', run.records_failed + len(batch))
            )
            def _upsert_batches() -> tuple[int, int]:
                """Upsert batches to database - extracted for decorator usage"""
                total_created = 0
                total_updated = 0
                with transaction.atomic():
                    # Create new records
                    for model_class, create_batch in records_to_create.items():
                        if create_batch:
                            if self.use_copy:
                                self._bulk_insert_via_copy(create_batch, model_class)
                            else:
                                model_class.objects.bulk_create(create_batch, ignore_conflicts=True)
                            total_created += len(create_batch)
                    
                    # Update existing records
                    for model_class, update_batch in records_to_update.items():
                        if update_batch:
                            # Get all field names except id/pk
                            update_fields = [
                                f.name for f in model_class._meta.fields
                                if not f.primary_key and f.name != 'id'
                            ]
                            # Cap bulk_update batch size at 1000 to prevent memory exhaustion
                            # Large batch sizes create massive CASE statements (one WHEN per record × fields)
                            # which can consume 1.5GB+ RAM and take 1+ hours on low-memory instances
                            update_batch_size = min(self.batch_size, 1000)
                            model_class.objects.bulk_update(update_batch, update_fields, batch_size=update_batch_size)
                            total_updated += len(update_batch)
                
                return total_created, total_updated
            
            total_created, total_updated = _upsert_batches()
            run.records_created += total_created
            run.records_updated += total_updated
            run.records_skipped += records_to_skip
            
            # Log summary if significant activity
            if total_created > 0 or total_updated > 0 or records_to_skip > 0:
                logger.debug(
                    f"[Run {run.id}] Upserted batch: {total_created} created, {total_updated} updated, "
                    f"{records_to_skip} skipped (existing was newer)"
                )
        except Exception as e:
            # Recoverable errors: database constraint violations, connection issues
            # Re-raise to let caller decide (may want to retry or abort)
            run.records_failed += len(batch)
            logger.error(f"[Run {run.id}] Batch upsert failed: {e}")
            raise
    
    def _is_newer_than_existing(self, incoming_date: datetime | None, existing_date: datetime | None) -> bool:
        """Compare source file dates to determine if incoming is newer"""
        if existing_date is None:
            return True  # No existing date, treat as newer
        if incoming_date is None:
            return False  # No incoming date, keep existing
        return incoming_date > existing_date
    
    def _update_batch_to_db(self, batch: list, run: IngestRun):
        """Update existing records matched by case_number"""
        if not batch:
            return
        
        try:
            model_class = type(batch[0])
            valid_update_fields = []
            for field in self.update_fields:
                try:
                    model_class._meta.get_field(field)
                    valid_update_fields.append(field)
                except FieldDoesNotExist:
                    continue

            if not valid_update_fields:
                run.records_skipped += len(batch)
                logger.warning(
                    f"[Run {run.id}] No valid update fields for {model_class.__name__}; "
                    f"skipping {len(batch)} records"
                )
                return
            
            # Extract case_numbers from batch
            if not hasattr(batch[0], 'case_number'):
                logger.warning(f"[Run {run.id}] Model {model_class.__name__} has no case_number field, cannot update")
                run.records_failed += len(batch)
                return
            
            case_numbers = [r.case_number for r in batch]
            
            # Deduplicate case_numbers within batch
            unique_case_numbers = list(dict.fromkeys(case_numbers))  # Preserves order
            
            # Fetch existing records matching update_filter and case_numbers
            existing_queryset = model_class.objects.filter(case_number__in=unique_case_numbers)
            
            # Apply update_filter if specified
            if self.update_filter:
                existing_queryset = existing_queryset.filter(**self.update_filter)
            
            # Create lookup dict by case_number
            existing_records = {r.case_number: r for r in existing_queryset}
            
            # Match and update
            records_to_update = []
            matched_case_numbers = set()
            
            for new_record in batch:
                case_number = new_record.case_number
                if case_number in existing_records and case_number not in matched_case_numbers:
                    existing = existing_records[case_number]
                    # Copy fields from new_record to existing
                    for field in valid_update_fields:
                        if hasattr(new_record, field):
                            setattr(existing, field, getattr(new_record, field))
                    records_to_update.append(existing)
                    matched_case_numbers.add(case_number)
            
            # Bulk update
            if records_to_update:
                @handle_unrecoverable_errors(
                    log_message=f"[Run {run.id}] Unrecoverable error in batch update",
                    logger_instance=logger,
                    on_unrecoverable=lambda e: setattr(run, 'records_failed', run.records_failed + len(batch))
                )
                def _update_batches() -> None:
                    """Update batches in database - extracted for decorator usage"""
                    with transaction.atomic():
                        model_class.objects.bulk_update(
                            records_to_update,
                            valid_update_fields,
                            batch_size=self.batch_size
                        )
                
                _update_batches()
                run.records_updated += len(records_to_update)
            
            # Track unmatched records
            unmatched_count = len(batch) - len(records_to_update)
            if unmatched_count > 0:
                run.records_skipped += unmatched_count
                logger.debug(f"[Run {run.id}] {unmatched_count} records in batch not found in database (skipped)")
                
        except Exception as e:
            # Recoverable errors: database constraint violations, connection issues
            # Re-raise to let caller decide (may want to retry or abort)
            run.records_failed += len(batch)
            logger.error(f"[Run {run.id}] Batch update failed: {e}")
            raise
    
    def _generate_version_tag(self, run: IngestRun) -> str:
        """Generate version tag for ingest run"""
        # Domain and source_type are stored as strings in DB (CharField with choices)
        # Handle both enum objects and string values
        domain = run.source.domain.value if hasattr(run.source.domain, 'value') else run.source.domain
        source_type = run.source.source_type.value if hasattr(run.source.source_type, 'value') else run.source.source_type
        format_version = run.source.format_version or 'unknown'
        run_id = run.id
        return f"{domain}_{source_type}_{format_version}_run{run_id}"
    
    def _link_records_to_version(self, run: IngestRun, version: IngestVersion):
        """
        Link all records created in this run to the version.
        
        Records are linked based on:
        - Salary records: source_file from checkpoint
        - Cutoff dates: bulletin publication date (from source URL metadata)
        """
        version.refresh_from_db()
        
        source_file = run.checkpoint.get('filepath', '')
        if not source_file:
            logger.warning(f"[Run {run.id}] No filepath in checkpoint, cannot link records to version")
            return
        
        source_file = Path(source_file).name
        
        # Link salary records by source_file
        if run.source.source_type in [SourceType.LCA, SourceType.PERM]:
            updated = SalaryRecord.objects.filter(
                source_file=source_file,
                ingest_version__isnull=True
            ).update(ingest_version=version)
            logger.info(f"[Run {run.id}] Linked {updated} salary records to version {version.version_tag}")
        
        # Link cutoff dates (for visa bulletin)
        # Cutoff dates are linked via bulletin publication date extracted from source URL
        elif run.source.source_type == SourceType.BULLETIN:
            # Extract publication date from source metadata or URL
            # This assumes the bulletin was created during transform stage
            # For now, link by matching source URL pattern
            from models.visa_cutoff_date import Bulletin
            from django.utils.dateparse import parse_date
            
            # Try to find bulletin by source URL or metadata
            bulletin_date = run.source.metadata.get('publication_date')
            if bulletin_date:
                if isinstance(bulletin_date, str):
                    bulletin_date = parse_date(bulletin_date)
                
                if bulletin_date:
                    updated = VisaCutoffDate.objects.filter(
                        bulletin__publication_date=bulletin_date,
                        ingest_version__isnull=True
                    ).update(ingest_version=version)
                    logger.info(f"[Run {run.id}] Linked {updated} cutoff dates to version {version.version_tag}")
                else:
                    logger.warning(f"[Run {run.id}] Could not parse publication_date from metadata")
            else:
                logger.warning(f"[Run {run.id}] No publication_date in source metadata for bulletin linking")
    
    def _validate_post_ingest(self, plugin: DataSourcePlugin, run: IngestRun) -> ValidationResult:
        """
        Run post-ingest validation after load stage completes.
        
        Args:
            plugin: Plugin instance to run validation
            run: Completed IngestRun
            
        Returns:
            ValidationResult with errors and warnings
        """
        logger.info(f"[Run {run.id}] Running post-ingest validation...")
        validation_start = time.time()
        
        @handle_unrecoverable_errors(
            log_message=f"[Run {run.id}] Unrecoverable error in validation",
            logger_instance=logger
        )
        def _run_validation() -> ValidationResult:
            """Run plugin validation - extracted for decorator usage"""
            return plugin.validate_post_ingest(run)
        
        try:
            result = _run_validation()
            
            validation_duration = time.time() - validation_start
            if result.passed:
                logger.info(f"[Run {run.id}] Validation passed in {validation_duration:.2f}s")
            else:
                logger.error(f"[Run {run.id}] Validation failed in {validation_duration:.2f}s: {len(result.errors)} error(s)")
            
            return result
        except Exception as e:
            # Recoverable errors: plugin validation logic errors
            # Convert to validation result so pipeline can decide whether to abort
            logger.error(f"[Run {run.id}] Validation raised exception: {e}")
            return ValidationResult(
                passed=False,
                errors=[f"Validation exception: {str(e)}"],
                warnings=[]
            )
    
    def _validate_copy_preflight(self, records: list, fields: list, model_class) -> None:
        if self._copy_preflight_done:
            return
        self._copy_preflight_done = True
        decimal_fields = [f for f in fields if isinstance(f, models.DecimalField)]
        if not decimal_fields:
            return
        sample_records = records[:200]
        failures: list[tuple[str, object]] = []
        for record in sample_records:
            for field in decimal_fields:
                value = getattr(record, field.attname, None)
                if value is None or isinstance(value, (Decimal, int, float)):
                    continue
                try:
                    Decimal(str(value))
                except (InvalidOperation, ValueError, TypeError):
                    failures.append((field.attname, value))
                    if len(failures) >= 5:
                        break
            if len(failures) >= 5:
                break
        if failures:
            logger.error(
                "COPY preflight failed for %s; non-numeric values: %s",
                model_class.__name__,
                failures,
            )
            raise ValueError("COPY preflight failed: non-numeric DecimalField values detected")

    def _bulk_insert_via_copy(self, records: list, model_class):
        """Use PostgreSQL COPY for fastest bulk insert (3-10x faster than bulk_create)"""
        from io import StringIO
        
        if not records:
            return
        
        # Prepare data as tab-separated values
        buffer = StringIO()
        fields = [f for f in model_class._meta.fields if not f.primary_key]
        field_names = [f.attname for f in fields]
        schema = ModelCopySchema.from_model(model_class)

        self._validate_copy_preflight(records, fields, model_class)

        field_names_set = set(field_names)
        wage_fields = {"wage_from", "wage_to", "wage_unit"}
        if wage_fields & field_names_set and not wage_fields.issubset(field_names_set):
            missing = ", ".join(sorted(wage_fields - field_names_set))
            logger.error(
                "Schema validation failed for %s: missing wage fields: %s",
                model_class.__name__,
                missing,
            )
            raise ValueError(f"Schema mismatch: missing wage fields: {missing}")
        wage_fields_present = wage_fields.issubset(field_names_set)
        
        # DEBUG: Log field names to verify order
        field_names_str = ', '.join(f.attname for f in fields)
        logger.info(f"🔍 COPY field order for {model_class.__name__}: {field_names_str}")
        
        record_count = 0
        for record in records:
            values = []
            # Get unique identifier for logging (case_number if available)
            record_id = getattr(record, 'case_number', None) or f"record_{id(record)}"
            record_count += 1
            
            # DEBUG: Log first 3 records completely for debugging
            if record_count <= 3:
                logger.info(f"Record {record_count} ({record_id}): wage_from={getattr(record, 'wage_from', None)}, wage_to={getattr(record, 'wage_to', None)}, wage_unit={getattr(record, 'wage_unit', None)}")
            
            for field in fields:
                value = getattr(record, field.attname, None)
                if value is None:
                    if isinstance(field, models.DateTimeField) and (field.auto_now or field.auto_now_add) and not field.null:
                        values.append(timezone.now().isoformat())
                        continue
                    if isinstance(field, (models.CharField, models.TextField)) and not field.null:
                        values.append('')
                    else:
                        values.append('\\N')
                    continue
                if value == '' and field.attname.endswith('_id'):
                    logger.warning(
                        "COPY value warning [%s]: %s.%s has empty string for FK field; writing NULL. "
                        "Record: case_number=%s",
                        record_id,
                        model_class.__name__,
                        field.attname,
                        record_id,
                    )
                    values.append('\\N')
                    continue
                
                # Convert enum values to their string representation
                original_value = value
                if hasattr(value, 'value'):
                    # This is a Django TextChoices/IntegerChoices enum
                    value = value.value
                    # DEBUG: Log enum conversions for wage fields (first 3 records)
                    if record_count <= 3 and field.attname in ('wage_unit', 'wage_from', 'wage_to', 'prevailing_wage_unit', 'visa_program', 'case_status'):
                        logger.info(f"  ⚙️  {field.attname}: {original_value!r} -> {value!r}")
                
                # Debug: Log ALL values going to wage_to field  
                if field.attname == 'wage_to':
                    # Log EVERY record's wage_to to catch the bug
                    if value and isinstance(value, str) and not value.replace('.', '').replace('-', '').isdigit():
                        logger.error(
                            "🐛 BUG FOUND! Line %d: About to write non-numeric %r to wage_to for case %s. "
                            "Raw record fields: wage_from=%r (type=%s), wage_to=%r (type=%s), wage_unit=%r (type=%s)",
                            record_count,
                            value,
                            record_id,
                            getattr(record, 'wage_from', None),
                            type(getattr(record, 'wage_from', None)).__name__,
                            getattr(record, 'wage_to', None),
                            type(getattr(record, 'wage_to', None)).__name__,
                            getattr(record, 'wage_unit', None),
                            type(getattr(record, 'wage_unit', None)).__name__,
                        )

                # Normalize Decimal fields to avoid invalid numeric literals in COPY.
                if isinstance(field, models.DecimalField):
                    if value is None:
                        values.append('\\N')
                        continue
                    if isinstance(value, Decimal):
                        values.append(str(value))
                        continue
                    # Check for string values that can't be decimals
                    if isinstance(value, str):
                        # Strip whitespace and check if it looks like a decimal
                        cleaned = value.strip()
                        if not cleaned or not any(c.isdigit() for c in cleaned):
                            # Empty or no digits - write NULL
                            logger.warning(
                                "COPY value error [%s]: %s.%s has non-numeric string %r; writing NULL. "
                                "Record: case_number=%s",
                                record_id,
                                model_class.__name__,
                                field.attname,
                                value,
                                record_id,
                            )
                            values.append('\\N')
                            continue
                    try:
                        values.append(str(Decimal(str(value))))
                        continue
                    except (InvalidOperation, ValueError, TypeError):
                        logger.error(
                            "COPY value error [%s]: %s.%s has non-decimal value %r; writing NULL. "
                            "Record: case_number=%s, type=%s",
                            record_id,
                            model_class.__name__,
                            field.attname,
                            value,
                            record_id,
                            type(value).__name__,
                        )
                        values.append('\\N')
                        continue

                if value == '' and isinstance(
                    field,
                    (
                        models.IntegerField,
                        models.BigIntegerField,
                        models.SmallIntegerField,
                        models.PositiveIntegerField,
                        models.PositiveSmallIntegerField,
                        models.AutoField,
                        models.BigAutoField,
                        models.ForeignKey,
                    ),
                ):
                    logger.warning(
                        "COPY value warning [%s]: %s.%s has empty string for numeric field; writing NULL. "
                        "Record: case_number=%s",
                        record_id,
                        model_class.__name__,
                        field.attname,
                        record_id,
                    )
                    values.append('\\N')
                    continue

                if value is None:
                    values.append('\\N')
                    continue

                if isinstance(value, (int, float)):
                    values.append(str(value))
                    continue

                # Escape special characters for PostgreSQL COPY TEXT format
                # CRITICAL: Escape backslashes FIRST (backslash is escape character in COPY)
                # A trailing backslash before a tab would escape the tab, causing field misalignment!
                str_value = (str(value)
                            .replace('\\', '\\\\')  # Escape backslashes FIRST
                            .replace('\t', ' ')      # Then replace tabs
                            .replace('\n', ' ')
                            .replace('\r', ' '))
                values.append(str_value)

            # DEBUG: Log wage fields for records around line 786
            if wage_fields_present and 780 <= record_count <= 790:
                wage_from_pos = schema.wage_from
                wage_to_pos = schema.wage_to
                wage_unit_pos = schema.wage_unit
                logger.error(
                    "🔍 Line %d (%s): wage_from=%r, wage_to=%r, wage_unit=%r",
                    record_count,
                    record_id,
                    values[wage_from_pos] if len(values) > wage_from_pos else None,
                    values[wage_to_pos] if len(values) > wage_to_pos else None,
                    values[wage_unit_pos] if len(values) > wage_unit_pos else None,
                )
            
            # Also check if "year" is in wage_to position for ANY record
            if wage_fields_present and len(values) > schema.wage_to and values[schema.wage_to] == 'year':
                copy_line = '\t'.join(values)
                logger.error(
                    "🐛 GOTCHA! Line %d: COPY buffer has 'year' in wage_to position! Case: %s\n"
                    "   wage_from (pos %s): %r\n"
                    "   wage_to (pos %s): %r\n"
                    "   wage_unit (pos %s): %r\n"
                    "   Full COPY line preview: %s",
                    record_count,
                    record_id,
                    schema.wage_from,
                    values[schema.wage_from] if len(values) > schema.wage_from else None,
                    schema.wage_to,
                    values[schema.wage_to],
                    schema.wage_unit,
                    values[schema.wage_unit] if len(values) > schema.wage_unit else None,
                    copy_line[:300]
                )

            buffer.write('\t'.join(values) + '\n')
        
        buffer.seek(0)
        
        # DEBUG: Save buffer to file for inspection
        buffer_content = buffer.getvalue()
        debug_path = f"/tmp/copy_buffer_{model_class.__name__}.tsv"
        with open(debug_path, 'w') as f:
            f.write(buffer_content)
        logger.info(f"💾 Saved COPY buffer to {debug_path} ({len(buffer_content)} bytes, {len(records)} records)")
        
        # Reset buffer
        buffer.seek(0)
        
        with connection.cursor() as cursor:
            cursor.copy_from(
                buffer,
                model_class._meta.db_table,
                columns=field_names,
                null='\\N'
            )

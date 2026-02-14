"""Database utility functions for bulk operations and performance optimization"""

from typing import TypeVar, Generic, Iterable, Callable
from django.db import models, transaction
from models.salary import EmployerCluster
from lib.business.salary.cluster_utils import normalize_canonical_name

ModelType = TypeVar('ModelType', bound=models.Model)


def bulk_update_batched(
queryset_or_list: Iterable[ModelType],
    batch_size: int = 1000,
    fields: list[str] | None = None
) -> int:
    """
    Update multiple model instances in batches using bulk_update.
    
    More efficient than individual save() calls in loops.
    
    Args:
        queryset_or_list: Iterable of model instances to update
        batch_size: Number of records per batch (default: 1000)
        fields: List of field names to update (None = all fields)
    
    Returns:
        Total number of records updated
    
    Example:
        >>> employers = Employer.objects.filter(canonical_cluster__isnull=False)
        >>> for emp in employers:
        ...     emp.canonical_cluster = some_cluster
        >>> bulk_update_batched(employers, fields=['canonical_cluster'])
    """
    if isinstance(queryset_or_list, models.QuerySet):
        items = list(queryset_or_list)
    else:
        items = list(queryset_or_list)
    
    if not items:
        return 0
    
    # Determine model class from first item
    model_class = items[0].__class__
    
    # If fields not specified, update all non-pk fields
    if fields is None:
        fields = [
            f.name for f in model_class._meta.fields
            if not f.primary_key and not f.auto_created
        ]
    
    total_updated = 0
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        model_class.objects.bulk_update(batch, fields, batch_size=batch_size)
        total_updated += len(batch)
    
    return total_updated


def bulk_create_batched(
    items: list[ModelType],
    batch_size: int = 1000,
    ignore_conflicts: bool = False
) -> int:
    """
    Create multiple model instances in batches using bulk_create.
    
    More efficient than individual create() calls in loops.
    
    Args:
        items: List of model instances to create
        batch_size: Number of records per batch (default: 1000)
        ignore_conflicts: If True, ignore conflicts on unique constraints
    
    Returns:
        Total number of records created
    
    Example:
        >>> reviews = [EmployerClusteringReview(...) for ...]
        >>> bulk_create_batched(reviews, ignore_conflicts=True)
    """
    if not items:
        return 0
    
    model_class = items[0].__class__
    total_created = 0
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        model_class.objects.bulk_create(
            batch,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts
        )
        total_created += len(batch)
    
    return total_created


class BatchedUpdateCollector:
    """
    Generic helper for collecting model updates and automatically flushing in batches.
    
    Handles the common pattern of:
    - Collecting records to update in a list
    - Automatically flushing when batch_size is reached
    - Supporting dry_run mode
    - Wrapping updates in transactions
    - Tracking count of processed records
    
    Example:
        >>> collector = BatchedUpdateCollector(
        ...     fields=['employer'],
        ...     batch_size=1000,
        ...     dry_run=False
        ... )
        >>> for record in records:
        ...     record.employer = employer
        ...     collector.add(record)
        >>> count = collector.flush()  # Flush remaining records
        >>> total_updated = collector.count
    """
    
    def __init__(
        self,
        fields: list[str],
        batch_size: int = 1000,
        dry_run: bool = False,
        use_transaction: bool = True
    ):
        """
        Initialize batched update collector.
        
        Args:
            fields: List of field names to update
            batch_size: Number of records per batch (default: 1000)
            dry_run: If True, don't actually update (default: False)
            use_transaction: If True, wrap updates in transaction.atomic() (default: True)
        """
        self.fields = fields
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.use_transaction = use_transaction
        self.records: list[ModelType] = []
        self.count = 0
    
    def add(self, record: ModelType) -> int:
        """
        Add a record to the batch. Automatically flushes if batch_size is reached.
        
        Args:
            record: Model instance to update
        
        Returns:
            Number of records flushed (0 if no flush occurred)
        """
        if self.dry_run:
            self.count += 1
            return 0
        
        self.records.append(record)
        
        if len(self.records) >= self.batch_size:
            return self._flush()
        
        return 0
    
    def _flush(self) -> int:
        """Internal flush method - updates database and resets records list"""
        if not self.records or self.dry_run:
            return 0
        
        flushed_count = len(self.records)
        
        if self.use_transaction:
            with transaction.atomic():
                bulk_update_batched(self.records, batch_size=self.batch_size, fields=self.fields)
        else:
            bulk_update_batched(self.records, batch_size=self.batch_size, fields=self.fields)
        
        self.count += flushed_count
        self.records = []
        
        return flushed_count
    
    def flush(self) -> int:
        """
        Flush any remaining records in the batch.
        
        Returns:
            Number of records flushed
        """
        return self._flush()


class BatchedUpdates:
    """
    Helper class for managing batched updates and creates with automatic flushing.
    
    Prevents memory buildup by automatically flushing when batch_size is reached.
    
    Example:
        >>> batched = BatchedUpdates(batch_size=1000, dry_run=False)
        >>> for employer in employers:
        ...     employer.canonical_cluster = cluster
        ...     batched.add_employer_update(employer)
        >>> batched.flush_all(employer_fields=['canonical_cluster'])
    """
    
    def __init__(self, batch_size: int = 1000, dry_run: bool = False):
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.employers_to_update: list = []
        self.review_entries: list = []
        
        # Pre-load existing cluster ids and canonical names (values(), not full ORM) to save memory
        # Lazy-load full cluster instances on first use into _cluster_cache
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("Pre-loading existing employer clusters into cache...")
        existing_rows = list(
            EmployerCluster.objects.values("id", "canonical_name")
        )
        # normalized_canonical_name -> id (avoids holding full ORM objects for 200k+ clusters)
        self._cluster_id_by_normalized: dict[str, int] = {
            normalize_canonical_name(row["canonical_name"]): row["id"]
            for row in existing_rows
        }
        # Lazy-loaded and new clusters: normalized_key -> EmployerCluster
        self._cluster_cache: dict[str, object] = {}
        cluster_count = len(self._cluster_id_by_normalized)
        if cluster_count > 0:
            logger.info(f"Loaded {cluster_count:,} existing cluster ids into cache")
        
        self._clusters_to_create: list = []  # List of EmployerCluster instances to create
        # Deduplication: track employer IDs in current batch to prevent duplicate updates
        self._employer_update_ids: set = set()  # Set of employer.pk values in current batch
        
        # Pre-load existing slugs into cache (single query at startup)
        # Prevents N+1 slug loading in flush_clusters() - was reloading ALL slugs per flush
        self._used_slugs: set[str] = set(
            EmployerCluster.objects
            .filter(slug__isnull=False)
            .values_list('slug', flat=True)
        )
        logger.info(f"Loaded {len(self._used_slugs):,} existing slugs into cache")
    
    def add_employer_update(self, employer):
        """Add employer to update batch, flush if batch_size reached"""
        if self.dry_run:
            return
        
        # Ensure clusters are saved before updating employers (Django requires saved FKs)
        if self._clusters_to_create:
            self.flush_clusters()
        
        # Deduplicate by employer ID to prevent updating same employer multiple times in one batch
        # This prevents unique constraint violations when same employer appears in multiple pairs
        employer_id = employer.pk
        if not hasattr(self, '_employer_update_ids'):
            self._employer_update_ids = set()
        
        if employer_id in self._employer_update_ids:
            # Already in batch, update the existing instance instead of adding duplicate
            for existing_emp in self.employers_to_update:
                if existing_emp.pk == employer_id:
                    # Update the existing instance with new cluster assignment
                    existing_emp.canonical_cluster = employer.canonical_cluster
                    break
            return
        
        self._employer_update_ids.add(employer_id)
        self.employers_to_update.append(employer)
        if len(self.employers_to_update) >= self.batch_size:
            self.flush_employer_updates()
    
    def add_review_entry(self, review):
        """Add review entry to create batch, flush if batch_size reached"""
        if self.dry_run:
            return
        
        self.review_entries.append(review)
        if len(self.review_entries) >= self.batch_size:
            self.flush_review_entries()
    
    def flush_employer_updates(self, fields: list[str] | None = None):
        """Flush pending employer updates"""
        if not self.employers_to_update or self.dry_run:
            return
        
        # Ensure clusters are saved before updating employers (Django requires saved FKs for bulk_update)
        if self._clusters_to_create:
            self.flush_clusters()
        
        # Filter out any employers without primary keys (shouldn't happen, but safety check)
        valid_employers = [emp for emp in self.employers_to_update if emp.pk is not None]
        if len(valid_employers) != len(self.employers_to_update):
            from django_config.logging_config import setup_logging
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Filtered out {len(self.employers_to_update) - len(valid_employers)} "
                f"employers without primary keys from update batch"
            )
        
        if valid_employers:
            try:
                bulk_update_batched(valid_employers, batch_size=self.batch_size, fields=fields)
            except Exception as e:
                # Log error details for debugging
                from django_config.logging_config import setup_logging
                import logging
                logger = logging.getLogger(__name__)
                
                # Check if it's a unique constraint violation (data integrity issue)
                error_str = str(e)
                if 'unique constraint' in error_str.lower() or 'duplicate key' in error_str.lower():
                    # This is a data integrity issue - there are duplicate employers in the database
                    # Log the error but try to continue by updating employers individually
                    logger.warning(
                        f"Unique constraint violation in bulk_update (data integrity issue): {e}. "
                        f"Attempting individual updates for {len(valid_employers)} employers..."
                    )
                    
                    # Fallback: update employers individually, skipping ones that fail
                    updated_count = 0
                    failed_count = 0
                    for emp in valid_employers:
                        try:
                            emp.save(update_fields=fields or ['canonical_cluster'])
                            updated_count += 1
                        except Exception as individual_error:
                            failed_count += 1
                            if failed_count <= 5:  # Log first 5 failures
                                logger.warning(
                                    f"Failed to update employer ID {emp.pk} "
                                    f"({emp.name_normalized}, {emp.city}, {emp.state}): {individual_error}"
                                )
                    
                    if failed_count > 0:
                        logger.warning(
                            f"Updated {updated_count}/{len(valid_employers)} employers. "
                            f"{failed_count} failed (likely duplicate employers in database)"
                        )
                else:
                    # Other errors - re-raise
                    logger.error(
                        f"Error in bulk_update: {e}. "
                        f"Batch size: {len(valid_employers)}, "
                        f"Sample employer IDs: {[emp.pk for emp in valid_employers[:5]]}"
                    )
                    raise
        
        self.employers_to_update = []
        # Clear the deduplication set after flushing
        if hasattr(self, '_employer_update_ids'):
            self._employer_update_ids.clear()
    
    def flush_review_entries(self):
        """Flush pending review entries"""
        if not self.review_entries or self.dry_run:
            return

        bulk_create_batched(self.review_entries, batch_size=self.batch_size, ignore_conflicts=True)
        self.review_entries = []
    
    def get_or_queue_cluster(self, canonical_name: str):
        """
        Get existing cluster from cache or queue a new one for batch creation.
        
        Uses case-insensitive lookup to prevent duplicate clusters with different casing
        (e.g., "BBC RETAIL" vs "BBC Retail").
        
        Returns a cluster instance (may be unsaved if queued for batch creation).
        The cluster will be created in batch when flush_clusters() is called.
        
        Note: If a new cluster is created, it preserves the exact casing of canonical_name
        provided (first occurrence wins). Subsequent lookups with different casing will
        return the same cluster instance.
        """
        # Use normalized (lowercase) key for case-insensitive lookup
        normalized_key = normalize_canonical_name(canonical_name)
        
        if normalized_key in self._cluster_cache:
            return self._cluster_cache[normalized_key]
        # Lazy-load existing cluster from pre-loaded id (avoids holding all clusters in memory)
        if normalized_key in self._cluster_id_by_normalized:
            cluster_id = self._cluster_id_by_normalized[normalized_key]
            cluster = EmployerCluster.objects.get(pk=cluster_id)
            self._cluster_cache[normalized_key] = cluster
            return cluster
        
        # Create unsaved cluster instance with original casing (will be saved in batch)
        # The canonical_name field keeps the exact casing from the first employer
        cluster = EmployerCluster(canonical_name=canonical_name)
        self._cluster_cache[normalized_key] = cluster
        self._clusters_to_create.append(cluster)
        
        # Auto-flush if batch size reached
        if len(self._clusters_to_create) >= self.batch_size:
            self.flush_clusters()
        
        return cluster
    
    def flush_clusters(self):
        """Flush pending cluster creations (batch create)"""
        if not self._clusters_to_create or self.dry_run:
            return
        
        # CRITICAL FIX: Create mapping from canonical_name to unsaved instances
        # We need to update these instances in-place after bulk_create so that
        # employers referencing them will have saved cluster instances
        unsaved_by_name = {c.canonical_name: c for c in self._clusters_to_create}
        
        # Batch create clusters with ignore_conflicts=True to handle race conditions
        # and concurrent runs gracefully (requires unique constraint on canonical_name)
        bulk_create_batched(self._clusters_to_create, batch_size=self.batch_size, ignore_conflicts=True)
        
        # Refresh cluster instances with IDs from database
        # We need to reload them to get the IDs assigned by the database
        # Note: If ignore_conflicts skipped some, we'll get the existing ones from DB
        canonical_names = list(unsaved_by_name.keys())
        created_clusters = EmployerCluster.objects.filter(canonical_name__in=canonical_names)
        
        # ✅ FIX PART 1: Generate slugs for newly created clusters (bulk_create bypasses save())
        # bulk_create doesn't call save(), so slugs aren't auto-generated
        # We need to explicitly generate them after creation
        clusters_needing_slugs = [c for c in created_clusters if not c.slug]
        if clusters_needing_slugs:
            from django.utils.text import slugify
            
            for cluster in clusters_needing_slugs:
                if cluster.canonical_name:
                    # Generate unique slug using same logic as model's generate_slug()
                    base_slug = slugify(cluster.canonical_name)
                    slug = base_slug
                    counter = 1
                    
                    while slug in self._used_slugs:
                        slug = f"{base_slug}-{counter}"
                        counter += 1
                    
                    cluster.slug = slug
                    self._used_slugs.add(slug)
            
            # Bulk update slugs
            EmployerCluster.objects.bulk_update(
                clusters_needing_slugs,
                ['slug'],
                batch_size=self.batch_size
            )
        
        # ✅ FIX PART 2: Update cache and unsaved instances in ONE loop (performance optimization)
        # - Update cache using normalized key (consistent with lookups in get_or_queue_cluster)
        # - Update original unsaved instances in-place with DB values (employers hold references)
        for cluster in created_clusters:
            # Update cache with normalized key
            normalized_key = normalize_canonical_name(cluster.canonical_name)
            self._cluster_cache[normalized_key] = cluster
            
            # Update original unsaved instance in-place
            # Employers hold references to these instances, so we need to copy the DB values into them
            unsaved_instance = unsaved_by_name.get(cluster.canonical_name)
            if unsaved_instance:
                unsaved_instance.pk = cluster.pk
                unsaved_instance.id = cluster.id
                for field in cluster._meta.fields:
                    setattr(unsaved_instance, field.name, getattr(cluster, field.name))
        
        self._clusters_to_create = []
    
    def flush_all(self, employer_fields: list[str] | None = None):
        """Flush all pending updates and creates"""
        # Flush clusters first (employers need cluster IDs)
        self.flush_clusters()
        self.flush_employer_updates(employer_fields)
        self.flush_review_entries()


def process_in_batches(
    queryset: models.QuerySet,
    batch_size: int = 1000,
    func: Callable[[list[ModelType]], None] | None = None
) -> int:
    """
    Process a queryset in batches to avoid loading all records into memory.
    
    More efficient than loading all records with list(queryset) for large datasets.
    
    Args:
        queryset: Django QuerySet to process
        batch_size: Number of records per batch (default: 1000)
        func: Optional function to call on each batch
    
    Returns:
        Total number of records processed
    
    Example:
        >>> def process_batch(batch):
        ...     updates = []
        ...     for record in batch:
        ...         record.wage_annual = calculate_annual_wage(...)
        ...         updates.append(record)
        ...     bulk_update_batched(updates, fields=['wage_annual'])
        >>> 
        >>> queryset = SalaryRecord.objects.filter(wage_annual__isnull=True)
        >>> process_in_batches(queryset, batch_size=1000, func=process_batch)
    """
    total_processed = 0
    
    # Use iterator to avoid loading all records into memory
    batch = []
    for record in queryset.iterator(chunk_size=batch_size):
        batch.append(record)
        
        if len(batch) >= batch_size:
            if func:
                func(batch)
            total_processed += len(batch)
            batch = []
    
    # Process remaining records
    if batch:
        if func:
            func(batch)
        total_processed += len(batch)
    
    return total_processed


def bulk_delete_batched(
    queryset: models.QuerySet,
    batch_size: int = 1000
) -> int:
    """
    Delete records from a queryset in batches.
    
    More efficient than queryset.delete() for very large datasets as it
    processes in smaller batches to avoid long-running transactions.
    
    Args:
        queryset: Django QuerySet to delete from
        batch_size: Number of records per batch (default: 1000)
    
    Returns:
        Total number of records deleted
    
    Example:
        >>> orphaned = Employer.objects.filter(salary_records__isnull=True)
        >>> bulk_delete_batched(orphaned, batch_size=1000)
    """
    if not queryset.exists():
        return 0
    
    # Get model class from queryset
    model_class = queryset.model
    
    total_deleted = 0
    
    # Delete in batches using primary keys
    while True:
        # Get batch of primary keys
        batch_ids = list(queryset.values_list('pk', flat=True)[:batch_size])
        
        if not batch_ids:
            break
        
        # Delete this batch
        deleted_count = model_class.objects.filter(pk__in=batch_ids).delete()[0]
        total_deleted += deleted_count
        
        # If we got fewer than batch_size, we're done
        if deleted_count < batch_size:
            break
    
    return total_deleted

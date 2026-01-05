# Unified Ingest Pipeline Design

## Executive Summary

A modular, resumable data ingest pipeline framework built on Django that supports multiple data sources (DoL salary data, Visa Bulletin) with incremental updates, checkpoint/resume capability, performance optimization, and rollback support.

**Key Requirements:**
- Expandable to any number of data sources via plugin architecture
- Maintains DB of seen sources (URL, download status, processing status, records, errors, timing, metadata)
- Supports incremental updates at each stage (download → parse → transform → load)
- Performance-aware: batched streaming, no downtime, separated ingest/serve performance
- Modular: adding new data source touches minimal code (plugin + config)
- Debuggable: fine-grained progress tracking and instrumentation
- DB agnostic: can swap database backends
- Versioned: rollback capability for bad ingests

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Pipeline Orchestrator                        │
│  (coordinates stages, handles resumption, tracks progress)       │
└─────────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
    │Download │──▶│  Parse  │──▶│Transform│──▶│  Load   │
    │ Stage   │   │  Stage  │   │  Stage  │   │  Stage  │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Source Registry (DB)                          │
│  (tracks: URL, status, errors, records, timing, version)        │
└─────────────────────────────────────────────────────────────────┘
```

## Core Models (`models/ingest/`)

### Enums

```python
# models/ingest/enums.py
class DataDomain(models.TextChoices):
    """Data source domain (organization/system)"""
    DOL = 'dol', 'Department of Labor'
    VISA_BULLETIN = 'visa_bulletin', 'Visa Bulletin'

class SourceType(models.TextChoices):
    """Type of data source within a domain"""
    LCA = 'lca', 'LCA (H-1B)'
    PERM = 'perm', 'PERM'
    BULLETIN = 'bulletin', 'Visa Bulletin'

class IngestStatus(models.TextChoices):
    """Overall status of an ingest run"""
    PENDING = 'pending', 'Pending'
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'

class IngestStage(models.TextChoices):
    """Current stage within the pipeline"""
    PENDING = 'pending', 'Pending'
    DOWNLOADING = 'downloading', 'Downloading'
    PARSING = 'parsing', 'Parsing'
    TRANSFORMING = 'transforming', 'Transforming'
    LOADING = 'loading', 'Loading to Database'
    COMPLETED = 'completed', 'Completed'
```

### 1. DataSource - Registry of all data sources

```python
class DataSource(models.Model):
    """Registry of known data sources (URLs, files, APIs)"""
    url = models.URLField(unique=True)
    domain = models.CharField(max_length=50, choices=DataDomain.choices)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    format_version = models.CharField(max_length=20)  # Schema version detection
    discovered_at = models.DateTimeField(auto_now_add=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)  # When file was last downloaded
    local_file_path = models.CharField(max_length=500, blank=True)  # Cached local path if downloaded
    metadata = models.JSONField(default=dict)  # Flexible metadata
```

**Purpose:**
- Track all known data sources (URLs, files)
- Store metadata (format version, domain, type)
- Cache local file path after download (stored in IngestRun during active runs)
- Enable discovery and tracking of new sources

**Note:** `local_file_path` is primarily for caching/reference. Active download paths during a run are tracked in `IngestRun.checkpoint['filepath']` to avoid stale paths if files are moved/deleted.

### 2. IngestRun - Tracks each complete pipeline execution

```python
class IngestRun(models.Model):
    """
    Single execution of the complete ingest pipeline (all stages).
    
    Each IngestRun represents one full pass through: download → parse → transform → load.
    The pipeline can be interrupted and resumed at any stage via checkpoints.
    """
    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(max_length=20, choices=IngestStatus.choices, default=IngestStatus.PENDING)
    stage = models.CharField(max_length=20, choices=IngestStage.choices, default=IngestStage.PENDING)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Progress tracking
    records_processed = models.IntegerField(default=0)
    records_created = models.IntegerField(default=0)
    records_updated = models.IntegerField(default=0)
    records_failed = models.IntegerField(default=0)
    
    # Resumption support
    checkpoint = models.JSONField(default=dict)  # {
    #     "stage": "loading",
    #     "last_row": 50000,
    #     "batch": 51,
    #     "filepath": "/path/to/file.xlsx"  # Local file path during run
    # }
    
    # Error tracking
    error_message = models.TextField(blank=True)
    error_traceback = models.TextField(blank=True)
```

**Purpose:**
- Track one complete pipeline execution (all stages: download → parse → transform → load)
- Enable resumption from checkpoints at any stage
- Store errors and timing for debugging
- Track progress across all stages

**State Graph:**
```
status: PENDING, stage: PENDING
    ↓
status: RUNNING, stage: DOWNLOADING
    ↓ (checkpoint saved: filepath stored)
status: RUNNING, stage: PARSING
    ↓ (checkpoint saved: last_row, batch)
status: RUNNING, stage: TRANSFORMING
    ↓ (checkpoint saved: records_processed)
status: RUNNING, stage: LOADING
    ↓ (checkpoint saved: last_row, batch)
status: COMPLETED, stage: COMPLETED

OR (on error/interruption):
status: FAILED/RUNNING, stage: <last_stage>  # Can resume from checkpoint
```

**Status vs Stage:**
- `status`: High-level state (PENDING, RUNNING, COMPLETED, FAILED)
- `stage`: Current pipeline stage (DOWNLOADING, PARSING, TRANSFORMING, LOADING)
- Both are needed: status for filtering runs, stage for resumption logic

**Resumption Capability:**
- ✅ **Yes, can resume partial ingest runs** - Checkpoints saved at each stage transition
- ✅ **Can resume mid-stage** - Checkpoint includes `last_row`, `batch` for precise resumption
- ✅ **No intermediate "DONE" stages needed** - Stage transitions are implicit (when stage changes, previous is done)
- **Example:** If interrupted at row 50,000 during PARSING, resume from `checkpoint['last_row'] = 50000`

**Checkpoint Structure:**
```python
checkpoint = {
    'stage': 'parsing',           # Current stage
    'last_row': 50000,            # Last processed row (for resume)
    'batch': 50,                  # Last completed batch
    'filepath': '/path/to/file',  # Local file path
    'stage_start_time': '2025-12-06T10:00:00'  # For timing
}
```

### 3. IngestVersion - For rollback capability

```python
class IngestVersion(models.Model):
    """Version marker for rollback - links records to their ingest run"""
    run = models.OneToOneField(IngestRun, on_delete=models.CASCADE, related_name='version')
    version_tag = models.CharField(max_length=50, unique=True)  # "dol_lca_2024q4_v1"
    is_active = models.BooleanField(default=True)
    supersedes = models.ForeignKey('self', null=True, on_delete=models.SET_NULL)
```

**Purpose:**
- Link all records from an ingest run to a version tag
- Enable rollback by version
- Track version lineage (supersedes relationship)

**Version Reference Strategy:**

**Option A: Foreign Key by ID (Recommended)**
```python
# In SalaryRecord, VisaCutoffDate:
ingest_version = models.ForeignKey(
    'ingest.IngestVersion',
    on_delete=models.SET_NULL,
    null=True,
    db_index=True
)
```

**Tradeoffs:**
- ✅ Fast joins (indexed FK)
- ✅ Referential integrity enforced by DB
- ✅ Efficient queries (`WHERE ingest_version_id = 123`)
- ❌ Requires lookup to get version_tag for human-readable rollback

**Option B: String Tag Reference**
```python
ingest_version_tag = models.CharField(max_length=50, db_index=True)
```

**Tradeoffs:**
- ✅ Human-readable in queries
- ✅ Direct rollback by tag without lookup
- ❌ No referential integrity (orphaned tags possible)
- ❌ Slower joins (string comparison vs int)
- ❌ Tag changes require updates across all records

**Recommendation:** Use Option A (FK by ID). For rollback operations, look up version by tag once, then use ID for efficient deletion. This provides both performance and integrity.

## Plugin Architecture (`lib/ingest/`)

### Base Classes

```python
# lib/ingest/base.py
class DataSourcePlugin(ABC):
    """Base class for all data source plugins"""
    domain: str  # 'dol', 'visa_bulletin'
    source_type: str  # 'lca', 'perm', 'bulletin'
    
    @abstractmethod
    def discover_sources(self) -> list[SourceInfo]: 
        """Discover new data sources (scrape URLs, check APIs)"""
        ...
    
    @abstractmethod
    def download(self, source: DataSource, run: IngestRun) -> Path: 
        """Download source with resume support"""
        ...
    
    @abstractmethod
    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]: 
        """Stream parse file, yield dicts, update checkpoint"""
        ...
    
    @abstractmethod
    def transform(self, record: dict) -> Model | None: 
        """Apply corrections, validation, enrichment"""
        ...
    
    @abstractmethod
    def get_format_version(self, filepath: Path) -> str: 
        """Detect format version for schema changes"""
        ...

# lib/ingest/registry.py
class PluginRegistry:
    """Central registry for data source plugins"""
    _plugins: dict[str, DataSourcePlugin] = {}
    
    @classmethod
    def register(cls, plugin: DataSourcePlugin): 
        """Register a plugin"""
        key = f"{plugin.domain.value}:{plugin.source_type.value}"
        cls._plugins[key] = plugin
    
    @classmethod
    def get_plugin(cls, domain: str, source_type: str) -> DataSourcePlugin:
        """Get plugin by domain and source type (accepts enum or string)"""
        # Normalize to string values
        domain_val = domain.value if hasattr(domain, 'value') else domain
        source_val = source_type.value if hasattr(source_type, 'value') else source_type
        key = f"{domain_val}:{source_val}"
        return cls._plugins[key]
```

### Example Plugin Structure

```python
# lib/ingest/plugins/dol_lca.py
class H1BSalaryDataSourcePlugin(DataSourcePlugin):
    """Plugin for Department of Labor H-1B LCA disclosure data"""
    domain = DataDomain.DOL
    source_type = SourceType.LCA
    
    def discover_sources(self) -> list[SourceInfo]:
        """Scrape DOL page for available LCA files"""
        # Check https://www.dol.gov/agencies/eta/foreign-labor/performance
        # Find all LCA disclosure data links
        ...
    
    def download(self, source: DataSource, run: IngestRun) -> Path:
        """Download with resume support, progress tracking"""
        # Check if file already downloaded
        # Resume partial downloads
        # Update run.checkpoint with download progress
        ...
    
    def parse(self, filepath: Path, run: IngestRun) -> Iterator[dict]:
        """Stream parse CSV/Excel, yield dicts, update checkpoint"""
        # Option 1: Use existing lib/salary_import._read_data_file with streaming (pandas)
        # Option 2: Use openpyxl for true streaming (for very large Excel files)
        # Resume from run.checkpoint['last_row'] if present
        # Update checkpoint every N rows
        
        # For large Excel files, can use:
        # return parse_excel_streaming(filepath, run)  # openpyxl streaming
        # Or standard pandas approach:
        # return _read_data_file(filepath, stream=True)  # pandas chunked
        ...
    
    def transform(self, record: dict) -> SalaryRecord | None:
        """Apply corrections, validation, enrichment"""
        # Use existing lib/salary_import._process_row logic
        # Return None for invalid records (filtered out)
        # 
        # IMPORTANT: Error Handling Principle
        # Plugins should NOT catch and suppress non-plugin-specific errors. All exceptions
        # should propagate to the framework. The orchestrator distinguishes between:
        # - Unrecoverable errors (ImportError, ModuleNotFoundError): Abort the entire run
        # - Recoverable errors (data issues, parsing problems): Log and continue processing
        # Plugins should only handle plugin-specific validation (e.g., missing required
        # fields should return None, not raise exceptions).
        ...
    
    def get_format_version(self, filepath: Path) -> str:
        """Detect format version from column names or file structure"""
        # Check column mappings match known versions
        # Return version string like "2024q4" or "legacy_2008"
        ...
```

## Pipeline Orchestrator (`lib/ingest/orchestrator.py`)

### Stage-by-Stage vs End-to-End Streaming

**Two approaches for pipeline execution:**

**Option A: Stage-by-Stage (Current Design)**
- Each stage completes fully before next starts
- Download → Parse → Transform → Load
- Checkpoint after each stage
- **Pros:**
  - Clear separation of concerns
  - Easy to resume from any stage
  - Can inspect intermediate results
  - Simpler error handling per stage
- **Cons:**
  - Requires storing intermediate data (file on disk)
  - More disk I/O (write file, read file)
  - Slightly higher latency (can't start loading until all parsing done)

**Option B: End-to-End Streaming**
- Stream directly: Download → Parse → Transform → Load
- No intermediate storage
- **Pros:**
  - Lower latency (start loading as soon as first records parsed)
  - Less disk I/O
  - Lower memory (no intermediate file)
- **Cons:**
  - Harder to resume (need to re-download to resume parsing)
  - More complex error handling (which stage failed?)
  - Can't inspect intermediate results

**Recommendation:** Use **Stage-by-Stage** for resumability and debuggability. The disk I/O overhead is acceptable for the benefits of checkpointing and error isolation.

### Implementation

```python
import logging
from models.ingest.enums import IngestStatus, IngestStage

logger = logging.getLogger(__name__)

class PipelineOrchestrator:
    """Coordinates pipeline stages with resumption support"""
    
    def __init__(
        self, 
        batch_size: int = 1000,
        adaptive_batch: bool = True,
        use_copy: bool = False,
        prefilter_existing: bool = True
    ):
        """
        Args:
            batch_size: Initial batch size (will adapt if adaptive_batch=True)
            adaptive_batch: Automatically adjust batch size based on DB state
            use_copy: Use PostgreSQL COPY instead of bulk_create (faster, PostgreSQL-only)
            prefilter_existing: Pre-filter existing cases before insert (faster)
        """
        self.adaptive_batch = adaptive_batch
        self.use_copy = use_copy
        self.prefilter_existing = prefilter_existing
        self.initial_batch_size = batch_size
        self.batch_size = batch_size
    
    def run(self, source: DataSource, resume: bool = True) -> IngestRun:
        """Execute full pipeline, resuming from checkpoint if interrupted"""
        run = self._get_or_create_run(source, resume)
        plugin = PluginRegistry.get_plugin(source.domain, source.source_type)
        
        logger.info(f"[Run {run.id}] Starting pipeline for source: {source.url}")
        logger.info(f"[Run {run.id}] Current stage: {run.stage}, status: {run.status}")
        
        try:
            run.status = IngestStatus.RUNNING
            run.save()
            
            # Stage 1: Download
            if run.stage in [IngestStage.PENDING, IngestStage.DOWNLOADING]:
                filepath = self._download_stage(plugin, source, run)
            
            # Stage 2: Parse
            if run.stage in [IngestStage.DOWNLOADING, IngestStage.PARSING]:
                records = self._parse_stage(plugin, filepath, run)
            
            # Stage 3: Transform
            if run.stage in [IngestStage.PARSING, IngestStage.TRANSFORMING]:
                models = self._transform_stage(plugin, records, run)
            
            # Stage 4: Load to Database
            if run.stage in [IngestStage.TRANSFORMING, IngestStage.LOADING]:
                self._load_to_db_stage(models, run)
            
            run.status = IngestStatus.COMPLETED
            run.stage = IngestStage.COMPLETED
            run.completed_at = timezone.now()
            logger.info(f"[Run {run.id}] Pipeline completed successfully")
        except Exception as e:
            run.status = IngestStatus.FAILED
            run.error_message = str(e)
            run.error_traceback = traceback.format_exc()
            logger.error(f"[Run {run.id}] Pipeline failed at stage {run.stage}: {e}")
            raise
        finally:
            run.save()
        
        return run
    
    def _download_stage(self, plugin, source, run):
        """Download stage with resume support"""
        stage_start = time.time()
        run.stage = IngestStage.DOWNLOADING
        run.save()
        logger.info(f"[Run {run.id}] Stage: DOWNLOADING")
        
        filepath = plugin.download(source, run)
        
        # Store filepath in checkpoint for later stages
        run.checkpoint['filepath'] = str(filepath)
        run.stage = IngestStage.PARSING
        run.save()
        
        stage_duration = time.time() - stage_start
        logger.info(f"[Run {run.id}] Download completed in {stage_duration:.2f}s: {filepath}")
        return filepath
    
    def _parse_stage(self, plugin, filepath, run):
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
                next(records, None)
        
        run.stage = IngestStage.TRANSFORMING
        run.save()
        
        stage_duration = time.time() - stage_start
        logger.info(f"[Run {run.id}] Parse stage ready (duration: {stage_duration:.2f}s)")
        return records
    
    def _transform_stage(self, plugin, records, run):
        """Transform stage with progress tracking"""
        stage_start = time.time()
        run.stage = IngestStage.TRANSFORMING
        run.save()
        logger.info(f"[Run {run.id}] Stage: TRANSFORMING")
        
        for record in records:
            model = plugin.transform(record)
            if model:
                yield model
                run.records_processed += 1
                if run.records_processed % 10000 == 0:
                    logger.debug(f"[Run {run.id}] Transformed {run.records_processed:,} records")
                    run.save(update_fields=['records_processed'])
        
        run.stage = IngestStage.LOADING
        run.save()
        
        stage_duration = time.time() - stage_start
        logger.info(f"[Run {run.id}] Transform completed: {run.records_processed:,} records in {stage_duration:.2f}s")
    
    def _load_to_db_stage(self, models: Iterator, run: IngestRun):
        """Batched streaming insert to database with checkpoint updates"""
        stage_start = time.time()
        run.stage = IngestStage.LOADING
        run.save()
        logger.info(f"[Run {run.id}] Stage: LOADING TO DATABASE")
        
        batch = []
        for i, model in enumerate(models):
            batch.append(model)
            if len(batch) >= self.batch_size:
                self._insert_batch_to_db(batch, run)
                run.checkpoint = {
                    'stage': IngestStage.LOADING,
                    'last_row': i,
                    'batch': i // self.batch_size,
                    'filepath': run.checkpoint.get('filepath')  # Preserve filepath
                }
                run.records_processed = i + 1
                run.save(update_fields=['checkpoint', 'records_processed'])
                
                if (i + 1) % (self.batch_size * 10) == 0:
                    rate = (i + 1) / (time.time() - stage_start)
                    logger.info(f"[Run {run.id}] Loaded {i + 1:,} records ({rate:,.0f} rec/sec)")
                
                batch = []
        
        # Insert remaining records
        if batch:
            self._insert_batch_to_db(batch, run)
        
        stage_duration = time.time() - stage_start
        logger.info(f"[Run {run.id}] Database load completed: {run.records_created:,} records in {stage_duration:.2f}s")
    
    def _insert_batch_to_db(self, batch: list, run: IngestRun):
        """Insert batch to database with error handling and optimizations"""
        try:
            # Pre-filter existing cases if enabled
            if self.prefilter_existing:
                source_file = run.checkpoint.get('filepath', '')
                if source_file:
                    batch = _prefilter_existing_cases(batch, source_file)
                    if not batch:
                        run.records_skipped += len(batch)
                        return
            
            with transaction.atomic():
                model_class = type(batch[0])
                
                if self.use_copy:
                    # Use PostgreSQL COPY for fastest inserts
                    bulk_insert_via_copy(batch, model_class)
                else:
                    # Standard Django ORM
                    model_class.objects.bulk_create(batch, ignore_conflicts=not self.prefilter_existing)
            
            run.records_created += len(batch)
        except Exception as e:
            run.records_failed += len(batch)
            logger.error(f"[Run {run.id}] Batch insert failed: {e}")
            raise
```

### Logging Approach

**Structured logging with run context:**
- All log messages include `[Run {run.id}]` prefix for filtering
- Per-stage timing logged automatically
- Progress updates every 10k records (configurable)
- Error messages include full context (stage, checkpoint, source)

**Log levels:**
- `INFO`: Stage transitions, completion, summary stats
- `DEBUG`: Per-batch progress, checkpoint updates
- `WARNING`: Slow batches, validation issues
- `ERROR`: Failures with full traceback

**Example log output:**
```
[Run 123] Starting pipeline for source: https://dol.gov/...
[Run 123] Current stage: pending, status: pending
[Run 123] Stage: DOWNLOADING
[Run 123] Download completed in 45.2s: /data/lca_fy2024.xlsx
[Run 123] Stage: PARSING
[Run 123] Stage: TRANSFORMING
[Run 123] Transformed 10,000 records
[Run 123] Transform completed: 500,000 records in 120.5s
[Run 123] Stage: LOADING TO DATABASE
[Run 123] Loaded 10,000 records (2,500 rec/sec)
[Run 123] Database load completed: 500,000 records in 200.3s
[Run 123] Pipeline completed successfully
```

## Database Performance Strategy

### 1. Ingest/Serve Separation

**Approach:** Add version tracking to existing models

```python
# Add to SalaryRecord and VisaCutoffDate models
ingest_version = models.ForeignKey(
    'ingest.IngestVersion',
    on_delete=models.SET_NULL,
    null=True,
    related_name='salary_records'  # or 'cutoff_dates'
)

# During ingest:
# - Insert records with ingest_version set
# - After validation, activate version
# - Serving queries filter by is_active=True

# Atomic swap after successful ingest:
def activate_version(version: IngestVersion):
    """Activate new version, deactivate old"""
    with transaction.atomic():
        # Deactivate old version
        IngestVersion.objects.filter(
            source=version.source,
            is_active=True
        ).update(is_active=False)
        
        # Activate new version
        version.is_active = True
        version.save()
```

### 2. Batched Streaming (existing pattern)

- Keep current 1000-record batch size
- Stream from file, never load full dataset in memory
- Update checkpoint every batch for resumption

### 3. Index Management for Zero Interruption

**Chosen Approach: Version-Based Separation**

We use **version-based separation** (not staging tables). The approaches are mutually exclusive - we chose version-based for simplicity and zero interruption.

**How Version-Based Works:**
```python
# Records tagged with ingest_version
# Serving queries filter: WHERE ingest_version.is_active = True
# New ingest: Insert with is_active=False, then atomic flip

def load_with_versioning(model_class, version: IngestVersion):
    """Load records with version, activate atomically"""
    # 1. Insert all records with is_active=False (fast, indexes updated but not queried)
    model_class.objects.bulk_create([
        model(ingest_version=version, ...) for model in models
    ])
    
    # 2. Index updates happen during inserts, but serving queries don't hit them
    #    because they filter by is_active=True (which doesn't match new records)
    
    # 3. Atomic activation (single UPDATE, fast, no interruption)
    with transaction.atomic():
        IngestVersion.objects.filter(
            source=version.source,
            is_active=True
        ).update(is_active=False)
        version.is_active = True
        version.save()
```

**Why This Doesn't Cause Interruption:**

1. **Indexes are NOT disabled** - They're updated during inserts, but serving queries use a different index path:
   - Serving queries: `WHERE is_active=True` → uses `is_active_idx` (indexed, fast)
   - New records: `is_active=False` → indexes updated, but not queried by serving

2. **No index contention** - Serving queries and ingest use different index paths:
   - Serving: Queries `is_active=True` records (existing index)
   - Ingest: Updates `is_active=False` records (separate index entries)

3. **Atomic activation is fast** - Single UPDATE statement, milliseconds:
   ```sql
   UPDATE ingest_version SET is_active=False WHERE source_id=X AND is_active=True;
   UPDATE ingest_version SET is_active=True WHERE id=Y;
   ```
   These are fast index lookups, not table scans.

4. **No serving slowdown** - During ingest:
   - Serving queries continue using `is_active=True` index (unchanged)
   - New records inserted with `is_active=False` (separate index entries)
   - Activation is atomic UPDATE (fast, no table lock)

**Why Not Staging Tables:**
- More complex (table creation, schema management)
- Requires more disk space (duplicate tables)
- Table rename operations can be slower on large tables
- Version-based is simpler and achieves same zero-interruption goal

**Index Optimization (Optional, for very large ingests):**
```python
# Records tagged with ingest_version
# Serving queries filter: WHERE ingest_version.is_active = True
# New ingest: Insert with is_active=False, then atomic flip

def load_with_versioning(model_class, version: IngestVersion):
    """Load records with version, activate atomically"""
    # 1. Insert all records with is_active=False (fast, indexes updated but not queried)
    model_class.objects.bulk_create([
        model(ingest_version=version, ...) for model in models
    ])
    
    # 2. Rebuild indexes if needed (can be done incrementally)
    # Index updates happen, but serving queries don't hit them (is_active=False)
    
    # 3. Atomic activation (single UPDATE, fast)
    with transaction.atomic():
        IngestVersion.objects.filter(
            source=version.source,
            is_active=True
        ).update(is_active=False)
        version.is_active = True
        version.save()
```

**Benefits:**
- ✅ Zero interruption: Serving queries filter by is_active (indexed)
- ✅ Fast inserts: Index updates happen, but not queried during ingest
- ✅ Simple rollback: Set is_active=False
- ✅ No table swaps: Single table, versioned records

**Index Optimization (Optional, for very large ingests):**

For extremely large ingests (millions of records), you can optimize index maintenance:

```python
def optimize_indexes_for_bulk(model_class):
    """Temporarily optimize PostgreSQL settings for bulk load"""
    # Increase maintenance_work_mem for faster index builds
    # Note: On Lightsail with ~1GB RAM, use 256MB max (not 1GB)
    with connection.cursor() as cursor:
        # Use 25% of available RAM, max 256MB for Lightsail
        cursor.execute("SET maintenance_work_mem = '256MB'")  # Safe for 1GB RAM
        # ... bulk insert ...
        cursor.execute("RESET maintenance_work_mem")

def analyze_after_load(model_class):
    """Update statistics after bulk load (helps query planner)"""
    with connection.cursor() as cursor:
        # ANALYZE updates statistics for query planner (fast, doesn't block)
        cursor.execute(f"ANALYZE {model_class._meta.db_table}")
```

**Note:** We do NOT disable indexes. Indexes are maintained during inserts, but serving queries use a different index path (`is_active=True`), so there's no contention.

## Performance Optimizations

### Adaptive Batch Sizing

**Problem:** Fixed batch size (1000) may not be optimal as database grows. Large DBs need smaller batches, small DBs can use larger batches.

**Solution:** Dynamically adjust batch size based on database state and observed performance.

```python
def get_optimal_batch_size(model_class, current_count: int) -> int:
    """Calculate optimal batch size based on database size"""
    if current_count < 100_000:
        return 5_000  # Small DB: larger batches (less transaction overhead)
    elif current_count < 1_000_000:
        return 2_000  # Medium DB: medium batches
    else:
        return 1_000  # Large DB: smaller batches (current default)

class PipelineOrchestrator:
    def __init__(self, batch_size: int = None, adaptive: bool = True):
        self.adaptive = adaptive
        self.initial_batch_size = batch_size or 1000
        self.batch_size = self.initial_batch_size
    
    def _load_to_db_stage(self, models: Iterator, run: IngestRun):
        """Batched streaming insert with adaptive batch sizing"""
        # Adjust batch size based on current DB size
        if self.adaptive:
            current_count = SalaryRecord.objects.count()
            self.batch_size = get_optimal_batch_size(SalaryRecord, current_count)
            logger.info(f"[Run {run.id}] Adaptive batch size: {self.batch_size}")
        
        batch = []
        recent_batch_times = []  # Track performance
        
        for i, model in enumerate(models):
            batch.append(model)
            if len(batch) >= self.batch_size:
                batch_start = time.time()
                self._insert_batch_to_db(batch, run)
                batch_time = time.time() - batch_start
                
                # Adaptive adjustment: if batches getting slow, reduce size
                recent_batch_times.append(batch_time)
                if len(recent_batch_times) > 10:
                    avg_time = sum(recent_batch_times[-10:]) / 10
                    if avg_time > 1.0 and self.adaptive:  # Slower than 1 second
                        self.batch_size = max(500, self.batch_size - 100)
                        logger.info(f"[Run {run.id}] Reduced batch size to {self.batch_size} (avg: {avg_time:.2f}s)")
                
                run.checkpoint = {
                    'stage': IngestStage.LOADING,
                    'last_row': i,
                    'batch': i // self.batch_size,
                    'filepath': run.checkpoint.get('filepath'),
                    'batch_size': self.batch_size  # Save for resume
                }
                run.records_processed = i + 1
                run.save(update_fields=['checkpoint', 'records_processed'])
                batch = []
        
        if batch:
            self._insert_batch_to_db(batch, run)
```

**Benefits:**
- Automatically adapts to database state
- Reduces transaction overhead for small DBs
- Prevents slowdown for large DBs
- Self-tuning based on observed performance

### Pre-filter Existing Cases

**Problem:** `ignore_conflicts=True` checks uniqueness for every record, which gets slower as DB grows.

**Solution:** Pre-filter existing cases using efficient database queries before bulk insert.

```python
def _prefilter_existing_cases(
    records: list[SalaryRecord], 
    source_file: str,
    batch_size: int = 10000
) -> list[SalaryRecord]:
    """Filter out existing cases using efficient batch queries"""
    case_numbers = [r.case_number for r in records]
    
    # Query in batches to avoid huge IN clauses
    existing = set()
    for i in range(0, len(case_numbers), batch_size):
        batch_cases = case_numbers[i:i+batch_size]
        existing.update(
            SalaryRecord.objects
            .filter(source_file=source_file, case_number__in=batch_cases)
            .values_list('case_number', flat=True)
        )
    
    # Return only new records
    return [r for r in records if r.case_number not in existing]

def _load_to_db_stage(self, models: Iterator, run: IngestRun):
    """Load with pre-filtering for better performance"""
    batch = []
    for i, model in enumerate(models):
        batch.append(model)
        
        if len(batch) >= self.batch_size:
            # Pre-filter existing cases before insert
            new_records = _prefilter_existing_cases(batch, run.source.url)
            
            if new_records:
                self._insert_batch_to_db(new_records, run, ignore_conflicts=False)
            else:
                run.records_skipped += len(batch)
            
            # Update checkpoint...
            batch = []
```

**Benefits:**
- Reduces conflict checking overhead
- More efficient for large batches
- Can use `ignore_conflicts=False` (faster) since conflicts already filtered

### PostgreSQL COPY for Bulk Inserts (Optional)

**Problem:** Django ORM `bulk_create` has overhead. PostgreSQL COPY is 3-10x faster.

**Solution:** Use PostgreSQL COPY for very large ingests (optional, can be enabled per plugin).

```python
from django.db import connection
from io import StringIO

def bulk_insert_via_copy(records: list[SalaryRecord], model_class):
    """Use PostgreSQL COPY for fastest bulk insert (3-10x faster than bulk_create)"""
    if not records:
        return
    
    # Prepare data as tab-separated values
    buffer = StringIO()
    for record in records:
        # Convert record to TSV format
        values = [
            str(record.case_number),
            record.visa_program,
            record.employer_name,
            # ... all fields
        ]
        buffer.write('\t'.join(values) + '\n')
    buffer.seek(0)
    
    # Get column names
    columns = [f.name for f in model_class._meta.fields if not f.primary_key]
    
    with connection.cursor() as cursor:
        cursor.copy_from(
            buffer,
            model_class._meta.db_table,
            columns=columns,
            null=''
        )

# In orchestrator, add option:
class PipelineOrchestrator:
    def __init__(self, batch_size: int = 1000, use_copy: bool = False):
        self.use_copy = use_copy  # Enable for very large ingests
        ...
    
    def _insert_batch_to_db(self, batch: list, run: IngestRun):
        """Insert batch using COPY or bulk_create"""
        if self.use_copy:
            bulk_insert_via_copy(batch, type(batch[0]))
        else:
            # Standard Django ORM
            model_class = type(batch[0])
            model_class.objects.bulk_create(batch, ignore_conflicts=True)
```

**Tradeoffs:**
- ✅ 3-10x faster than `bulk_create`
- ✅ Bypasses ORM overhead
- ❌ More complex (raw SQL)
- ❌ Must handle conflicts manually (use pre-filtering)
- ❌ PostgreSQL-specific (less portable)

**When to Use:**
- Very large ingests (millions of records)
- When performance is critical
- When you can accept PostgreSQL-specific code

### Streaming Excel with openpyxl (Optional)

**Problem:** pandas loads entire Excel file into memory. For very large files, this is slow and memory-intensive.

**Solution:** Use openpyxl directly for true streaming (optional, can be enabled per plugin).

```python
from openpyxl import load_workbook

def parse_excel_streaming(filepath: Path, run: IngestRun) -> Iterator[dict]:
    """Stream Excel file row-by-row using openpyxl (true streaming)"""
    wb = load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    
    # Get headers from first row
    headers = [cell.value for cell in ws[1]]
    
    # Resume from checkpoint if present
    start_row = run.checkpoint.get('last_row', 0) + 2  # +2 for header and 0-indexing
    if start_row > 2:
        logger.info(f"[Run {run.id}] Resuming Excel parse from row {start_row}")
    
    for row_num, row in enumerate(ws.iter_rows(min_row=start_row, values_only=True), start=start_row):
        record = dict(zip(headers, row))
        
        # Update checkpoint periodically
        if row_num % 10000 == 0:
            run.checkpoint['last_row'] = row_num - 1
            run.save(update_fields=['checkpoint'])
        
        yield record
    
    wb.close()
```

**Benefits:**
- ✅ True streaming (no full file load)
- ✅ Lower memory usage
- ✅ 30-50% faster for very large files
- ✅ Can resume from any row

**Tradeoffs:**
- ❌ Different library (openpyxl vs pandas)
- ❌ May need different data type handling
- ❌ Requires testing

**When to Use:**
- Very large Excel files (>500k rows)
- Memory-constrained environments
- When pandas memory usage is problematic

### Persistent Employer Cache

**Problem:** Employer lookups are repeated across multiple imports. Current cache is per-import only.

**Solution:** Use Django cache framework for persistent employer caching across imports.

```python
from django.core.cache import cache

def _get_or_create_employer_cached(
    employer_name: str,
    city: str,
    state: str,
    cache_timeout: int = 3600  # 1 hour
) -> Employer:
    """Get or create employer with persistent cache"""
    cache_key = f"employer:{Employer.normalize_name(employer_name)}:{city}:{state}"
    employer_id = cache.get(cache_key)
    
    if employer_id:
        try:
            return Employer.objects.get(pk=employer_id)
        except Employer.DoesNotExist:
            # Cache stale, continue to create
            pass
    
    # Not in cache, create or get
    employer, _ = Employer.objects.get_or_create(
        name_normalized=Employer.normalize_name(employer_name),
        city=city,
        state=state,
        defaults={'name': employer_name}
    )
    
    # Cache for future imports
    cache.set(cache_key, employer.id, timeout=cache_timeout)
    return employer
```

**Benefits:**
- ✅ Reduces repeated employer lookups across imports
- ✅ Faster for files with many duplicate employers
- ✅ Works across multiple import runs

### Performance Optimization Summary

**Quick Wins (Low Effort, Medium Impact):**
1. ✅ **Adaptive batch sizing** - 10-30% improvement
2. ✅ **Pre-filter existing cases** - 5-15% improvement
3. ✅ **Persistent employer cache** - 5-10% improvement

**High Impact (Medium-High Effort):**
4. ⭐ **PostgreSQL COPY** - 3-10x improvement (optional, for very large ingests)
5. ⭐ **Streaming Excel with openpyxl** - 30-50% faster reading (optional, for large files)

**Expected Combined Impact:**
- **Current:** 80-180s for 618k rows
- **After Quick Wins:** 50-120s (20-55% faster)
- **After High Impact:** 10-30s (5-15x faster)

**Implementation Priority:**
1. Start with adaptive batch sizing (easy, good impact)
2. Add pre-filtering (easy, good impact)
3. Add persistent cache (easy, moderate impact)
4. Consider COPY/openpyxl only if needed for very large ingests

**How This Achieves Zero Interruption:**
1. **Version-based**: Serving queries use `WHERE is_active=True` (indexed). New records have `is_active=False` during ingest, so serving queries never touch them.
2. **Atomic activation**: Single UPDATE flips `is_active` flags. No partial state visible.
3. **Index separation**: Index updates happen on inactive records, serving queries use active index.

**How This Separates Ingest/Serve Performance:**
1. **Different index paths**: Serving queries use `is_active_idx`, ingest updates inactive records (separate index entries).
2. **No contention**: Serving queries never lock rows being inserted (different is_active values).
3. **No serving slowdown**: Index updates on `is_active=False` records don't affect queries on `is_active=True` records.

## Rollback Implementation

### Source-Level Rollback

```python
def rollback_ingest(version_tag: str):
    """Remove all records from a specific ingest version"""
    version = IngestVersion.objects.get(version_tag=version_tag)
    
    with transaction.atomic():
        # Delete all records from this version
        SalaryRecord.objects.filter(ingest_version=version).delete()
        VisaCutoffDate.objects.filter(ingest_version=version).delete()
        
        # Deactivate version
        version.is_active = False
        version.save()
        
        # Reactivate previous version if exists
        if version.supersedes:
            version.supersedes.is_active = True
            version.supersedes.save()
            
            logger.info(f"Rolled back to version: {version.supersedes.version_tag}")
```

### Periodic Snapshots

```python
# scripts/ingest/snapshot.py
def create_snapshot(tables: list[str], tag: str):
    """Create point-in-time snapshot using pg_dump"""
    from django.conf import settings
    from datetime import datetime
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"snapshot_{tag}_{timestamp}.sql"
    backup_dir = Path(settings.BASE_DIR) / 'backups'
    backup_dir.mkdir(exist_ok=True)
    
    db_settings = settings.DATABASES['default']
    
    subprocess.run([
        'pg_dump',
        '-h', db_settings['HOST'],
        '-U', db_settings['USER'],
        '-t', ' -t '.join(tables),
        '-f', str(backup_dir / filename),
        db_settings['NAME']
    ], check=True)
    
    logger.info(f"Created snapshot: {filename}")
    return backup_dir / filename

def restore_snapshot(snapshot_path: Path):
    """Restore from snapshot"""
    from django.conf import settings
    
    db_settings = settings.DATABASES['default']
    
    subprocess.run([
        'psql',
        '-h', db_settings['HOST'],
        '-U', db_settings['USER'],
        '-d', db_settings['NAME'],
        '-f', str(snapshot_path)
    ], check=True)
```

## File Structure

```
lib/ingest/
├── __init__.py
├── base.py              # Abstract base classes (DataSourcePlugin)
├── registry.py          # Plugin registry
├── orchestrator.py      # Pipeline coordinator
├── checkpoint.py        # Resumption logic utilities
├── versioning.py        # Rollback utilities
└── plugins/
    ├── __init__.py
    ├── dol_lca.py       # H-1B LCA plugin (wraps lib/salary_import.py)
    ├── dol_perm.py      # PERM plugin (wraps lib/salary_import.py)
    └── visa_bulletin.py # Visa bulletin plugin (wraps lib/parsing/bulletin/db_importer.py)

models/ingest/
├── __init__.py
├── enums.py             # DataDomain, SourceType, IngestStatus, IngestStage
├── data_source.py       # DataSource model
├── ingest_run.py        # IngestRun model
└── ingest_version.py    # IngestVersion model

scripts/ingest/
├── __init__.py
├── run_pipeline.py      # CLI entry point
├── discover_sources.py  # Find new data sources
├── rollback.py          # Rollback commands
└── snapshot.py          # Backup utilities
```

## CLI Interface

```bash
# Discover new sources (doesn't ingest)
bazel run //:ingest -- discover --domain dol
bazel run //:ingest -- discover --domain visa_bulletin

# Discover AND ingest in one command (recommended)
bazel run //:ingest -- discover-and-ingest --domain dol
bazel run //:ingest -- discover-and-ingest --all-domains

# Run pipeline for specific source
bazel run //:ingest -- run --source-id 123
bazel run //:ingest -- run --url "https://..."

# Run all pending sources (sources that haven't been ingested yet)
bazel run //:ingest -- run --all-pending

# Resume interrupted run
bazel run //:ingest -- resume --run-id 456

# Check status
bazel run //:ingest -- status
bazel run //:ingest -- status --source-id 123

# Rollback bad ingest
bazel run //:ingest -- rollback --version dol_lca_2024q4_v1

# Create snapshot
bazel run //:ingest -- snapshot --tag pre_2025_update

# List sources
bazel run //:ingest -- list-sources
```

**Workflow Options:**

1. **Manual (stage-by-stage):**
   ```bash
   bazel run //:ingest -- discover --domain dol
   bazel run //:ingest -- run --all-pending
   ```

2. **Automated (discover and ingest):**
   ```bash
   bazel run //:ingest -- discover-and-ingest --all-domains
   # Equivalent to: discover → run --all-pending
   ```

3. **Cron-friendly (idempotent):**
   ```bash
   # Safe to run repeatedly - only processes new/pending sources
   bazel run //:ingest -- discover-and-ingest --all-domains
   ```

## Instrumentation

### Progress Logging

```python
# Enhanced logging with run context
logger.info(f"[Run {run.id}] Stage: {run.stage}")
logger.info(f"[Run {run.id}] Progress: {run.records_processed:,}/{total:,} ({pct:.1f}%)")
logger.info(f"[Run {run.id}] Rate: {rate:,.0f} records/sec")
logger.info(f"[Run {run.id}] ETA: {eta}")

# Per-stage timing
logger.info(f"[Run {run.id}] Download: {download_time:.2f}s")
logger.info(f"[Run {run.id}] Parse: {parse_time:.2f}s")
logger.info(f"[Run {run.id}] Transform: {transform_time:.2f}s")
logger.info(f"[Run {run.id}] Load: {load_time:.2f}s")
```

### Stage Execution Tracking

**Question:** Should we have a separate DB entity for stage execution within ingest run?

**Option A: Current Design (Single IngestRun Entity)**
```python
# All stage info in IngestRun.checkpoint and stage field
IngestRun:
  - stage: current stage
  - checkpoint: {"last_row": 50000, "stage": "parsing", ...}
  - records_processed: total across all stages
  - started_at, completed_at: overall timing
```

**Tradeoffs:**
- ✅ Simple: One entity per run
- ✅ Sufficient for most use cases
- ❌ Can't track per-stage timing separately
- ❌ Can't track per-stage errors separately
- ❌ Harder to query "how long did parsing take across all runs?"

**Option B: Separate StageExecution Entity (More Granular)**
```python
class StageExecution(models.Model):
    """Individual stage execution within an ingest run"""
    run = models.ForeignKey(IngestRun, on_delete=models.CASCADE, related_name='stages')
    stage = models.CharField(max_length=20, choices=IngestStage.choices)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True)
    records_processed = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    checkpoint = models.JSONField(default=dict)  # Stage-specific checkpoint
```

**Tradeoffs:**
- ✅ Granular tracking: Per-stage timing, errors, progress
- ✅ Easy queries: "Average parsing time across all runs"
- ✅ Better debugging: See which stage failed and when
- ✅ Historical analysis: Track stage performance over time
- ❌ More complex: Additional model, more DB writes
- ❌ More storage: One record per stage per run

**Recommendation:** Start with **Option A** (current design). Add **Option B** later if you need:
- Per-stage performance analysis
- Detailed stage-level error tracking
- Historical stage timing trends

**Migration Path:**
- Phase 1: Use Option A (IngestRun only)
- Phase 2: If needed, add StageExecution model
- Phase 3: Populate StageExecution from IngestRun.checkpoint data
- Phase 4: Update orchestrator to create StageExecution records

### Metrics (Easy to Add Later)

**Design for extensibility:** All timing and counts are already tracked in `IngestRun` model. Adding metrics export is straightforward.

**Future Integration Points:**
```python
# lib/ingest/metrics.py (optional, add when needed)
# Easy to add Prometheus, StatsD, or custom metrics

class IngestMetrics:
    """Metrics exporter - add when monitoring infrastructure is ready"""
    
    @staticmethod
    def record_stage_completion(run: IngestRun, stage: str, duration: float):
        """Record stage completion - hook into orchestrator"""
        # Prometheus example:
        # stage_duration.labels(domain=run.source.domain, stage=stage).observe(duration)
        pass
    
    @staticmethod
    def record_records_processed(run: IngestRun, count: int):
        """Record records processed - hook into checkpoint updates"""
        # Prometheus example:
        # records_processed.labels(domain=run.source.domain).inc(count)
        pass
```

**Current State:**
- All metrics data available in `IngestRun` model (timing, counts, errors)
- Can query via Django ORM for dashboards
- No external dependencies yet

**When to Add:**
- When you need real-time alerting
- When you need cross-run aggregation
- When you have monitoring infrastructure (Prometheus, etc.)

**For Now:**
- Use `IngestRun` queries for status checks
- Logs provide real-time visibility
- Can add metrics layer later without changing core code

## Migration Path from Current Code

### Phase 1: Add Models (No Breaking Changes)
- Create `models/ingest/` with DataSource, IngestRun, IngestVersion
- Add migrations
- Existing importers continue working unchanged

### Phase 2: Wrap Existing Importers as Plugins
- Create `lib/ingest/plugins/dol_lca.py` that wraps `lib/salary_import.import_csv_file`
- Create `lib/ingest/plugins/visa_bulletin.py` that wraps `lib/parsing/bulletin/db_importer.save_bulletin_to_db`
- Register plugins in `lib/ingest/plugins/__init__.py`
- Test plugins work independently

### Phase 3: Add Orchestrator
- Implement `lib/ingest/orchestrator.py`
- Add checkpoint support to existing parsers
- Test resumption works

### Phase 4: Add Source Discovery
- Implement discovery methods in plugins
- Create `scripts/ingest/discover_sources.py`
- Test discovery finds new sources

### Phase 5: Add Versioning and Rollback
- Add `ingest_version` FK to `SalaryRecord` and `VisaCutoffDate`
- Implement versioning in orchestrator
- Create rollback utilities
- Test rollback works

### Phase 6: Migrate Scripts
- ✅ Completed: `scripts/salary/import_data.py` removed (replaced by unified ingest pipeline)
- ✅ Completed: `scripts/bulletin/refresh_data.py` and `refresh_incremental.py` removed (replaced by unified ingest pipeline)
- ✅ Test end-to-end

### Phase 7: Add Snapshots
- Implement snapshot utilities
- Add cron job for periodic snapshots
- Test restore works

## Key Files to Modify

### New Files
- `models/ingest/__init__.py`
- `models/ingest/enums.py`
- `models/ingest/data_source.py`
- `models/ingest/ingest_run.py`
- `models/ingest/ingest_version.py`
- `lib/ingest/__init__.py`
- `lib/ingest/base.py`
- `lib/ingest/registry.py`
- `lib/ingest/orchestrator.py`
- `lib/ingest/checkpoint.py`
- `lib/ingest/versioning.py`
- `lib/ingest/plugins/__init__.py`
- `lib/ingest/plugins/dol_lca.py`
- `lib/ingest/plugins/dol_perm.py`
- `lib/ingest/plugins/visa_bulletin.py`
- `scripts/ingest/__init__.py`
- `scripts/ingest/run_pipeline.py`
- `scripts/ingest/discover_sources.py`
- `scripts/ingest/rollback.py`
- `scripts/ingest/snapshot.py`

### Modified Files
- `models/__init__.py` - Import ingest models
- `models/salary.py` - Add `ingest_version` FK
- `models/visa_cutoff_date.py` - Add `ingest_version` FK
- `lib/salary_import.py` - Extract reusable functions for plugin
- `lib/parsing/bulletin/db_importer.py` - Extract reusable functions for plugin
- `BUILD` - Add new targets for ingest scripts

## Implementation Checklist

### Core Functionality
- [ ] Create ingest models (DataSource, IngestRun, IngestVersion)
- [ ] Implement plugin base classes and registry
- [ ] Build pipeline orchestrator with checkpoint/resume support
- [ ] Refactor salary_import.py into DOL LCA/PERM plugins
- [ ] Refactor bulletin importer into plugin
- [ ] Add ingest_version FK to existing models, implement rollback
- [ ] Create unified CLI for pipeline operations
- [ ] Add periodic snapshot backup utility
- [ ] Write tests for orchestrator and plugins
- [ ] Update documentation

### Performance Optimizations (Quick Wins)
- [ ] Implement adaptive batch sizing in orchestrator
- [ ] Add pre-filtering for existing cases before bulk insert
- [ ] Add persistent employer cache (Django cache framework)

### Performance Optimizations (High Impact - Optional)
- [ ] Add PostgreSQL COPY support for very large ingests
- [ ] Add openpyxl streaming option for very large Excel files
- [ ] Benchmark and tune batch sizes for different DB sizes

## Benefits

1. **Modularity**: New data source = new plugin file + config entry
2. **Resumability**: Interrupted ingests resume from checkpoint
3. **Observability**: Fine-grained progress tracking and error reporting
4. **Rollback**: Source-level rollback via version tags
5. **Performance**: Batched streaming, index management, ingest/serve separation
6. **DB Agnostic**: Django ORM abstracts database (PostgreSQL, SQLite, etc.)
7. **Minimal Dependencies**: Built on Django, no heavy orchestration frameworks

---

*Last Updated: December 2025*

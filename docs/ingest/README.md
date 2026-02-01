# Ingest Pipeline Documentation

This directory contains documentation for the unified ingest pipeline framework that handles data ingestion from multiple sources (DOL salary data, Visa Bulletin).

## Overview

The ingest pipeline is a modular, resumable framework built on Django that supports:
- Multiple data sources via plugin architecture
- Incremental updates at each stage (download → parse → transform → load → validate)
- Checkpoint/resume capability for long-running imports
- Performance optimization with batched streaming
- Versioning and rollback support
- Automatic validation after ingestion

## Documentation Files

### Architecture and Design
- **PIPELINE_DESIGN.md** - Complete design document for the unified ingest pipeline
  - Plugin architecture
  - Stage flow (download → parse → transform → load → validate)
  - Core models (DataSource, IngestRun, IngestVersion)
  - Checkpoint/resume mechanism
  - Performance optimization strategies

### Validation
- **VALIDATION_FRAMEWORK.md** - Ingest validation framework documentation
  - Validation flow and integration
  - ValidationResult structure (errors vs warnings)
  - Plugin implementation requirements
  - Post-ingest validation examples
  
- **VALIDATION_MANUAL_FLOW.md** - Manual validation workflow
  - Running validation locally and in production
  - Available validation scripts
  - Interpreting validation results
  - Maintaining golden sets for regression detection

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Pipeline Orchestrator                        │
│  (coordinates stages, handles resumption, tracks progress)       │
└─────────────────────────────────────────────────────────────────┘
         │              │              │              │              │
         ▼              ▼              ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
    │Download │──▶│  Parse  │──▶│Transform│──▶│  Load   │──▶│Validate │
    │ Stage   │   │  Stage  │   │  Stage  │   │  Stage  │   │  Stage  │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘
         │              │              │              │              │
         ▼              ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Source Registry (DB)                          │
│  (tracks: URL, status, errors, records, timing, version)        │
└─────────────────────────────────────────────────────────────────┘
```

## Related Code

### Core Framework
- **Orchestrator:** `lib/ingest/orchestrator.py` - Coordinates pipeline stages
- **Base Plugin:** `lib/ingest/base.py` - Base class for all ingest plugins
- **Registry:** `lib/ingest/registry.py` - Plugin registry and discovery
- **Versioning:** `lib/ingest/versioning.py` - Version management and rollback

### Plugins
- **DOL LCA:** `lib/ingest/plugins/dol_lca.py` - H-1B LCA data ingest
- **DOL PERM:** `lib/ingest/plugins/dol_perm.py` - PERM green card data ingest
- **Visa Bulletin:** `lib/ingest/plugins/visa_bulletin.py` - Visa Bulletin parsing
- **Salary Validation:** `lib/ingest/plugins/salary_validation.py` - Shared validation logic

### Models
- **Ingest Models:** `models/ingest/` - DataSource, IngestRun, IngestVersion
- **Enums:** `models/enums/` - DataDomain, SourceType, IngestStatus, ActionType

### Scripts
- **Ingest Scripts:** `scripts/ingest/` - Scripts for running ingest pipelines
- **Validation Scripts:** `scripts/salary/validate_data.py` - Manual validation

## Quick Start

### Create a New Ingest Plugin

```python
# lib/ingest/plugins/my_plugin.py
from lib.ingest.base import IngestPlugin
from models.ingest import DataDomain, SourceType

class MyPlugin(IngestPlugin):
    domain = DataDomain.DOL  # or DataDomain.VISA_BULLETIN
    source_type = SourceType.MY_TYPE
    
    def download(self, source, run):
        """Download data from source URL"""
        pass
    
    def parse(self, source, run):
        """Parse downloaded file"""
        pass
    
    def transform(self, parsed_data, source, run):
        """Transform parsed data to model instances"""
        pass
    
    def validate_post_ingest(self, run):
        """Validate data after ingestion"""
        return ValidationResult(passed=True, errors=[], warnings=[])
```

### Run Ingest Pipeline

```bash
# Run DOL LCA ingest
bazel run //scripts/ingest:run_dol_lca_ingest

# Run with specific files
bazel run //scripts/ingest:run_dol_lca_ingest -- --files data/salary/dol_data/LCA_FY2024.xlsx

# Resume from checkpoint
bazel run //scripts/ingest:run_dol_lca_ingest -- --resume
```

### Validate Ingested Data

```bash
# Run comprehensive validation
bazel run //scripts/salary:validate_data

# Run only post-ingest validation
bazel run //scripts/salary:validate_data -- --post-ingest-only
```

## Key Concepts

### Checkpoint/Resume
- Pipeline stores checkpoints after each stage completion
- Can resume from last checkpoint on failure or interruption
- Checkpoint includes: file path, last processed row, current stage, ETA

### Versioning
- Each successful ingest creates a new `IngestVersion`
- Versions can be activated/deactivated for rollback
- Old versions can be archived or deleted

### Validation
- Runs automatically after load stage completes
- Plugins implement `validate_post_ingest()` to check data quality
- Errors abort pipeline, warnings are logged only
- See VALIDATION_FRAMEWORK.md for details

### Rejection Tracking
- Pipeline tracks why records are rejected during transform stage
- Each `IngestRun` stores rejection statistics in `IngestRejectionStats`
- Tracks counts per rejection reason with sample case numbers
- Helps identify data quality issues and format mismatches

**Query rejection stats:**
```python
# Get rejection stats for a run
run = IngestRun.objects.get(id=504)
for stat in run.rejection_stats.all().order_by('-count'):
    print(f"{stat.get_reason_display()}: {stat.count:,} records")
    print(f"  Sample case numbers: {stat.sample_case_numbers}")
```

**Common rejection reasons:**
- `missing_case_number` - No case number in record
- `missing_employer_name` - Employer name is null/empty
- `unknown_employer_name` - Employer name is "Unknown"
- `missing_job_title` - Job title is null/empty
- `missing_wage_data` - No wage information provided

## Performance Optimization

- **Batched Streaming:** Process large files in chunks (memory efficient)
- **Prefiltering:** Skip already-imported records before transformation
- **Bulk Operations:** Use `bulk_create` / `bulk_update` for database operations
- **Adaptive Batching:** Adjust batch size based on performance metrics

See PIPELINE_DESIGN.md for complete performance optimization strategies.


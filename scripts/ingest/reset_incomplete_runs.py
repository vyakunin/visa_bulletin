#!/usr/bin/env python3
"""
Reset IngestRuns for files that had incomplete records so they can be re-imported.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
import django

django.setup()

from django.db.models import Q

from models.ingest.enums import IngestStage, IngestStatus
from models.ingest.ingest_run import IngestRun


def reset_runs():
    print("🔄 Resetting IngestRuns for re-import...")

    # Files to reset
    # 1. PERM_FY2008 (had missing job titles)
    # 2. All Worksite files (had missing locations/job titles)

    runs_to_reset = IngestRun.objects.filter(
        Q(source__url__icontains="PERM_FY2008")
        | Q(source__url__icontains="Worksite")
        | Q(checkpoint__icontains="PERM_FY2008")
        | Q(checkpoint__icontains="Worksite")
    ).exclude(
        status=IngestStatus.PENDING  # Don't reset if already pending
    )

    count = runs_to_reset.count()
    print(f"   Found {count} runs to reset")

    if count > 0:
        # For duplicates (multiple runs for same file), we might want to keep only one and delete others
        # But simpler to just mark them all failed except the latest one which we set to pending?
        # Actually, if we set them all to pending, the orchestrator might run them all.
        # Better strategy: Delete all previous runs for these files and create NEW pending runs (or reset the latest).

        # Let's delete them to be safe and let the orchestrator discover them as new?
        # No, orchestrator checks DataSource.
        # If we delete IngestRuns, the orchestrator will see the DataSource has no recent run?
        # Let's check orchestrator logic. Usually it finds DataSources that need running.

        # Safe approach: Set status to CANCELLED for all, then the Orchestrator (if run with --discover) might pick them up?
        # Or we can manually create new Pending runs for these sources.

        print("   Marking old runs as CANCELLED...")
        runs_to_reset.update(status=IngestStatus.CANCELLED)

        # Find the DataSources and create new runs
        sources = set(run.source for run in runs_to_reset)
        print(f"   Creating new PENDING runs for {len(sources)} sources...")

        new_runs = []
        for source in sources:
            new_runs.append(
                IngestRun(
                    source=source,
                    status=IngestStatus.PENDING,
                    stage=IngestStage.PENDING,
                    checkpoint={},
                )
            )

        IngestRun.objects.bulk_create(new_runs)
        print(f"   ✅ Created {len(new_runs)} new PENDING runs")


if __name__ == "__main__":
    reset_runs()

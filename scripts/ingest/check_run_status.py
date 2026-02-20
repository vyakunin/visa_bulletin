#!/usr/bin/env python3
"""Check status of IngestRuns for problematic files"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
import django

django.setup()

from models.ingest.ingest_run import IngestRun

problematic_files = [
    "H-1B_Disclosure_Data_FY2019.xlsx",
    "LCA_Worksites_FY2022_Q4.xlsx",
    "LCA_Worksites_FY2024_Q4.xlsx",
    "LCA_Worksites_FY2023_Q4.xlsx",
    "LCA_Worksites_FY2021.xlsx",
    "LCA_Disclosure_Data_FY2024_Q3.xlsx",
]

print("Checking IngestRun status for problematic files:")
for filename in problematic_files:
    # Find runs associated with this file
    # Note: DataSource stores URL, but IngestRun might store filename in checkpoint or metadata
    # Or we look for runs where the source URL contains the filename

    runs = IngestRun.objects.filter(source__url__icontains=filename).order_by(
        "-started_at"
    )

    if not runs.exists():
        # Try checking checkpoint for filepath
        runs = IngestRun.objects.filter(checkpoint__icontains=filename).order_by(
            "-started_at"
        )

    print(f"\nFile: {filename}")
    if runs.exists():
        for run in runs:
            print(
                f"  Run {run.id}: Status={run.get_status_display()}, Stage={run.get_stage_display()}"
            )
            print(f"  Checkpoint: {run.checkpoint}")
    else:
        print("  No runs found")

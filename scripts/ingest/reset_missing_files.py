
import os
from pathlib import Path

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.ingest.data_source import DataSource
from models.ingest.enums import IngestStatus
from models.salary import SalaryRecord, WorksiteRecord


def reset_missing_files():
    sources = DataSource.objects.all()
    print(f"Checking {sources.count()} sources...")

    reset_count = 0

    for source in sources:
        # Check if source has completed runs
        completed_runs = source.runs.filter(status=IngestStatus.COMPLETED)
        if not completed_runs.exists():
            # No completed runs, it's already pending (or failed/running)
            continue

        # Get filename
        if not source.local_file_path:
            # Skip if no local file (can't verify)
            continue

        filename = Path(source.local_file_path).name

        # Check if data exists in DB
        salary_count = SalaryRecord.objects.filter(source_file=filename).count()
        worksite_count = WorksiteRecord.objects.filter(source_file=filename).count()
        total_records = salary_count + worksite_count

        if total_records == 0:
            print(f"Source {filename} (ID: {source.id}) has completed runs but NO records in DB. Resetting runs.")
            # Mark runs as FAILED so they are picked up by all_pending (which excludes sources with COMPLETED runs)
            # Actually, delete them or mark failed.
            # If we mark as FAILED, all_pending logic:
            # sources_with_completed = set(DataSource.objects.filter(runs__status=IngestStatus.COMPLETED)...)
            # So if we change status to FAILED, it won't be in sources_with_completed.
            completed_runs.update(status=IngestStatus.FAILED, error_message="Reset by reset_missing_files script: No records in DB")
            reset_count += 1
        else:
            # print(f"Source {filename} has {total_records} records. OK.")
            pass

    print(f"Reset {reset_count} sources.")

if __name__ == "__main__":
    reset_missing_files()


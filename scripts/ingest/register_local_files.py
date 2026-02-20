import os
import re
from pathlib import Path

import django
from django.utils import timezone

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, FormatVersion, SourceType


def register_local_files():
    # Use BUILD_WORKSPACE_DIRECTORY if available to find the real source root
    workspace_dir = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    data_dir = workspace_dir / "data/salary/dol_data"

    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        return

    xlsx_files = list(data_dir.glob("**/*.xlsx"))
    print(f"Found {len(xlsx_files)} Excel files in {data_dir}")

    created_count = 0
    skipped_count = 0

    for file_path in xlsx_files:
        filename = file_path.name

        # Determine source type
        if filename.upper().startswith("PERM"):
            source_type = SourceType.PERM
        elif (
            filename.upper().startswith("H-1B")
            or filename.upper().startswith("LCA")
            or filename.upper().startswith("ICERT")
        ):
            source_type = SourceType.LCA
        else:
            print(f"Skipping unknown file type: {filename}")
            continue

        # Determine format version (simple heuristic)
        fiscal_year_match = re.search(r"FY(\d{4})", filename, re.IGNORECASE)
        format_version = FormatVersion.UNKNOWN
        if fiscal_year_match:
            fiscal_year = int(fiscal_year_match.group(1))
            if fiscal_year < 2015:
                format_version = FormatVersion.LEGACY
            else:
                format_version = FormatVersion.MODERN

        # Construct a unique URL for the local file
        # We use file:// scheme to indicate it's local
        url = f"file://{filename}"

        # Check if source exists (by URL or by local_file_path)
        # Note: We can't easily check if an existing https:// source corresponds to this file
        # without inspecting the file or having a map.
        # But since we want to ensure THESE specific files are ingested, we register them.
        # The pipeline handles record deduplication via case_number.

        # Check if this exact file is already registered as a local path
        existing = DataSource.objects.filter(
            local_file_path=str(file_path.absolute())
        ).first()
        if existing:
            print(f"Source already exists for {filename} (ID: {existing.id})")
            skipped_count += 1
            continue

        # Check if URL exists
        existing_url = DataSource.objects.filter(url=url).first()
        if existing_url:
            print(f"Source already exists for URL {url} (ID: {existing_url.id})")
            # Update local path just in case
            existing_url.local_file_path = str(file_path.absolute())
            existing_url.downloaded_at = timezone.now()
            existing_url.save()
            skipped_count += 1
            continue

        # Create new source
        DataSource.objects.create(
            url=url,
            domain=DataDomain.DOL,
            source_type=source_type,
            format_version=format_version,
            local_file_path=str(file_path.absolute()),
            downloaded_at=timezone.now(),
            metadata={"registered_from_local": True, "filename": filename},
        )
        print(f"Registered new source: {filename}")
        created_count += 1

    print(
        f"Finished registration. Created: {created_count}, Skipped/Updated: {skipped_count}"
    )


if __name__ == "__main__":
    register_local_files()

#!/usr/bin/env python3
"""
Extract one sample row from each DoL file for smoke test.

Usage:
    bazel run //scripts/ingest:extract_smoke_test_samples > tests/data/dol_smoke_test_samples.yaml
"""

import os
import sys

import yaml

# Setup Django
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from lib.utils.excel_utils import read_excel_streaming
from lib.utils.http_utils import get_workspace_dir


def categorize_file(filename: str) -> dict:
    """Categorize file type and expected output"""
    filename_lower = filename.lower()

    if "appendix" in filename_lower:
        return {
            "type": "appendix_a",
            "expect": "none",
            "description": "Appendix A (exempt workers metadata)",
        }
    elif "worksite" in filename_lower:
        return {
            "type": "worksite",
            "expect": "worksite_record",
            "description": "Worksite locations (I-200 cases)",
        }
    elif "perm" in filename_lower:
        return {
            "type": "perm",
            "expect": "salary_record",
            "description": "PERM labor certification",
        }
    else:
        return {
            "type": "lca",
            "expect": "salary_record",
            "description": "LCA H-1B disclosure",
        }


def extract_samples():
    """Extract one sample row from each DoL file"""
    workspace_dir = get_workspace_dir()
    data_dir = workspace_dir / "data" / "salary" / "dol_data"

    samples = []

    for filepath in sorted(data_dir.glob("*.xlsx")):
        print(f"Extracting sample from {filepath.name}...", file=sys.stderr)

        category = categorize_file(filepath.name)

        try:
            # Get first data row
            for row in read_excel_streaming(filepath, start_row=1):
                # Convert to serializable format (limit field values to avoid huge YAML)
                sample_data = {}
                for k, v in row.items():
                    if v is None:
                        sample_data[k] = None
                    else:
                        str_val = str(v)
                        # Truncate very long values
                        sample_data[k] = (
                            str_val[:200] if len(str_val) > 200 else str_val
                        )

                samples.append(
                    {
                        "filename": filepath.name,
                        "type": category["type"],
                        "expect": category["expect"],
                        "description": category["description"],
                        "sample_row": sample_data,
                    }
                )
                break  # Only take first row
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            samples.append(
                {
                    "filename": filepath.name,
                    "type": category["type"],
                    "expect": category["expect"],
                    "description": category["description"],
                    "error": str(e),
                }
            )

    # Output as YAML
    print(yaml.dump(samples, default_flow_style=False, allow_unicode=True))


if __name__ == "__main__":
    extract_samples()

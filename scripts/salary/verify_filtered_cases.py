#!/usr/bin/env python3
"""Verify that filtered-out cases are correctly annotated."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Django setup must be before model imports
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

import yaml

from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from lib.utils.http_utils import get_workspace_dir


def main():
    workspace = get_workspace_dir()
    test_data_file = workspace / "tests" / "data" / "dol_golden_test_data.yaml"

    with open(test_data_file) as f:
        data = yaml.safe_load(f)

    test_cases = data.get("test_cases", [])

    # Find filtered-out cases
    filtered_cases = [
        tc
        for tc in test_cases
        if tc.get("record_type") is None and tc.get("expected_error")
    ]

    print(f"Found {len(filtered_cases)} filtered-out cases\n")
    print("Spot-checking 10 random cases to verify they're correctly filtered:\n")

    import random

    random.seed(42)
    sample = random.sample(filtered_cases, min(10, len(filtered_cases)))

    for i, test_case in enumerate(sample, 1):
        plugin_type = test_case.get("plugin_type")
        input_dict = test_case.get("input", {})
        source_file = test_case.get("source_file", "unknown")
        row_number = test_case.get("row_number", "unknown")
        expected_error = test_case.get("expected_error", "")

        # Create plugin
        if plugin_type == "PERM":
            plugin = PERMSalaryDataSourcePlugin(skip_clustering=True)
        elif plugin_type == "H1B":
            plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
        else:
            print(f"Case {i}: Unknown plugin_type: {plugin_type}")
            continue

        # Run transform
        try:
            result = plugin.transform(input_dict)
        except Exception as e:
            print(f"\n{'=' * 80}")
            print(f"Case {i}: {source_file}:{row_number} (plugin: {plugin_type})")
            print(f"❌ Exception occurred: {e}")
            print(f"Expected error: {expected_error}")
            print(f"Input keys: {list(input_dict.keys())[:10]}")
            continue

        # Verify result matches expectation
        print(f"\n{'=' * 80}")
        print(f"Case {i}: {source_file}:{row_number} (plugin: {plugin_type})")
        print(f"Expected: None (error: {expected_error})")
        print(f"Actual: {type(result).__name__ if result else 'None'}")

        # Check why it was filtered
        case_number = (
            input_dict.get("CASE_NUMBER")
            or input_dict.get("LCA_CASE_NUMBER")
            or input_dict.get("CASE_NO", "")
        )
        employer_name = (
            input_dict.get("EMPLOYER_NAME")
            or input_dict.get("LCA_CASE_EMPLOYER_NAME")
            or input_dict.get("NAME", "")
        )
        wage_from = (
            input_dict.get("WAGE_RATE_OF_PAY_FROM")
            or input_dict.get("LCA_CASE_WAGE_RATE_FROM")
            or input_dict.get("WAGE_RATE_1", "")
        )

        print(f"  Case number: {case_number[:50] if case_number else 'MISSING'}")
        print(f"  Employer name: {employer_name[:50] if employer_name else 'MISSING'}")
        print(f"  Wage from: {wage_from if wage_from else 'MISSING'}")

        if result is None:
            print("  ✅ Correctly filtered out")
        else:
            print(f"  ❌ Should be filtered but got {type(result).__name__}")
            print("  This is a test failure - annotation is wrong!")


if __name__ == "__main__":
    main()

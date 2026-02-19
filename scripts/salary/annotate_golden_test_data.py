#!/usr/bin/env python3
"""
Helper script to annotate golden test data with expected results.

For each test case, runs transform() and shows the result, making it easier
to manually annotate expected_result and record_type fields.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Django setup
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
import django

django.setup()

import yaml

from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from lib.utils.http_utils import get_workspace_dir
from models.salary import SalaryRecord, WorksiteRecord


def main():
    workspace = get_workspace_dir()
    test_data_file = workspace / 'tests' / 'data' / 'dol_golden_test_data.yaml'

    with open(test_data_file) as f:
        data = yaml.safe_load(f)

    test_cases = data.get('test_cases', [])

    print(f"Processing {len(test_cases)} test cases...\n")

    annotated_count = 0
    unannotated_count = 0

    for i, test_case in enumerate(test_cases, 1):
        plugin_type = test_case.get('plugin_type')
        record_type = test_case.get('record_type')
        input_dict = test_case.get('input', {})
        source_file = test_case.get('source_file', 'unknown')
        row_number = test_case.get('row_number', 'unknown')

        if record_type:
            annotated_count += 1
            continue

        unannotated_count += 1

        # Create plugin
        if plugin_type == 'PERM':
            plugin = PERMSalaryDataSourcePlugin(skip_clustering=True)
        elif plugin_type == 'H1B':
            plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
        else:
            print(f"Case {i}: Unknown plugin_type: {plugin_type}")
            continue

        # Run transform
        try:
            result = plugin.transform(input_dict)
        except Exception as e:
            print(f"\n{'='*80}")
            print(f"Case {i}: {source_file}:{row_number} (plugin: {plugin_type})")
            print(f"ERROR: {e}")
            print(f"Input keys: {list(input_dict.keys())[:10]}...")
            print("\nSuggested annotation:")
            print("  record_type: null  # Error occurred")
            print(f"  expected_error: \"{str(e)}\"")
            continue

        # Show result
        print(f"\n{'='*80}")
        print(f"Case {i}: {source_file}:{row_number} (plugin: {plugin_type})")

        if result is None:
            print("Result: None (record filtered out)")
            print("\nSuggested annotation:")
            print("  record_type: null")
            print("  expected_error: \"Record filtered out (missing required data)\"")
        elif isinstance(result, SalaryRecord):
            print("Result: SalaryRecord")
            print(f"  Case number: {result.case_number}")
            print(f"  Employer: {result.employer_name}")
            print(f"  Wage annual: {result.wage_annual}")
            print("\nSuggested annotation:")
            print("  record_type: SalaryRecord")
            print("  expected_result:")
            result_dict = result.to_dict()
            # Show key fields
            for key in ['case_number', 'visa_program', 'employer_name', 'wage_annual', 'job_title']:
                if key in result_dict:
                    print(f"    {key}: {result_dict[key]!r}")
            print("  # ... (add full to_dict() output)")
        elif isinstance(result, WorksiteRecord):
            print("Result: WorksiteRecord")
            print(f"  Case number: {result.case_number}")
            print(f"  Worksite: {result.worksite_city}, {result.worksite_state}")
            print(f"  Wage annual: {result.wage_annual}")
            print("\nSuggested annotation:")
            print("  record_type: WorksiteRecord")
            print("  expected_result:")
            result_dict = result.to_dict()
            # Show key fields
            for key in ['case_number', 'visa_program', 'worksite_city', 'worksite_state', 'wage_annual']:
                if key in result_dict:
                    print(f"    {key}: {result_dict[key]!r}")
            print("  # ... (add full to_dict() output)")
        else:
            print(f"Result: {type(result).__name__} (unexpected type)")

    print(f"\n{'='*80}")
    print(f"Summary: {annotated_count} annotated, {unannotated_count} unannotated")
    print("\nTo annotate, copy the suggested annotations above into the YAML file.")


if __name__ == '__main__':
    main()


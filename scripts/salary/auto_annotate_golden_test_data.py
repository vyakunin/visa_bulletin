#!/usr/bin/env python3
"""
Automatically annotate golden test data by running transform() on each case.

Updates the YAML file with record_type, expected_result, and expected_error fields.
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
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from models.salary import SalaryRecord, WorksiteRecord
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import ScriptLogger

logger = ScriptLogger(__file__)

def auto_annotate_case(test_case: dict, plugin_type: str) -> dict:
    """
    Run transform() on a test case and return annotation.
    
    Returns:
        dict with record_type, expected_result, expected_error fields
    """
    input_dict = test_case.get('input', {})
    
    # Create plugin
    if plugin_type == 'PERM':
        plugin = PERMSalaryDataSourcePlugin(skip_clustering=True)
    elif plugin_type == 'H1B':
        plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
    else:
        return {
            'record_type': None,
            'expected_error': f"Unknown plugin_type: {plugin_type}"
        }
    
    # Run transform
    try:
        result = plugin.transform(input_dict)
    except Exception as e:
        return {
            'record_type': None,
            'expected_error': str(e)
        }
    
    # Handle result
    if result is None:
        return {
            'record_type': None,
            'expected_error': "Record filtered out (missing required data)"
        }
    elif isinstance(result, SalaryRecord):
        result_dict = result.to_dict()
        # Remove employer_id (varies due to get_or_create)
        result_dict.pop('employer_id', None)
        # to_dict() now handles enum serialization automatically
        return {
            'record_type': 'SalaryRecord',
            'expected_result': result_dict,
            'expected_error': None
        }
    elif isinstance(result, WorksiteRecord):
        result_dict = result.to_dict()
        # to_dict() now handles enum serialization automatically
        return {
            'record_type': 'WorksiteRecord',
            'expected_result': result_dict,
            'expected_error': None
        }
    else:
        return {
            'record_type': None,
            'expected_error': f"Unexpected result type: {type(result).__name__}"
        }

def main():
    workspace = get_workspace_dir()
    test_data_file = workspace / 'tests' / 'data' / 'dol_golden_test_data.yaml'
    
    # Load existing data
    with open(test_data_file, 'r') as f:
        data = yaml.safe_load(f)
    
    test_cases = data.get('test_cases', [])
    
    logger.log_call(
        args={'total_cases': len(test_cases)},
        context='Auto-annotating golden test data'
    )
    
    print(f"Processing {len(test_cases)} test cases...\n")
    
    annotated_count = 0
    skipped_count = 0
    error_count = 0
    
    for i, test_case in enumerate(test_cases, 1):
        plugin_type = test_case.get('plugin_type')
        source_file = test_case.get('source_file', 'unknown')
        row_number = test_case.get('row_number', 'unknown')
        
        # Skip if already annotated
        if test_case.get('record_type') is not None:
            skipped_count += 1
            if i % 100 == 0:
                print(f"Progress: {i}/{len(test_cases)} (skipped {skipped_count} already annotated)")
            continue
        
        # Auto-annotate
        try:
            annotation = auto_annotate_case(test_case, plugin_type)
            
            # Update test case
            test_case['record_type'] = annotation.get('record_type')
            test_case['expected_result'] = annotation.get('expected_result')
            test_case['expected_error'] = annotation.get('expected_error')
            
            annotated_count += 1
            
            if i % 50 == 0:
                print(f"Progress: {i}/{len(test_cases)} (annotated {annotated_count}, skipped {skipped_count})")
        except Exception as e:
            error_count += 1
            print(f"Error annotating case {i} ({source_file}:{row_number}): {e}")
            test_case['record_type'] = None
            test_case['expected_error'] = f"Annotation error: {str(e)}"
    
    # Save updated data
    print(f"\nSaving annotated data to {test_data_file}...")
    with open(test_data_file, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    print(f"\n{'='*80}")
    print(f"Summary:")
    print(f"  Total cases: {len(test_cases)}")
    print(f"  Annotated: {annotated_count}")
    print(f"  Skipped (already annotated): {skipped_count}")
    print(f"  Errors: {error_count}")
    print(f"\nSaved to: {test_data_file}")

if __name__ == '__main__':
    main()


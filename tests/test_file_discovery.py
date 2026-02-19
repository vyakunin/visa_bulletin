"""
Tests for file discovery mechanism.

Verifies that all DOL files are correctly detected as PERM, H1B, or unknown.

Quick unit tests test the detection logic with mock headers (no file I/O).
Integration test verifies against all actual files in dol_data.
"""

import pytest

from lib.utils.excel_utils import read_excel_headers
from lib.utils.http_utils import get_workspace_dir
from scripts.salary.collect_dol_golden_test_data import detect_file_type


@pytest.mark.parametrize("headers,expected_type", [
    # PERM files - have PERM-specific columns
    (['WAGE_OFFER_FROM_9089', 'EMPLOYER_NAME', 'CASE_NUMBER'], 'PERM'),
    (['WAGE_OFFERED_FROM_9089', 'JOB_OPP_WAGE_FROM', 'PW_JOB_TITLE_9089'], 'PERM'),
    (['WAGE_OFFER_FROM', 'WAGE_OFFER_TO', 'PW_SOC_CODE'], 'PERM'),

    # H1B files - have LCA-specific columns
    (['LCA_CASE_NUMBER', 'LCA_CASE_WAGE_RATE_FROM', 'EMPLOYER_NAME'], 'H1B'),
    (['LCA_CASE_NUMBER', 'VISA_CLASS', 'EMPLOYER_NAME'], 'H1B'),
    (['CASE_NUMBER', 'VISA_CLASS', 'EMPLOYMENT_START_DATE'], 'H1B'),

    # Worksite files - CASE_NUMBER + WAGE + WORKSITE (no employer)
    (['CASE_NUMBER', 'WAGE_RATE_OF_PAY_FROM', 'WORKSITE_CITY', 'WORKSITE_STATE'], 'H1B'),
    (['CASE_NUMBER', 'WAGE_RATE_OF_PAY_FROM', 'WORK_CITY', 'WORK_STATE'], 'H1B'),

    # Fallback: CASE_NUMBER + WAGE + employer = H1B
    (['CASE_NUMBER', 'WAGE_RATE_FROM', 'EMPLOYER_NAME'], 'H1B'),

    # Unknown files - Appendix A (no wage/employer/worksite indicators)
    (['CASE_NUMBER', 'APPX_A_NO_OF_EXEMPT_WORKERS', 'APPX_A_NAME_OF_INSTITUTION'], None),
    (['CASE_NUMBER', 'APPX_A_FIELD_OF_STUDY', 'APPX_A_DATE_OF_DEGREE'], None),

    # Unknown files - no clear indicators
    (['CASE_NUMBER'], None),  # No wage fields
    ([], None),  # Empty headers
])
def test_detect_file_type_from_headers(headers, expected_type):
    """Quick unit test for file type detection logic."""
    detected = detect_file_type(headers)
    assert detected == expected_type, \
        f"Expected {expected_type}, got {detected} for headers: {headers[:5]}"


@pytest.mark.integration  # Slower test that reads actual files
def test_all_files_discovered():
    """
    Integration test: Verify that all files in dol_data are discovered correctly.
    
    Expected:
    - All files should be detected as PERM, H1B, or unknown
    - Only Appendix A files should be unknown (6 files)
    - No files should cause errors during detection
    """
    workspace = get_workspace_dir()
    dol_data_dir = workspace / 'data' / 'salary' / 'dol_data'

    if not dol_data_dir.exists():
        pytest.skip("dol_data directory not found")

    # Find all Excel files
    excel_files = sorted(dol_data_dir.glob('*.xlsx'))

    assert len(excel_files) > 0, "No Excel files found in dol_data"

    # Test detection on each file
    perm_files = []
    h1b_files = []
    unknown_files = []
    error_files = []

    for filepath in excel_files:
        try:
            headers = read_excel_headers(filepath)
            detected = detect_file_type(headers)

            if detected == 'PERM':
                perm_files.append(filepath.name)
            elif detected == 'H1B':
                h1b_files.append(filepath.name)
            else:
                unknown_files.append(filepath.name)
        except Exception as e:
            error_files.append((filepath.name, str(e)))

    # Verify no errors
    assert len(error_files) == 0, \
        f"Files with errors: {error_files}"

    # Verify all files are accounted for
    total_detected = len(perm_files) + len(h1b_files) + len(unknown_files)
    assert total_detected == len(excel_files), \
        f"Not all files processed: {total_detected}/{len(excel_files)}"

    # Verify only Appendix A files are unknown
    appendix_files = [f for f in unknown_files if 'Appendix' in f or 'APPX' in f]
    assert len(appendix_files) == len(unknown_files), \
        f"Non-Appendix files are unknown: {set(unknown_files) - set(appendix_files)}"

    # Verify expected count (6 Appendix A files)
    assert len(unknown_files) == 6, \
        f"Expected 6 unknown files (Appendix A), got {len(unknown_files)}: {unknown_files}"

    # Verify reasonable distribution
    assert len(perm_files) > 0, "No PERM files detected"
    assert len(h1b_files) > 0, "No H1B files detected"

    # Coverage should be high (all except Appendix A)
    coverage = (len(perm_files) + len(h1b_files)) / len(excel_files) * 100
    assert coverage >= 90, \
        f"Coverage too low: {coverage:.1f}% (expected >= 90%)"


def test_appendix_files_detected_as_unknown():
    """Quick unit test: Verify Appendix A file headers are detected as unknown."""
    # Appendix A files have these headers (no wage/employer/worksite)
    appendix_headers = [
        'CASE_NUMBER',
        'APPX_A_NO_OF_EXEMPT_WORKERS',
        'APPX_A_NAME_OF_INSTITUTION',
        'APPX_A_FIELD_OF_STUDY',
        'APPX_A_DATE_OF_DEGREE'
    ]

    detected = detect_file_type(appendix_headers)
    assert detected is None, \
        f"Appendix A files should be unknown, got {detected}"

    # Verify they don't have salary/worksite indicators
    headers_upper = [h.upper() for h in appendix_headers]
    has_wage = any('WAGE' in h for h in headers_upper)
    has_employer = any('EMPLOYER' in h for h in headers_upper)
    has_worksite = any('WORKSITE' in h or 'WORK_CITY' in h for h in headers_upper)

    assert not has_wage, "Appendix A files should not have wage fields"
    assert not has_employer, "Appendix A files should not have employer fields"
    assert not has_worksite, "Appendix A files should not have worksite fields"


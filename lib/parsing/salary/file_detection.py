"""
File type detection utilities for salary data import.

Distinguishes between different DOL file formats:
- Regular LCA/PERM files (employer-focused)
- Worksite files (location-focused)
"""

# Column mappings for worksite files (shared with plugin)
# Note: Worksite files have NO employer fields - they focus on location
WORKSITE_COLUMN_MAPPINGS = {
    "case_number": ["CASE_NUMBER", "LCA_CASE_NUMBER"],
    "case_status": ["CASE_STATUS", "STATUS"],
    # No employer fields in worksite files
    "job_title": ["JOB_TITLE", "LCA_CASE_JOB_TITLE"],
    "soc_code": ["SOC_CODE", "LCA_CASE_SOC_CODE"],
    "soc_title": ["SOC_TITLE", "LCA_CASE_SOC_NAME"],
    "worksite_city": ["WORKSITE_CITY", "LCA_CASE_WORKLOC1_CITY", "WORK_CITY"],
    "worksite_state": ["WORKSITE_STATE", "LCA_CASE_WORKLOC1_STATE", "WORK_STATE"],
    "worksite_zip": ["WORKSITE_ZIP", "LCA_CASE_WORKLOC1_POSTAL_CODE", "WORK_ZIP"],
    "wage_from": [
        "WAGE_RATE_OF_PAY_FROM",
        "LCA_CASE_WAGE_RATE_FROM",
        "WAGE_RATE_OF_PAY_FROM_1",
    ],
    "wage_to": [
        "WAGE_RATE_OF_PAY_TO",
        "LCA_CASE_WAGE_RATE_TO",
        "WAGE_RATE_OF_PAY_TO_1",
    ],
    "wage_unit": ["WAGE_UNIT_OF_PAY", "LCA_CASE_WAGE_RATE_UNIT", "WAGE_UNIT_OF_PAY_1"],
    "prevailing_wage": ["PREVAILING_WAGE", "PW_WAGE_LEVEL", "PREVAILING_WAGE_1"],
    "prevailing_wage_unit": ["PW_UNIT_OF_PAY", "PW_UNIT_OF_PAY_1"],
    "case_submitted": ["RECEIVED_DATE", "LCA_CASE_SUBMIT", "CASE_SUBMITTED"],
    "decision_date": ["DECISION_DATE", "LCA_CASE_CERTIFICATION"],
    "employment_start": [
        "BEGIN_DATE",
        "LCA_CASE_EMPLOYMENT_START_DATE",
        "EMPLOYMENT_START_DATE",
    ],
    "employment_end": [
        "END_DATE",
        "LCA_CASE_EMPLOYMENT_END_DATE",
        "EMPLOYMENT_END_DATE",
    ],
}


def is_worksite_file(filename: str) -> bool:
    """
    Detect if a file is a worksite file based on filename.

    Worksite files typically contain 'worksite' or 'worksites' in the name.
    These files have a different format - they focus on worksite locations
    rather than employer information.

    Args:
        filename: Name of the file to check

    Returns:
        True if this appears to be a worksite file, False otherwise

    Examples:
        >>> is_worksite_file('LCA_Worksites_FY2022_Q4.xlsx')
        True
        >>> is_worksite_file('LCA_FY2020_Worksites.xlsx')
        True
        >>> is_worksite_file('LCA_FY2024.csv')
        False
        >>> is_worksite_file('PERM_Disclosure_Data_FY2024.xlsx')
        False
    """
    filename_lower = filename.lower()
    return "worksite" in filename_lower or "worksites" in filename_lower

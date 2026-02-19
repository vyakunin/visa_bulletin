"""Shared validation utilities for reusable queryset patterns"""

from django.db.models import Q

from models.salary import SalaryRecord


def get_missing_salary_data_queryset():
    """
    Get queryset for records with missing salary data (wage_annual is null or 0).
    
    Returns:
        QuerySet filtered for missing wage_annual values
    
    Example:
        >>> missing = get_missing_salary_data_queryset()
        >>> count = missing.count()
        >>> can_fix = missing.filter(wage_from__isnull=False, wage_unit__isnull=False)
    """
    return SalaryRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0)
    )


def get_invalid_state_queryset():
    """
    Get queryset for records with invalid state codes.
    
    Returns:
        QuerySet filtered for invalid worksite_state values
    
    Example:
        >>> from lib.utils.location_utils import VALID_STATES
        >>> invalid = get_invalid_state_queryset()
        >>> count = invalid.count()
    """
    from lib.utils.location_utils import VALID_STATES

    return SalaryRecord.objects.filter(
        worksite_state__isnull=False
    ).exclude(worksite_state__in=VALID_STATES).exclude(worksite_state='')


def get_high_wage_queryset(threshold: float = 1000000):
    """
    Get queryset for records with high wage_annual values.
    
    Args:
        threshold: Minimum wage_annual value (default: $1M)
    
    Returns:
        QuerySet filtered for high wage_annual values
    
    Example:
        >>> high_wage = get_high_wage_queryset(threshold=2000000)
        >>> count = high_wage.count()
    """
    return SalaryRecord.objects.filter(wage_annual__gt=threshold)


def get_orphaned_employers_queryset():
    """
    Get queryset for employers with no salary records.
    
    Note: This requires the Employer model. Adjust import if model location differs.
    
    Returns:
        QuerySet filtered for employers with no related salary records
    
    Example:
        >>> orphaned = get_orphaned_employers_queryset()
        >>> count = orphaned.count()
    """
    from models.salary import Employer

    return Employer.objects.filter(salary_records__isnull=True)








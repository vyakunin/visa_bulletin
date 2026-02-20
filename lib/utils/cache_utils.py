"""
Cache utility functions for invalidating cached data after imports.
"""

from django.core.cache import cache


def invalidate_salary_cache():
    """Invalidate salary-related cache after data import/update"""
    cache_keys_to_invalidate = [
        "salary_fiscal_years",
        "salary_has_data",
        "worksite_fiscal_years",
        "worksite_has_data",
    ]

    for key in cache_keys_to_invalidate:
        cache.delete(key)

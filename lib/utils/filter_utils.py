"""Generic filter application utilities for Django querysets"""

from django.db.models import Q
from models.enums.visa_program import VisaProgram


def apply_text_search_filter(queryset, query: str, fields: list[str]):
    """
    Apply case-insensitive text search across multiple fields.
    
    Args:
        queryset: Django queryset to filter
        query: Search query string
        fields: List of field names to search
        
    Returns:
        Filtered queryset
    """
    if not query:
        return queryset
    
    # Build Q objects for OR search across fields
    q_objects = Q()
    for field in fields:
        q_objects |= Q(**{f'{field}__icontains': query})
    
    return queryset.filter(q_objects)


def apply_visa_program_filter(queryset, program_filter: str, program_field: str = 'visa_program'):
    """
    Apply visa program filter to queryset.
    
    Args:
        queryset: Django queryset to filter
        program_filter: Program filter value ('h1b' or 'perm')
        program_field: Name of the visa program field (default: 'visa_program')
        
    Returns:
        Filtered queryset
    """
    if not program_filter:
        return queryset
    
    if program_filter == 'h1b':
        return queryset.filter(**{f'{program_field}__in': [VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3]})
    elif program_filter == 'perm':
        return queryset.filter(**{f'{program_field}': VisaProgram.PERM})
    
    return queryset


def apply_fiscal_year_filter(queryset, year_filter: str | int | None, year_field: str = 'fiscal_year'):
    """
    Apply fiscal year filter to queryset.
    
    Args:
        queryset: Django queryset to filter
        year_filter: Year filter value (string or int)
        year_field: Name of the fiscal year field (default: 'fiscal_year')
        
    Returns:
        Filtered queryset
    """
    if not year_filter:
        return queryset
    
    try:
        year = int(year_filter)
        return queryset.filter(**{year_field: year})
    except (ValueError, TypeError):
        return queryset










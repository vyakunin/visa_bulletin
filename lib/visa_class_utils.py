"""
Utilities for handling visa class variations

The visa bulletin has evolved over time, leading to multiple variations
of visa class names in the historical data. This module provides utilities
to handle these variations.
"""


def get_all_employment_visa_classes_from_db() -> list[str]:
    """
    Get all distinct employment-based visa classes from the database
    
    Returns:
        List of visa class strings, sorted
        
    Note: This includes all historical variations, not just enum values
    """
    from models.visa_cutoff_date import VisaCutoffDate
    
    classes = VisaCutoffDate.objects.filter(
        visa_category='employment_based'
    ).values_list('visa_class', flat=True).distinct().order_by('visa_class')
    
    return list(classes)


def get_deduplicated_employment_classes() -> list[tuple[str, str]]:
    """
    Get deduplicated employment visa classes with normalized display names
    
    Returns historical variations from database but deduplicates the display names.
    Maps each unique normalized name to a representative raw database value.
    
    Returns:
        List of (raw_value, display_name) tuples, sorted by display name
        
    Example:
        [("1st", "EB-1: Priority Workers"),
         ("2nd", "EB-2: Professionals with Advanced Degrees"),
         ...]
    """
    from models.enums.employment_preference import EmploymentPreference
    from models.visa_cutoff_date import VisaCutoffDate
    
    # Get all raw values from database
    raw_classes = VisaCutoffDate.objects.filter(
        visa_category='employment_based'
    ).values_list('visa_class', flat=True).distinct()
    
    # Build a map: normalized_display_name -> first raw value seen
    seen_displays: dict[str, str] = {}
    for raw_class in raw_classes:
        display_name = EmploymentPreference.normalize_for_display(raw_class)
        if display_name not in seen_displays:
            seen_displays[display_name] = raw_class
    
    # Convert to list of tuples and sort by display name
    result = [(raw, display) for display, raw in seen_displays.items()]
    result.sort(key=lambda x: x[1])  # Sort by display name
    
    return result


def get_all_family_visa_classes_from_db() -> list[str]:
    """
    Get all distinct family-sponsored visa classes from the database
    
    Returns:
        List of visa class strings, sorted
    """
    from models.visa_cutoff_date import VisaCutoffDate
    
    classes = VisaCutoffDate.objects.filter(
        visa_category='family_sponsored'
    ).values_list('visa_class', flat=True).distinct().order_by('visa_class')
    
    return list(classes)


def normalize_visa_class_for_display(visa_class: str) -> str:
    """
    Normalize visa class names for display
    
    DEPRECATED: Use EmploymentPreference.normalize_for_display() instead.
    This function is kept for backward compatibility but delegates to the enum.
    
    Args:
        visa_class: Raw visa class from database
        
    Returns:
        Normalized, readable name
        
    Example:
        >>> normalize_visa_class_for_display("5th Set Aside: (High Unemployment - 10%)")
        "EB-5: High Unemployment (10%)"
    """
    from models.enums.employment_preference import EmploymentPreference
    return EmploymentPreference.normalize_for_display(visa_class)


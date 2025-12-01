"""Employment-based visa preference categories"""

from django.db import models


class EmploymentPreference(models.TextChoices):
    """Employment-based preference categories"""
    
    # EB-1: Priority Workers
    EB1 = "1st", "EB-1: Priority Workers"
    
    # EB-2: Professionals with Advanced Degrees
    EB2 = "2nd", "EB-2: Professionals with Advanced Degrees"
    
    # EB-3: Skilled Workers
    EB3 = "3rd", "EB-3: Skilled Workers, Professionals"
    
    # EB-4: Special Immigrants  
    EB4 = "4th", "EB-4: Special Immigrants"
    
    # EB-5: Investor Categories
    EB5 = "5th", "EB-5: All Categories"
    
    @classmethod
    def normalize_for_display(cls, visa_class: str) -> str:
        """
        Normalize historical visa class names to consistent display format.
        This handles all the variations from old bulletins.
        
        Args:
            visa_class: Raw visa class string from database
            
        Returns:
            Normalized, user-friendly display name
        """
        # Clean up and normalize whitespace/punctuation
        clean = ' '.join(visa_class.split())  # Normalize whitespace
        clean = clean.replace(' -', '-').replace('- ', '-')  # Normalize hyphens
        clean_lower = clean.lower()
        
        # EB-1 through EB-4 (handles "1st", "1 st", etc.)
        if clean.startswith('1') or '1 st' in clean or '1st' in clean:
            return 'EB-1: Priority Workers'
        if clean.startswith('2') or '2 nd' in clean or '2nd' in clean:
            return 'EB-2: Professionals with Advanced Degrees'
        if clean.startswith('3') or '3 rd' in clean or '3rd' in clean:
            if 'other worker' in clean_lower:
                return 'EB-3: Other Workers'
            return 'EB-3: Skilled Workers, Professionals'
        if clean.startswith('4') or '4 th' in clean or '4th' in clean:
            if 'religious' in clean_lower:
                return 'EB-4: Religious Workers'
            return 'EB-4: Special Immigrants'
        
        # EB-5 variations (MANY historical formats!)
        if '5' in clean or 'eb-5' in clean_lower:
            # Check for specific EB-5 subcategories
            if 'high unemployment' in clean_lower or '(nh' in clean_lower or 'rh' in clean_lower or 'nh,' in clean_lower:
                return 'EB-5: High Unemployment (10%)'
            if 'infrastructure' in clean_lower or '(ri' in clean_lower or 'ri)' in clean_lower:
                return 'EB-5: Infrastructure (2%)'
            if 'rural' in clean_lower or '(nr' in clean_lower or 'rr' in clean_lower or 'nr,' in clean_lower:
                return 'EB-5: Rural (20%)'
            if 'unreserved' in clean_lower or 'all others' in clean_lower:
                return 'EB-5: Unreserved'
            # Targeted/Regional (multiple spelling variations!)
            if 'targeted' in clean_lower or 'regional' in clean_lower or 'employ-ment' in clean_lower or 'employmentareas' in clean_lower:
                return 'EB-5: Targeted Employment Areas / Regional Centers'
            if 'non-regional' in clean_lower:
                return 'EB-5: Non-Regional Center'
            if 'pilot' in clean_lower:
                return 'EB-5: Pilot Programs'
            # Generic EB-5
            return 'EB-5: All Categories'
        
        # Special subcategories
        if 'other worker' in clean_lower:
            return 'EB-3: Other Workers'
        if 'religious' in clean_lower:
            return 'EB-4: Religious Workers'
        if 'schedule a' in clean_lower:
            return 'Schedule A Workers'
        if 'iraqi' in clean_lower or 'afghani' in clean_lower:
            return 'Iraqi & Afghani Translators'
        
        # Single letters usually mean "Current" or "Unavailable"
        if clean in ('C', 'U'):
            return clean
        
        # Fallback: return cleaned version
        return clean

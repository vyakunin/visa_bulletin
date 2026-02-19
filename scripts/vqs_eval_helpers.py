"""
Helper functions for series-aware reporting.
"""
from statistics import mean
from datetime import date

from lib.business.vqs.accuracy_metrics import compute_bulletin_accuracy, BulletinAccuracyRow
from lib.business.vqs.meta_params import VqsMetaParams
from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate
from models.enums.country import Country


# Retrogressed series: where the model should add value over persistence
RETROGRESSED_SERIES = {
    ("2nd", Country.INDIA.value),
    ("3rd", Country.INDIA.value),
    ("2nd", Country.CHINA.value),
    ("3rd", Country.CHINA.value),
}


def is_retrogressed_series(visa_class: str, country: int) -> bool:
    """Return True if this is a heavily retrogressed series."""
    return (visa_class, country) in RETROGRESSED_SERIES


def get_bulletins_in_range(start_year: int, end_year: int) -> list[date]:
    """Return list of bulletin publication dates in [start_year, end_year)."""
    return list(
        Bulletin.objects.filter(
            publication_date__year__gte=start_year,
            publication_date__year__lt=end_year
        )
        .order_by("publication_date")
        .values_list("publication_date", flat=True)
    )


def evaluate_with_breakdown(params: VqsMetaParams, start_year: int, end_year: int) -> dict:
    """Evaluate params and return series-aware breakdown."""
    bulletins = get_bulletins_in_range(start_year, end_year)
    
    if not bulletins:
        return {"overall_mae": 0.0, "retrogressed_mae": 0.0, "other_mae": 0.0, "n_samples": 0}
    
    rows = compute_bulletin_accuracy(bulletins=bulletins, meta=params)
    
    # Split by series type
    retrogressed_rows = [r for r in rows if is_retrogressed_series(r.visa_class, r.country)]
    other_rows = [r for r in rows if not is_retrogressed_series(r.visa_class, r.country)]
    
    errors = [r.error_days for r in rows if r.error_days is not None]
    overall_mae = mean(errors) if errors else 0.0
    
    retro_errors = [r.error_days for r in retrogressed_rows if r.error_days is not None]
    retrogressed_mae = mean(retro_errors) if retro_errors else 0.0
    
    other_errors = [r.error_days for r in other_rows if r.error_days is not None]
    other_mae = mean(other_errors) if other_errors else 0.0
    
    return {
        "overall_mae": overall_mae,
        "retrogressed_mae": retrogressed_mae,
        "other_mae": other_mae,
        "n_samples": len(errors),
    }


def evaluate_persistence_baseline(start_year: int, end_year: int) -> dict:
    """Evaluate persistence baseline (predict no change) with series breakdown."""
    from lib.business.vqs.accuracy_metrics import EVALUABLE_VISA_CLASSES
    
    bulletins = get_bulletins_in_range(start_year, end_year)
    
    if not bulletins:
        return {"overall_mae": 0.0, "retrogressed_mae": 0.0, "other_mae": 0.0, "n_samples": 0}
    
    all_errors = []
    retro_errors = []
    other_errors = []
    
    for pub_date in bulletins:
        cutoffs = VisaCutoffDate.objects.filter(
            bulletin__publication_date=pub_date,
            visa_category="employment_based",
            visa_class__in=EVALUABLE_VISA_CLASSES,
        ).exclude(cutoff_date__isnull=True).select_related("bulletin")
        
        for row in cutoffs:
            prev_bulletin = Bulletin.objects.filter(
                publication_date__lt=pub_date
            ).order_by("-publication_date").first()
            
            if not prev_bulletin:
                continue
            
            prev_cutoff_row = VisaCutoffDate.objects.filter(
                bulletin=prev_bulletin,
                visa_category="employment_based",
                visa_class=row.visa_class,
                country=row.country,
                action_type=row.action_type,
            ).first()
            
            if not prev_cutoff_row or prev_cutoff_row.cutoff_date is None:
                continue
            
            error_days = abs((prev_cutoff_row.cutoff_date - row.cutoff_date).days)
            all_errors.append(error_days)
            
            if is_retrogressed_series(row.visa_class, row.country):
                retro_errors.append(error_days)
            else:
                other_errors.append(error_days)
    
    overall_mae = mean(all_errors) if all_errors else 0.0
    retro_mae = mean(retro_errors) if retro_errors else 0.0
    other_mae = mean(other_errors) if other_errors else 0.0
    
    return {
        "overall_mae": overall_mae,
        "retrogressed_mae": retro_mae,
        "other_mae": other_mae,
        "n_samples": len(all_errors),
    }

from datetime import date

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from models.enums.country import Country
from models.enums.family_preference import FamilyPreference
from models.enums.visa_category import VisaCategory
from models.vqs import PredictedBulletin


def prediction_list(request: HttpRequest) -> HttpResponse:
    """List all available historical predictions."""
    bulletins = PredictedBulletin.objects.order_by("-target_bulletin_month")

    context = {
        "bulletins": bulletins,
    }
    return render(request, "vqs/prediction_list.html", context)


import calendar

from models.bulletin import Bulletin
from models.visa_cutoff_date import VisaCutoffDate


def prediction_detail(
    request: HttpRequest, year: int, month: int, category: str = "employment_based"
) -> HttpResponse:
    """Detailed view of a specific month's data (Prediction + Bulletin)."""
    target_date = date(year, month, 1)

    # Try to find prediction
    bulletin = PredictedBulletin.objects.filter(
        target_bulletin_month=target_date
    ).first()

    # Try to find actual bulletin
    actual_bulletin = Bulletin.objects.filter(publication_date=target_date).first()

    # If neither exists, 404
    if not bulletin and not actual_bulletin:
        get_object_or_404(
            PredictedBulletin, target_bulletin_month=target_date
        )  # Trigger 404

    # Navigation context - manual month math
    def add_months(sourcedate, months):
        m = sourcedate.month - 1 + months
        y = sourcedate.year + m // 12
        mon = m % 12 + 1
        day = min(sourcedate.day, calendar.monthrange(y, mon)[1])
        return date(y, mon, day)

    # Improved navigation: find nearest available months in either table
    prev_bulletin = (
        PredictedBulletin.objects.filter(target_bulletin_month__lt=target_date)
        .order_by("-target_bulletin_month")
        .first()
    )
    prev_actual = (
        Bulletin.objects.filter(publication_date__lt=target_date)
        .order_by("-publication_date")
        .first()
    )

    next_bulletin_obj = (
        PredictedBulletin.objects.filter(target_bulletin_month__gt=target_date)
        .order_by("target_bulletin_month")
        .first()
    )
    next_actual = (
        Bulletin.objects.filter(publication_date__gt=target_date)
        .order_by("publication_date")
        .first()
    )

    # Pick the closest prev/next
    nav_prev = None
    if prev_bulletin and prev_actual:
        nav_prev = max(
            prev_bulletin.target_bulletin_month, prev_actual.publication_date
        )
    elif prev_bulletin:
        nav_prev = prev_bulletin.target_bulletin_month
    elif prev_actual:
        nav_prev = prev_actual.publication_date

    nav_next = None
    if next_bulletin_obj and next_actual:
        nav_next = min(
            next_bulletin_obj.target_bulletin_month, next_actual.publication_date
        )
    elif next_bulletin_obj:
        nav_next = next_bulletin_obj.target_bulletin_month
    elif next_actual:
        nav_next = next_actual.publication_date

    # Get previous month's actual bulletin for delta calculation
    last_actual_month = add_months(target_date, -1)
    last_actual_bulletin = Bulletin.objects.filter(
        publication_date=last_actual_month
    ).first()
    last_actual_cutoffs = {}
    if last_actual_bulletin:
        for cutoff in VisaCutoffDate.objects.filter(bulletin=last_actual_bulletin):
            key = f"{cutoff.visa_class}_{cutoff.country}_{cutoff.action_type}"
            last_actual_cutoffs[key] = cutoff.cutoff_date

    # Get current month's actual cutoffs
    current_actual_cutoffs = {}
    if actual_bulletin:
        for cutoff in VisaCutoffDate.objects.filter(bulletin=actual_bulletin):
            key = f"{cutoff.visa_class}_{cutoff.country}_{cutoff.action_type}"
            current_actual_cutoffs[key] = cutoff.cutoff_date

    if category == VisaCategory.FAMILY_SPONSORED.value:
        classes = [f[0] for f in FamilyPreference.choices]
        class_display = {f[0]: f[1].split(":")[0] for f in FamilyPreference.choices}
        category_label = "Family-Sponsored"
    else:
        classes = ["1st", "2nd", "3rd", "4th", "5th"]
        class_display = {
            "1st": "EB-1",
            "2nd": "EB-2",
            "3rd": "EB-3",
            "4th": "EB-4",
            "5th": "EB-5",
        }
        category_label = "Employment-Based"

    countries = [
        Country.ALL,
        Country.CHINA,
        Country.INDIA,
        Country.MEXICO,
        Country.PHILIPPINES,
    ]

    # Build a dense matrix
    matrix = {}
    for vc in classes:
        matrix[vc] = {}
        for c in countries:
            matrix[vc][c.value] = {
                "final_action": {"predicted": None, "actual_date": None},
                "filing": {"predicted": None, "actual_date": None},
            }

    # Populate predictions if they exist
    if bulletin:
        for cutoff in bulletin.cutoffs.all():
            if cutoff.visa_class in matrix:
                if cutoff.country in matrix[cutoff.visa_class]:
                    atype = (
                        "filing" if "filing" in cutoff.action_type else "final_action"
                    )

                    # Calculate movement delta
                    key = f"{cutoff.visa_class}_{cutoff.country}_{atype}"
                    last_actual_date = last_actual_cutoffs.get(key)
                    if last_actual_date and cutoff.predicted_date:
                        delta = (cutoff.predicted_date - last_actual_date).days
                        if delta == 0:
                            cutoff.movement_delta = "0"
                            cutoff.movement_type = "neutral"
                        elif delta >= 30:
                            cutoff.movement_delta = f"↑ {delta // 30}m"
                            cutoff.movement_type = "positive"
                        elif delta > 0:
                            cutoff.movement_delta = f"↑ {delta}d"
                            cutoff.movement_type = "positive"
                        elif delta <= -30:
                            cutoff.movement_delta = f"↓ {abs(delta) // 30}m"
                            cutoff.movement_type = "negative"
                        else:
                            cutoff.movement_delta = f"↓ {abs(delta)}d"
                            cutoff.movement_type = "negative"

                    if cutoff.predicted_date:
                        cutoff.formatted_date = cutoff.predicted_date.strftime(
                            "%d %b %Y"
                        )

                    matrix[cutoff.visa_class][cutoff.country][atype]["predicted"] = (
                        cutoff
                    )

    # Populate actual dates
    for vc in classes:
        for c in countries:
            for atype in ["final_action", "filing"]:
                key = f"{vc}_{c.value}_{atype}"
                if key in current_actual_cutoffs:
                    d = current_actual_cutoffs[key]
                    matrix[vc][c.value][atype]["actual_date"] = d
                    matrix[vc][c.value][atype]["formatted_actual"] = (
                        d.strftime("%d %b %Y") if d else None
                    )

    # Convert matrix to list of rows for template
    table_rows = []
    for vc in classes:
        row_data = {
            "class": class_display.get(vc, vc),
            "class_full": vc,
            "countries": [],
        }
        for c in countries:
            cell = matrix[vc][c.value]
            row_data["countries"].append(
                {
                    "country": c,
                    "final_action": cell["final_action"],
                    "filing": cell["filing"],
                }
            )
        table_rows.append(row_data)

    formatted_title = (
        f"{category_label} Predictions for {target_date.strftime('%B %Y')}"
        if bulletin
        else f"{category_label} Bulletin: {target_date.strftime('%B %Y')}"
    )
    formatted_nav_prev = nav_prev.strftime("%b %Y") if nav_prev else None
    formatted_nav_next = nav_next.strftime("%b %Y") if nav_next else None

    context = {
        "bulletin": bulletin,
        "actual_bulletin": actual_bulletin,
        "target_month": target_date,
        "table_rows": table_rows,
        "classes": classes,
        "countries": [c for c in countries],
        "nav_prev": nav_prev,
        "nav_next": nav_next,
        "formatted_title": formatted_title,
        "formatted_nav_prev": formatted_nav_prev,
        "formatted_nav_next": formatted_nav_next,
        "category": category,
        "category_label": category_label,
    }
    return render(request, "vqs/prediction_detail.html", context)


def spaghetti_view(request):
    """Temporary view for backtest visualization"""
    import os

    from django.conf import settings
    from django.http import HttpResponse

    # Path to the file we copied
    file_path = os.path.join(settings.BASE_DIR, "webapp", "templates", "spaghetti.html")

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    return HttpResponse(content, content_type="text/html")

from datetime import date

from django.template.loader import render_to_string
from django.utils.text import slugify

from models.blog import BlogPost
from models.bulletin import Bulletin
from models.enums.country import Country
from models.vqs import PredictedBulletin


class BulletinNarrator:
    """
    Generates human-readable narratives for Visa Bulletin updates.
    """

    def generate_post_for_bulletin(self, bulletin: Bulletin) -> BlogPost:
        """
        Main entry point. Generates a BlogPost for the given bulletin.
        """
        # 1. Gather Data
        prev_bulletin = self._get_previous_bulletin(bulletin.publication_date)
        prediction = self._get_prediction(bulletin.publication_date)

        # 2. Analyze
        movements = self._analyze_movements(bulletin, prev_bulletin)
        surprises = self._analyze_surprises(bulletin, prediction)

        # 3. Generate Content
        context = {
            "bulletin": bulletin,
            "movements": movements,
            "surprises": surprises,
            "outlook": self._generate_outlook(bulletin),
        }

        content = render_to_string("blog/templates/post_content.html", context)
        title = f"Visa Bulletin Analysis: {bulletin.publication_date.strftime('%B %Y')}"

        # 4. Create/Update Post
        post, created = BlogPost.objects.update_or_create(
            slug=slugify(title),
            defaults={
                "title": title,
                "content": content,
                "related_bulletin": bulletin,
                "is_published": True,
                "category": "Analysis",
            },
        )
        return post

    def _get_previous_bulletin(self, target_date: date) -> Bulletin | None:
        return (
            Bulletin.objects.filter(publication_date__lt=target_date)
            .order_by("-publication_date")
            .first()
        )

    def _get_prediction(self, target_date: date) -> PredictedBulletin | None:
        return PredictedBulletin.objects.filter(
            target_bulletin_month=target_date
        ).first()

    def _analyze_movements(self, current: Bulletin, previous: Bulletin | None) -> dict:
        """
        Compare current vs previous bulletin to find movement.
        Returns a dict organized by category -> list of narrative strings.
        """
        if not previous:
            return {}

        movements = {"family": [], "employment": []}

        # Helper to fetch cutoffs map: "Class_Country" -> Date
        def get_cutoffs(b):
            return {
                f"{c.visa_class}_{c.country}": c.cutoff_date
                for c in b.cutoff_dates.filter(action_type="final_action")
            }

        curr_map = get_cutoffs(current)
        prev_map = get_cutoffs(previous)

        # Define priority categories to report on
        # Format: (Visa Class, Country, Display Name)
        priority_checks = [
            ("1st", Country.CHINA, "EB-1 China"),
            ("1st", Country.INDIA, "EB-1 India"),
            ("2nd", Country.CHINA, "EB-2 China"),
            ("2nd", Country.INDIA, "EB-2 India"),
            ("2nd", Country.ALL, "EB-2 ROW"),
            ("3rd", Country.CHINA, "EB-3 China"),
            ("3rd", Country.INDIA, "EB-3 India"),
            ("3rd", Country.ALL, "EB-3 ROW"),
            ("F2A", Country.ALL, "F2A (Spouses/Children of LPR)"),
            ("F1", Country.Philippines, "F1 Philippines")
            if hasattr(Country, "Philippines")
            else ("F1", "PH", "F1 Philippines"),
        ]

        for visa_class, country, label in priority_checks:
            key = f"{visa_class}_{country}"
            curr_date = curr_map.get(key)
            prev_date = prev_map.get(key)

            if curr_date and prev_date:
                delta = (curr_date - prev_date).days
                narrative = ""
                if delta > 0:
                    narrative = f"<strong>{label}</strong> advanced by {delta} days to {curr_date.strftime('%d %b %Y')}."
                elif delta < 0:
                    narrative = f"<strong>{label}</strong> retrogressed by {abs(delta)} days to {curr_date.strftime('%d %b %Y')}."

                if narrative:
                    if visa_class.startswith("F"):
                        movements["family"].append(narrative)
                    else:
                        movements["employment"].append(narrative)

        return movements

    def _analyze_surprises(
        self, current: Bulletin, prediction: PredictedBulletin | None
    ) -> list[dict]:
        """
        Compare actual vs predicted.
        """
        if not prediction:
            return []

        surprises = []

        # Map predicted cutoffs
        pred_map = {
            f"{c.visa_class}_{c.country}": c.predicted_date
            for c in prediction.cutoffs.filter(action_type="final_action")
        }

        # Iterate actual cutoffs
        for actual in current.cutoff_dates.filter(action_type="final_action"):
            key = f"{actual.visa_class}_{actual.country}"
            pred_date = pred_map.get(key)

            if pred_date:
                delta = (actual.cutoff_date - pred_date).days

                # Threshold for surprise: > 14 days difference (arbitrary but reasonable)
                if abs(delta) > 14:
                    item = {
                        "category": actual.visa_class,
                        "country": actual.country,
                        "predicted": pred_date,
                        "actual": actual.cutoff_date,
                        "delta_days": delta,
                        "is_positive": delta > 0,  # Actual is ahead of predicted = Good
                        "delta_text": f"{'+' if delta > 0 else ''}{delta} days",
                        "narrative": "",
                    }

                    if delta > 0:
                        item["narrative"] = (
                            f"Better than expected. We predicted {pred_date} but it moved to {actual.cutoff_date}."
                        )
                    else:
                        item["narrative"] = (
                            f"Worse than expected. We predicted {pred_date} but it only reached {actual.cutoff_date}."
                        )

                    surprises.append(item)

        # Sort by magnitude of surprise
        surprises.sort(key=lambda x: abs(x["delta_days"]), reverse=True)
        return surprises[:5]  # Top 5 surprises

    def _generate_outlook(self, bulletin: Bulletin) -> str:
        return (
            "Based on the current movements, we expect continued slow progression in oversubscribed categories. "
            "Our model will update its forecast for the next fiscal year shortly."
        )

import logging
from collections import defaultdict
from datetime import date
from statistics import median

from django.template.loader import render_to_string
from django.utils.text import slugify

from models.blog import BlogPost
from models.bulletin import Bulletin
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate
from models.vqs import PredictedBulletin, PredictedCutoff

logger = logging.getLogger(__name__)

REGIME_LABELS = {
    "advancing": ("Advancing", "success"),
    "stalled": ("Stalled", "secondary"),
    "retrogressing": ("Retrogressing", "danger"),
    "recovering": ("Recovering", "info"),
    "volatile": ("Volatile", "warning"),
}

COUNTRY_DISPLAY = {
    Country.CHINA.value: "China",
    Country.INDIA.value: "India",
    Country.ALL.value: "ROW",
    Country.MEXICO.value: "Mexico",
    Country.PHILIPPINES.value: "Philippines",
}

EXPERT_DISPLAY_NAMES = {
    "persistence": "No-Change Baseline",
    "seasonal_median": "Seasonal Pattern",
    "linear_extrap": "12-Month Trend",
    "momentum_3m": "3-Month Momentum",
    "fy_reset": "Fiscal Year Cycle",
    "physics": "Queue Simulation",
    "supply_aware": "Supply-Adjusted",
    "demand_signal": "Demand Signal",
}

VISA_CLASS_DISPLAY = {
    "1st": "EB-1",
    "2nd": "EB-2",
    "3rd": "EB-3",
    "4th": "EB-4",
    "5th": "EB-5",
}

ACTION_TYPE_DISPLAY = {
    "final_action": "Final Action",
    "filing": "Filing Date",
}

PRIORITY_SERIES = [
    ("1st", Country.CHINA.value, "EB-1 China"),
    ("1st", Country.INDIA.value, "EB-1 India"),
    ("2nd", Country.CHINA.value, "EB-2 China"),
    ("2nd", Country.INDIA.value, "EB-2 India"),
    ("2nd", Country.ALL.value, "EB-2 ROW"),
    ("3rd", Country.CHINA.value, "EB-3 China"),
    ("3rd", Country.INDIA.value, "EB-3 India"),
    ("3rd", Country.ALL.value, "EB-3 ROW"),
]


def horizon_months_from_knowledge(target_month_first: date, knowledge_date: date) -> int:
    """Calendar months from knowledge date to target bulletin month (same as publish_predictions)."""
    return (
        (target_month_first.year - knowledge_date.year) * 12
        + (target_month_first.month - knowledge_date.month)
    )


def predicted_bulletin_for_blog_next_month(next_month_first: date) -> PredictedBulletin | None:
    """Pick stored predictions for the blog: prefer 1-month-ahead horizon, else newest knowledge."""
    rows = list(PredictedBulletin.objects.filter(target_bulletin_month=next_month_first))
    if not rows:
        return None
    for pb in rows:
        if horizon_months_from_knowledge(pb.target_bulletin_month, pb.prediction_date) == 1:
            return pb
    return max(rows, key=lambda r: r.prediction_date)


class BulletinNarrator:
    """Generates human-readable narratives for Visa Bulletin updates.

    Produces blog posts with:
    - Prediction surprises (actual vs predicted)
    - Key month-over-month movements
    - Data-driven outlook from VQS model metadata (regime, expert signals, pace)
    """

    def generate_post_for_bulletin(self, bulletin: Bulletin) -> BlogPost:
        prev_bulletin = self._get_previous_bulletin(bulletin.publication_date)
        prediction = self._get_prediction(bulletin.publication_date)

        movements = self._analyze_movements(bulletin, prev_bulletin)
        surprises = self._analyze_surprises(bulletin, prediction)
        ci_coverage = self._compute_ci_coverage(prediction, bulletin)
        predictions_context = self._build_predictions_context(bulletin.publication_date)
        historical_pace = self._historical_pace_context(bulletin.publication_date)
        outlook = self._generate_outlook_from_predictions(predictions_context, historical_pace)

        context = {
            "bulletin": bulletin,
            "movements": movements,
            "surprises": surprises,
            "ci_coverage": ci_coverage,
            "predictions_context": predictions_context,
            "historical_pace": historical_pace,
            "outlook": outlook,
        }

        content = render_to_string("blog/templates/post_content.html", context)
        title = f"Visa Bulletin Analysis: {bulletin.publication_date.strftime('%B %Y')}"

        post, _created = BlogPost.objects.update_or_create(
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
        # Use the most recent prediction (latest prediction_date) so we get
        # 1m-ahead predictions, not stale long-horizon ones.
        return PredictedBulletin.objects.filter(
            target_bulletin_month=target_date
        ).order_by("-prediction_date").first()

    def _compute_ci_coverage(
        self, prediction: PredictedBulletin | None, bulletin: Bulletin
    ) -> dict | None:
        """Compute CI coverage for this month's predictions vs actuals."""
        if not prediction:
            return None

        actual_map = {
            f"{c.visa_class}_{c.country}_{c.action_type}": c.cutoff_date
            for c in bulletin.cutoff_dates.all()
        }

        total = 0
        hits = 0
        widths: list[int] = []
        for cutoff in prediction.cutoffs.filter(
            confidence_low__isnull=False,
            confidence_high__isnull=False,
            predicted_date__isnull=False,
        ):
            key = f"{cutoff.visa_class}_{cutoff.country}_{cutoff.action_type}"
            actual = actual_map.get(key)
            if not actual:
                continue

            total += 1
            widths.append((cutoff.confidence_high - cutoff.confidence_low).days)
            if cutoff.confidence_low <= actual <= cutoff.confidence_high:
                hits += 1

        if total == 0:
            return None

        return {
            "total_with_ci": total,
            "hits": hits,
            "coverage_pct": round(hits / total * 100, 1),
            "mean_ci_width_days": round(sum(widths) / len(widths), 1),
        }

    def _analyze_movements(self, current: Bulletin, previous: Bulletin | None) -> dict:
        """Compare current vs previous bulletin to find movement."""
        if not previous:
            return {}

        movements = {"family": [], "employment": []}

        def get_cutoffs(b):
            # cutoff_date for "C" rows is stored as the bulletin publication_date
            # (see lib/parsing/bulletin/table_to_cutoff_data.py). Treat is_current=True
            # as "no real cutoff" so consecutive Current months don't masquerade as a
            # 30-day advance.
            return {
                f"{c.visa_class}_{c.country}": (None if c.is_current else c.cutoff_date)
                for c in b.cutoff_dates.filter(action_type="final_action")
            }

        curr_map = get_cutoffs(current)
        prev_map = get_cutoffs(previous)

        for visa_class, country_val, label in PRIORITY_SERIES:
            key = f"{visa_class}_{country_val}"
            curr_date = curr_map.get(key)
            prev_date = prev_map.get(key)

            if curr_date and prev_date:
                delta = (curr_date - prev_date).days
                narrative = ""
                if delta > 0:
                    narrative = (
                        f"<strong>{label}</strong> advanced by {delta} days "
                        f"to {curr_date.strftime('%d %b %Y')}."
                    )
                elif delta < 0:
                    narrative = (
                        f"<strong>{label}</strong> retrogressed by {abs(delta)} days "
                        f"to {curr_date.strftime('%d %b %Y')}."
                    )

                if narrative:
                    if visa_class.startswith("F"):
                        movements["family"].append(narrative)
                    else:
                        movements["employment"].append(narrative)

        return movements

    def _analyze_surprises(
        self, current: Bulletin, prediction: PredictedBulletin | None
    ) -> list[dict]:
        """Compare actual vs predicted with full context: previous cutoff, deltas, expert breakdown."""
        if not prediction:
            return []

        prev_bulletin = self._get_previous_bulletin(current.publication_date)
        prev_cutoff_map = {}
        if prev_bulletin:
            prev_cutoff_map = {
                f"{c.visa_class}_{c.country}_{c.action_type}": c.cutoff_date
                for c in prev_bulletin.cutoff_dates.all()
            }

        pred_cutoff_map = {
            f"{c.visa_class}_{c.country}_{c.action_type}": c
            for c in prediction.cutoffs.all()
        }

        surprises = []
        for actual in current.cutoff_dates.filter(action_type="final_action"):
            if not actual.cutoff_date:
                continue
            key = f"{actual.visa_class}_{actual.country}_{actual.action_type}"
            pred_cutoff = pred_cutoff_map.get(key)
            if not pred_cutoff or not pred_cutoff.predicted_date:
                continue

            pred_date = pred_cutoff.predicted_date
            miss_days = (actual.cutoff_date - pred_date).days
            if abs(miss_days) <= 14:
                continue

            prev_date = prev_cutoff_map.get(key)
            predicted_delta = (pred_date - prev_date).days if prev_date else None
            actual_delta = (actual.cutoff_date - prev_date).days if prev_date else None

            country_name = COUNTRY_DISPLAY.get(actual.country, str(actual.country))
            visa_display = VISA_CLASS_DISPLAY.get(actual.visa_class, actual.visa_class)
            action_display = ACTION_TYPE_DISPLAY.get(actual.action_type, actual.action_type)

            if miss_days > 0:
                verdict = "Underestimated advance"
            else:
                verdict = "Overestimated advance"

            expert_breakdown = self._build_expert_breakdown(
                pred_cutoff, prev_date, actual.cutoff_date
            )

            surprises.append({
                "label": f"{visa_display} {country_name}",
                "action_type": action_display,
                "category": actual.visa_class,
                "country": actual.country,
                "previous": prev_date,
                "predicted": pred_date,
                "actual": actual.cutoff_date,
                "predicted_delta": predicted_delta,
                "actual_delta": actual_delta,
                "miss_days": miss_days,
                "is_positive": miss_days > 0,
                "verdict": verdict,
                "expert_breakdown": expert_breakdown,
            })

        surprises.sort(key=lambda x: abs(x["miss_days"]), reverse=True)
        return surprises[:5]

    def _build_expert_breakdown(
        self,
        pred_cutoff: PredictedCutoff,
        previous_date: date | None,
        actual_date: date | None,
    ) -> list[dict]:
        """Build per-expert signal table from stored expert_predictions JSON."""
        raw = pred_cutoff.expert_predictions
        if not raw or not isinstance(raw, dict):
            return []

        persistence_date = None
        if "persistence" in raw and raw["persistence"].get("pred"):
            persistence_date = date.fromisoformat(raw["persistence"]["pred"])

        rows = []
        for name, data in raw.items():
            pred_str = data.get("pred")
            weight = data.get("weight", 0)
            pred_date = date.fromisoformat(pred_str) if pred_str else None

            delta_from_persistence = None
            if pred_date and persistence_date:
                delta_from_persistence = (pred_date - persistence_date).days

            delta_from_actual = None
            if pred_date and actual_date:
                delta_from_actual = (pred_date - actual_date).days

            rows.append({
                "name": name,
                "display_name": EXPERT_DISPLAY_NAMES.get(name, name),
                "predicted": pred_date,
                "weight": weight,
                "weight_pct": round(weight * 100, 1),
                "delta_from_persistence": delta_from_persistence,
                "delta_from_actual": delta_from_actual,
            })

        rows.sort(key=lambda x: x["weight"], reverse=True)
        return rows

    def _build_predictions_context(self, bulletin_date: date) -> list[dict]:
        """Load PredictedCutoff rows for the next month and extract regime + expert signals."""
        from dateutil.relativedelta import relativedelta

        next_month = bulletin_date + relativedelta(months=1)
        next_month = next_month.replace(day=1)

        pred_bulletin = predicted_bulletin_for_blog_next_month(next_month)
        if not pred_bulletin:
            return []

        series_data = []
        for visa_class, country_val, label in PRIORITY_SERIES:
            cutoff = pred_bulletin.cutoffs.filter(
                visa_class=visa_class,
                country=country_val,
                action_type="final_action",
            ).first()
            if not cutoff:
                continue

            entry = {
                "label": label,
                "visa_class": visa_class,
                "country": country_val,
                "predicted_date": cutoff.predicted_date,
                "confidence": "high" if cutoff.confidence_high else "medium",
                "explanation": cutoff.explanation_markdown or "",
            }

            # Parse regime and signals from explanation_markdown
            explanation = cutoff.explanation_markdown or ""
            if "Regime:" in explanation:
                regime_str = explanation.split("Regime:")[1].split("**")[0].strip().lower()
                entry["regime"] = regime_str
                regime_info = REGIME_LABELS.get(regime_str, (regime_str, "secondary"))
                entry["regime_label"] = regime_info[0]
                entry["regime_badge_class"] = regime_info[1]

            if cutoff.confidence_low and cutoff.confidence_high:
                entry["confidence_low"] = cutoff.confidence_low
                entry["confidence_high"] = cutoff.confidence_high
                entry["ci_spread_days"] = (cutoff.confidence_high - cutoff.confidence_low).days

            # Top-3 contributing experts by weight
            raw = cutoff.expert_predictions
            if raw and isinstance(raw, dict):
                expert_rows = []
                for exp_name, exp_data in raw.items():
                    if not isinstance(exp_data, dict):
                        continue
                    pred_str = exp_data.get("pred")
                    weight = exp_data.get("weight", 0.0)
                    pred_date = None
                    if pred_str:
                        try:
                            pred_date = date.fromisoformat(pred_str)
                        except ValueError:
                            pass
                    expert_rows.append({
                        "name": exp_name,
                        "display_name": EXPERT_DISPLAY_NAMES.get(exp_name, exp_name.replace("_", " ").title()),
                        "predicted": pred_date,
                        "weight_pct": round(weight * 100, 1),
                    })
                expert_rows.sort(key=lambda r: r["weight_pct"], reverse=True)
                expert_rows = [r for r in expert_rows if r["weight_pct"] > 0]
                entry["top_experts"] = expert_rows[:3]

            series_data.append(entry)

        return series_data

    def _historical_pace_context(self, bulletin_date: date) -> list[dict]:
        """Query last 12 months of cutoff advancement with seasonal deviation analysis.

        Instead of a raw 3-month pace (dominated by the October fiscal-year jump),
        computes how recent months deviate from their historical seasonal medians.
        """
        pace_data = []

        for visa_class, country_val, label in PRIORITY_SERIES:
            all_cutoffs = list(
                VisaCutoffDate.objects.filter(
                    visa_class=visa_class,
                    country=country_val,
                    action_type="final_action",
                    bulletin__publication_date__lte=bulletin_date,
                    cutoff_date__isnull=False,
                )
                .select_related("bulletin")
                .order_by("bulletin__publication_date")
            )

            if len(all_cutoffs) < 13:
                continue

            moves_by_month: dict[int, list[int]] = defaultdict(list)
            for i in range(1, len(all_cutoffs)):
                delta = (all_cutoffs[i].cutoff_date - all_cutoffs[i - 1].cutoff_date).days
                pub_month = all_cutoffs[i].bulletin.publication_date.month
                moves_by_month[pub_month].append(delta)

            recent_cutoffs = all_cutoffs[-13:]
            recent_moves: list[tuple[int, int]] = []
            for i in range(1, len(recent_cutoffs)):
                delta = (recent_cutoffs[i].cutoff_date - recent_cutoffs[i - 1].cutoff_date).days
                pub_month = recent_cutoffs[i].bulletin.publication_date.month
                recent_moves.append((delta, pub_month))

            avg_pace = sum(m[0] for m in recent_moves) / len(recent_moves)

            last_3 = recent_moves[-3:] if len(recent_moves) >= 3 else recent_moves
            deviations = []
            for actual_move, cal_month in last_3:
                hist = moves_by_month.get(cal_month, [])
                if len(hist) >= 3:
                    deviations.append(actual_move - median(hist))
                else:
                    deviations.append(actual_move - avg_pace)

            seasonal_dev = sum(deviations) / len(deviations) if deviations else 0.0

            pace_data.append({
                "label": label,
                "visa_class": visa_class,
                "country": country_val,
                "avg_12m_pace": round(avg_pace, 1),
                "seasonal_deviation": round(seasonal_dev, 1),
                "months_analyzed": len(recent_moves),
                "total_advance_days": sum(m[0] for m in recent_moves),
            })

        return pace_data

    def _describe_regime_signals(self, predictions_context: list[dict]) -> list[dict]:
        """Translate regime enums to plain English for each key series."""
        descriptions = []
        for entry in predictions_context:
            regime = entry.get("regime")
            if not regime:
                continue

            label = entry["label"]
            regime_label, _ = REGIME_LABELS.get(regime, (regime, "secondary"))

            if regime == "advancing":
                text = f"{label} is in an <strong>advancing</strong> pattern with consistent forward movement."
            elif regime == "stalled":
                text = f"{label} has been <strong>stalled</strong> with minimal cutoff movement."
            elif regime == "retrogressing":
                text = f"{label} is <strong>retrogressing</strong> — cutoff dates are moving backward."
            elif regime == "recovering":
                text = f"{label} is <strong>recovering</strong> from a recent retrogression period."
            elif regime == "volatile":
                text = f"{label} shows <strong>volatile</strong> behavior with unpredictable swings."
            else:
                text = f"{label}: regime {regime_label}."

            descriptions.append({
                "label": label,
                "regime": regime,
                "regime_label": regime_label,
                "description": text,
            })

        return descriptions

    def _generate_outlook_from_predictions(
        self, predictions_context: list[dict], historical_pace: list[dict]
    ) -> dict:
        """Generate structured outlook data from VQS predictions and historical pace.

        Returns a dict with:
          - summary: overall outlook text
          - series_outlooks: per-series prediction + pace context
          - regime_descriptions: plain-English regime signals
        """
        if not predictions_context:
            return {
                "summary": (
                    "No model predictions available for next month. "
                    "Our VQS model will generate forecasts once the next bulletin cycle begins."
                ),
                "series_outlooks": [],
                "regime_descriptions": [],
            }

        pace_by_key = {
            (p["visa_class"], p["country"]): p for p in historical_pace
        }

        series_outlooks = []
        for entry in predictions_context:
            key = (entry["visa_class"], entry["country"])
            pace = pace_by_key.get(key)

            outlook_item = {
                "label": entry["label"],
                "predicted_date": entry.get("predicted_date"),
                "regime": entry.get("regime"),
            }
            rl = entry.get("regime_label")
            if rl and str(rl).lower() != "unknown":
                outlook_item["regime_label"] = rl
                outlook_item["regime_badge_class"] = entry.get("regime_badge_class") or "secondary"
            else:
                outlook_item["regime_label"] = ""
                outlook_item["regime_badge_class"] = None

            if pace:
                outlook_item["avg_pace"] = pace["avg_12m_pace"]
                outlook_item["seasonal_deviation"] = pace["seasonal_deviation"]

                if pace["seasonal_deviation"] > 20:
                    outlook_item["pace_trend"] = "faster_than_usual"
                elif pace["seasonal_deviation"] < -20:
                    outlook_item["pace_trend"] = "slower_than_usual"
                else:
                    outlook_item["pace_trend"] = "typical"

            if entry.get("ci_spread_days"):
                outlook_item["confidence_note"] = (
                    "high" if entry["ci_spread_days"] < 30
                    else "moderate" if entry["ci_spread_days"] < 90
                    else "low"
                )

            if entry.get("top_experts"):
                outlook_item["top_experts"] = entry["top_experts"]

            series_outlooks.append(outlook_item)

        regime_descriptions = self._describe_regime_signals(predictions_context)

        advancing = sum(1 for o in series_outlooks if o.get("regime") == "advancing")
        stalled = sum(1 for o in series_outlooks if o.get("regime") == "stalled")
        retrogressing = sum(1 for o in series_outlooks if o.get("regime") == "retrogressing")

        if advancing > stalled + retrogressing:
            tone = "The overall trend is positive, with most tracked series showing forward movement."
        elif retrogressing > advancing:
            tone = "Several series are retrogressing. Applicants should prepare for possible further delays."
        elif stalled > advancing:
            tone = "Most series remain stalled with limited movement expected in the near term."
        else:
            tone = "The picture is mixed across employment-based categories."

        return {
            "summary": tone,
            "series_outlooks": series_outlooks,
            "regime_descriptions": regime_descriptions,
        }

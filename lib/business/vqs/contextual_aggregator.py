import math
from datetime import date
from typing import Any

from lib.business.vqs.predictors import (
    DemandSupplyPredictor,
    PacePredictor,
    PersistencePredictor,
    RegimeSwitchedPredictor,
    TrajectoryPredictor,
)
from lib.business.vqs.regime import classify_regime
from lib.business.vqs.seasonal_predictor import get_last_N_moves
from models.visa_cutoff_date import VisaCutoffDate


class ContextualTrajectoryAggregator:
    """
    Maintains weights for each model in specific contexts (Series, Horizon, Regime).
    Blends predictions using Softmax.
    """

    def __init__(
        self,
        learning_rate: float = 1.0,
        blend_temperature: float = 0.1,
        use_regime_context: bool = True,
    ):
        self.learning_rate = learning_rate
        self.blend_temperature = blend_temperature
        self.use_regime_context = use_regime_context

        self.predictors: dict[str, TrajectoryPredictor] = {
            "Persistence": PersistencePredictor(),
            "Pace": PacePredictor(),
            "DemandSupply": DemandSupplyPredictor(),
            "RegimeSwitched": RegimeSwitchedPredictor(),
        }

        # weights[context_key][model_name] = weight
        self.weights: dict[tuple, dict[str, float]] = {}

    def _get_context_key(
        self, visa_class: str, country: int, horizon: int, knowledge_date: date, action_type: str
    ) -> tuple:
        if not self.use_regime_context:
            return (visa_class, country, horizon)

        moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 6)
        regime_state = classify_regime(moves)

        # For oversubscribed EB-2/3, include EB-1 regime as additional context.
        # EB-1 utilization of visa supply spills to EB-2/3, so EB-1 regime
        # affects which model performs best for EB-2/3.
        eb1_regime = "n/a"
        if visa_class in ("2nd", "3rd"):
            eb1_moves = get_last_N_moves("1st", country, action_type, knowledge_date, 6)
            if eb1_moves:
                eb1_regime = classify_regime(eb1_moves).regime.value

        return (visa_class, country, horizon, regime_state.regime.value, eb1_regime)

    def _initialize_weights(self, context_key: tuple):
        if context_key not in self.weights:
            n = len(self.predictors)
            self.weights[context_key] = {name: 1.0 / n for name in self.predictors}

    def predict(
        self,
        visa_class: str,
        country: int,
        action_type: str,
        target_date: date,
        horizon: int,
    ) -> tuple[date | None, dict[str, Any]]:
        from dateutil.relativedelta import relativedelta
        knowledge_date = target_date - relativedelta(months=horizon)
        context_key = self._get_context_key(visa_class, country, horizon, knowledge_date, action_type)
        self._initialize_weights(context_key)

        preds = {}
        for name, predictor in self.predictors.items():
            try:
                preds[name] = predictor.predict(
                    visa_class=visa_class,
                    country=country,
                    action_type=action_type,
                    target_date=target_date,
                    horizon=horizon,
                )
            except Exception:
                preds[name] = None

        valid_preds = {k: v for k, v in preds.items() if v is not None}
        if not valid_preds:
            return None, {"weights": self.weights[context_key], "preds": preds}

        # Softmax blending
        model_weights = self.weights[context_key]
        
        # Compute softmax over valid models
        valid_weights = {k: model_weights[k] for k in valid_preds}
        max_w = max(valid_weights.values())
        
        exp_weights = {}
        for k, w in valid_weights.items():
            # Apply temperature
            # T -> 0: hard routing (max weight gets 1.0)
            # T -> inf: uniform blending
            scaled_w = (w - max_w) / self.blend_temperature
            # clamp to avoid overflow/underflow
            scaled_w = max(-500, min(500, scaled_w))
            exp_weights[k] = math.exp(scaled_w)
            
        sum_exp = sum(exp_weights.values())
        softmax_weights = {k: ew / sum_exp for k, ew in exp_weights.items()}

        # Blend dates
        # Convert dates to days since epoch for blending
        blended_days = 0.0
        for k, p_date in valid_preds.items():
            blended_days += p_date.toordinal() * softmax_weights[k]

        final_date = date.fromordinal(int(round(blended_days)))

        metadata = {
            "context_key": context_key,
            "weights": model_weights,
            "softmax_weights": softmax_weights,
            "preds": preds,
        }
        return final_date, metadata

    def update_weights(
        self,
        visa_class: str,
        country: int,
        action_type: str,
        target_date: date,
        horizon: int,
        actual_date: date,
    ):
        """Update weights based on actual outcome using Hedge algorithm."""
        from dateutil.relativedelta import relativedelta
        knowledge_date = target_date - relativedelta(months=horizon)
        context_key = self._get_context_key(visa_class, country, horizon, knowledge_date, action_type)
        self._initialize_weights(context_key)

        preds = {}
        for name, predictor in self.predictors.items():
            try:
                preds[name] = predictor.predict(
                    visa_class=visa_class,
                    country=country,
                    action_type=action_type,
                    target_date=target_date,
                    horizon=horizon,
                )
            except Exception:
                preds[name] = None

        current_weights = self.weights[context_key]
        new_weights = {}
        
        for name, w in current_weights.items():
            pred = preds.get(name)
            if pred is None:
                new_weights[name] = w
                continue
                
            error_days = abs((pred - actual_date).days)
            # Loss function: squared error scaled to years
            loss = (error_days / 365.0) ** 2
            
            # Hedge update
            new_weights[name] = w * math.exp(-self.learning_rate * loss)
            
        # Normalize
        total_w = sum(new_weights.values())
        if total_w > 0:
            for name in new_weights:
                new_weights[name] /= total_w
        else:
            n = len(new_weights)
            for name in new_weights:
                new_weights[name] = 1.0 / n
                
        self.weights[context_key] = new_weights

    def warmup_history(self, visa_class: str, country: int, action_type: str, knowledge_date: date, horizons: list[int]):
        """Warm up weights using historical data up to knowledge_date."""
        from models.bulletin import Bulletin
        from lib.business.vqs.data_cache import get_all_bulletins
        
        if not hasattr(self, "_last_warmup_date"):
            self._last_warmup_date = {}
            
        series_key = (visa_class, country, action_type)
        last_date = self._last_warmup_date.get(series_key)
        
        if last_date and last_date >= knowledge_date:
            # Already warmed up to this date or beyond
            return
            
        bulletins = get_all_bulletins()
        # Sort chronologically
        bulletins = sorted(bulletins, key=lambda b: b.publication_date)
        
        for b in bulletins:
            if last_date and b.publication_date <= last_date:
                continue
            if b.publication_date > knowledge_date:
                continue
                
            target_date = b.publication_date
            actual_obj = VisaCutoffDate.objects.filter(
                bulletin=b,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
            ).first()
            
            if not actual_obj or not actual_obj.cutoff_date:
                continue
                
            actual_date = actual_obj.cutoff_date
            
            for h in horizons:
                self.update_weights(
                    visa_class=visa_class,
                    country=country,
                    action_type=action_type,
                    target_date=target_date,
                    horizon=h,
                    actual_date=actual_date,
                )
                
        self._last_warmup_date[series_key] = knowledge_date


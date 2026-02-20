"""
Online Expert Aggregator using Hedge Algorithm.

Maintains weights for each expert for each series (visa_class, country).
Updates weights based on prediction error (squared loss) after each bulletin.
"""
import math
from datetime import date, timedelta
from typing import Optional, Dict

from lib.business.vqs.expert_pool import ALL_EXPERTS


class ExpertAggregator:
    def __init__(self, learning_rate: float = 0.5, experts: dict | None = None):
        self.experts = experts if experts is not None else ALL_EXPERTS
        self.learning_rate = learning_rate
        
        # Weights: series_key -> {expert_name -> weight}
        # series_key is tuple (visa_class, country)
        self.weights: Dict[tuple, Dict[str, float]] = {}
        
        # Track which series have been warmed up
        self.warmed_series: set[tuple] = set()
        
        # History for debugging/analysis
        # (series, date) -> {expert: prediction, 'ensemble': prediction, 'weights': {...}}
        self.history = {}

    def _get_series_key(self, visa_class: str, country: int) -> tuple:
        return (visa_class, country)

    def _initialize_weights(self, series_key: tuple, action_type: str = "final_action"):
        if series_key in self.weights:
            return

        is_filing = action_type == "filing"
        if "persistence" in self.experts:
            # Bias towards persistence: 50% mass (70% for filing)
            n_others = len(self.experts) - 1
            if n_others > 0:
                p_weight = 0.5 if is_filing else 0.5
                o_weight = (1.0 - p_weight) / n_others
                self.weights[series_key] = {
                    name: (p_weight if name == "persistence" else o_weight)
                    for name in self.experts
                }
            else:
                self.weights[series_key] = {"persistence": 1.0}
        else:
            # Uniform if no persistence
            n = len(self.experts)
            self.weights[series_key] = {name: 1.0 / n for name in self.experts}

    def predict(
        self,
        visa_class: str,
        country: int,
        action_type: str,
        knowledge_date: date,
        facts: list | None = None
    ) -> tuple[Optional[date], dict]:
        """
        Get ensemble prediction for the given series and date.
        Returns (predicted_date, metadata_dict).
        """
        series_key = self._get_series_key(visa_class, country)
        self._initialize_weights(series_key, action_type=action_type)
        
        current_weights = self.weights[series_key]
        
        # 1. Collect predictions from all experts
        expert_preds = {}
        valid_experts = []
        
        start_cutoff = None # need a reference point to convert dates to days
        
        # We need a reference date to do weighted averaging of dates.
        # Use simple persistence prediction as anchor.
        ref_pred = self.experts["persistence"](visa_class, country, action_type, knowledge_date, facts=facts)
        if not ref_pred:
            # If persistence fails (no history), we can't do anything
            return None, {"error": "No history"}
            
        anchor_date = ref_pred

        weighted_sum_days = 0.0
        total_weight = 0.0
        
        expert_outputs = {}

        for name, expert_fn in self.experts.items():
            pred = expert_fn(visa_class, country, action_type, knowledge_date, facts=facts)
            expert_outputs[name] = pred
            
            if pred is not None:
                # Calculate days from anchor
                delta_days = (pred - anchor_date).days
                weight = current_weights[name]
                
                weighted_sum_days += weight * delta_days
                total_weight += weight
                valid_experts.append(name)
        
        if total_weight == 0:
            return anchor_date, {"status": "all_experts_failed"}
            
        # Re-normalize weights among valid experts
        final_delta = weighted_sum_days / total_weight
        ensemble_pred = anchor_date + timedelta(days=int(final_delta))
        
        # Store for history (needed for update)
        self.history[(series_key, knowledge_date)] = {
            "expert_preds": expert_outputs,
            "weights": current_weights.copy(),
            "ensemble_pred": ensemble_pred
        }
        
        return ensemble_pred, {
            "weights": current_weights,
            "expert_preds": expert_outputs,
            "valid_experts": valid_experts
        }

    def update(
        self,
        visa_class: str,
        country: int,
        knowledge_date: date,
        actual_cutoff: date,
        action_type: str = "final_action"
    ):
        """
        Update weights based on actual outcome.
        Uses Hedge update rule: w_i *= exp(-eta * loss_i)
        Loss is Squared Error (MSE), scaled to be reasonable.
        """
        series_key = self._get_series_key(visa_class, country)
        if series_key not in self.weights:
            return # Should not happen if predict was called
            
        history_entry = self.history.get((series_key, knowledge_date))
        if not history_entry:
            return
            
        expert_preds = history_entry["expert_preds"]
        current_weights = self.weights[series_key]
        
        # Action-aware learning rate
        eta = 0.8 if action_type == "filing" else self.learning_rate
        
        # Calculate loss for each expert
        # Scale loss: days/30 (months) squared? Or just raw days?
        # Raw days squared can be huge (e.g. 300^2 = 90000). exp(-0.5 * 90000) -> 0 instantly.
        # We need to scale loss to range [0, 1] approximately, or use much smaller learning rate.
        # Let's use flexible learning rate or AdaHedge ideally.
        # For simple Hedge, let's normalize loss by max possible loss? 
        # Better: loss = (error_days / 365.0)^2.  Max expected error ~1 year.
        
        updates = {}
        scaling_factor = 365.0
        
        for name, pred in expert_preds.items():
            if pred is None:
                # Expert abstained. No weight update? Or max loss?
                # Neutral strategy: treat as if it predicted the ensemble average (no regret)
                # or just don't update its weight.
                # Let's give it median loss of other experts?
                # For now: no update for abstaining experts.
                updates[name] = 1.0
                continue
                
            error_days = (pred - actual_cutoff).days
            loss = (error_days / scaling_factor) ** 2
            
            # Hedge update
            update_factor = math.exp(-eta * loss)
            updates[name] = update_factor
            
        # Apply updates
        new_total = 0.0
        for name, factor in updates.items():
            current_weights[name] *= factor
            new_total += current_weights[name]
            
        # Renormalize
        if new_total > 0:
            for name in current_weights:
                current_weights[name] /= new_total
        else:
            # Numerical collapse, reset to uniform
            n = len(self.experts)
            for name in current_weights:
                current_weights[name] = 1.0 / n
                
        self.weights[series_key] = current_weights

    def warmup_history(
        self,
        visa_class: str,
        country: int,
        action_type: str,
        target_date: date,
        facts: list | None = None
    ):
        """
        Replay history up to target_date to learn weights for this series.
        """
        from models.bulletin import Bulletin
        from models.visa_cutoff_date import VisaCutoffDate
        
        # Get all historical cutoffs for this series before target_date
        # We need bulletins in order.
        history = list(VisaCutoffDate.objects.filter(
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            bulletin__publication_date__lt=target_date,
            cutoff_date__isnull=False
        ).select_related("bulletin").order_by("bulletin__publication_date"))
        
        if not history:
            return

        series_key = self._get_series_key(visa_class, country)
        if series_key in self.warmed_series:
            return  # Already warmed
            
        # Initialize weights
        self._initialize_weights(series_key)
        
        # Prepare for facts slicing
        # Assumes facts are sorted by publication_date!
        fact_idx = 0
        n_facts = len(facts) if facts else 0
        
        # Replay
        for row in history:
            pub_date = row.bulletin.publication_date
            actual_cutoff = row.cutoff_date
            
            # Slice facts for this point in history
            current_facts = None
            if facts is not None:
                # Advance idx to include all facts published on or before current pub_date
                # We assume facts are sorted by publication_date ascending.
                while fact_idx < n_facts and facts[fact_idx].publication_date <= pub_date:
                    fact_idx += 1
                
                # Careful: slicing a large list is O(K) copy.
                # If facts is 1M items, copying 500k items 100 times is slow.
                # 50MB * 100 = 5GB copy overhead.
                # Expert physics should handle this.
                # Ideally pass a wrapper or index range?
                # But expert_physics expects "list of objects".
                # Python slices are copies.
                # Optimizing: only expert_physics uses facts.
                # It iterates them.
                # If we pass the full list + a length limit?
                # expert_physics signature changes again...
                # Or we trust that 1M pointers copy is fast enough (8MB per copy).
                # 8MB * 200 = 1.6GB throughput. Doable in 1 second.
                # So straightforward slice is fine for 1M items.
                current_facts = facts[:fact_idx]
            
            # 1. Predict (updates internal history state)
            self.predict(visa_class, country, action_type, pub_date, facts=current_facts)
            
            # 2. Update (uses actual outcome)
            self.update(visa_class, country, pub_date, actual_cutoff, action_type=action_type)
            
        self.warmed_series.add(series_key)

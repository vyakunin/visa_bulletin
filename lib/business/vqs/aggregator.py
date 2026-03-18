"""Online Expert Aggregator using Hedge Algorithm.

Maintains weights for each expert for each series (visa_class, country).
Updates weights based on prediction error after each bulletin.

Supports:
- Multi-horizon composite loss
- Warmup decay (recent bulletins weighted more)
- Regime-aware learning rate
- Asymmetric loss (via MetricConfig)
"""

import math
from datetime import date, timedelta

from lib.business.vqs.expert_pool import ALL_EXPERT_TRAJECTORIES, ALL_EXPERTS
from lib.business.vqs.metric_config import MetricConfig


class ExpertAggregator:
    def __init__(
        self,
        learning_rate: float = 4.58,
        experts: dict | None = None,
        metric_config: MetricConfig | None = None,
    ):
        self.experts = experts if experts is not None else ALL_EXPERTS
        self.learning_rate = learning_rate
        self.metric_config = metric_config or MetricConfig.defaults()

        self.weights: dict[tuple, dict[str, float]] = {}
        self.warmed_series: set[tuple] = set()
        self.history = {}

    def _get_series_key(self, visa_class: str, country: int) -> tuple:
        return (visa_class, country)

    def _initialize_weights(self, series_key: tuple, action_type: str = "final_action"):
        if series_key in self.weights:
            return

        if "persistence" in self.experts:
            n_others = len(self.experts) - 1
            if n_others > 0:
                p_weight = 0.5
                o_weight = (1.0 - p_weight) / n_others
                self.weights[series_key] = {
                    name: (p_weight if name == "persistence" else o_weight)
                    for name in self.experts
                }
            else:
                self.weights[series_key] = {"persistence": 1.0}
        else:
            n = len(self.experts)
            self.weights[series_key] = {name: 1.0 / n for name in self.experts}

    def predict(
        self,
        visa_class: str,
        country: int,
        action_type: str,
        knowledge_date: date,
        facts: list | None = None,
    ) -> tuple[date | None, dict]:
        """Get ensemble prediction for the given series and date."""
        series_key = self._get_series_key(visa_class, country)
        self._initialize_weights(series_key, action_type=action_type)

        current_weights = self.weights[series_key]

        ref_pred = self.experts["persistence"](
            visa_class, country, action_type, knowledge_date, facts=facts
        )
        if not ref_pred:
            return None, {"error": "No history"}

        anchor_date = ref_pred

        weighted_sum_days = 0.0
        total_weight = 0.0
        expert_outputs = {}

        for name, expert_fn in self.experts.items():
            pred = expert_fn(
                visa_class, country, action_type, knowledge_date, facts=facts
            )
            expert_outputs[name] = pred

            if pred is not None:
                delta_days = (pred - anchor_date).days
                weight = current_weights[name]
                weighted_sum_days += weight * delta_days
                total_weight += weight

        if total_weight == 0:
            return anchor_date, {"status": "all_experts_failed"}

        final_delta = weighted_sum_days / total_weight
        ensemble_pred = anchor_date + timedelta(days=int(final_delta))

        self.history[(series_key, knowledge_date)] = {
            "expert_preds": expert_outputs,
            "weights": current_weights.copy(),
            "ensemble_pred": ensemble_pred,
        }

        return ensemble_pred, {
            "weights": current_weights,
            "expert_preds": expert_outputs,
            "valid_experts": [n for n in expert_outputs if expert_outputs[n] is not None],
        }

    def predict_trajectory(
        self,
        visa_class: str,
        country: int,
        action_type: str,
        knowledge_date: date,
        steps: int = 12,
        facts: list | None = None,
    ) -> list[date | None]:
        """Produce a weighted ensemble trajectory for steps 1..N months ahead."""
        series_key = self._get_series_key(visa_class, country)
        self._initialize_weights(series_key, action_type=action_type)
        current_weights = self.weights[series_key]

        ref_traj = ALL_EXPERT_TRAJECTORIES["persistence"](
            visa_class, country, action_type, knowledge_date, steps, facts
        )
        if all(d is None for d in ref_traj):
            return [None] * steps

        anchor = ref_traj[0]
        if anchor is None:
            return [None] * steps

        trajectory: list[date | None] = []
        for step_idx in range(steps):
            weighted_sum = 0.0
            total_w = 0.0
            for name in self.experts:
                traj_fn = ALL_EXPERT_TRAJECTORIES.get(name)
                if traj_fn is None:
                    continue
                traj = traj_fn(
                    visa_class, country, action_type, knowledge_date, steps, facts
                )
                pred = traj[step_idx] if step_idx < len(traj) else None
                if pred is None:
                    continue
                w = current_weights.get(name, 0.0)
                delta = (pred - anchor).days
                weighted_sum += w * delta
                total_w += w
            if total_w > 0:
                final_delta = weighted_sum / total_w
                trajectory.append(anchor + timedelta(days=int(final_delta)))
            else:
                trajectory.append(anchor)
        return trajectory

    def update(
        self,
        visa_class: str,
        country: int,
        knowledge_date: date,
        actual_cutoff: date,
        action_type: str = "final_action",
        actuals_by_horizon: dict[int, date] | None = None,
        metric_config: MetricConfig | None = None,
        regime_lr_multiplier: float = 1.0,
    ):
        """Update weights based on actual outcome(s).

        Uses Hedge update rule: w_i *= exp(-eta * loss_i).
        Supports regime-aware learning rate via regime_lr_multiplier.
        """
        series_key = self._get_series_key(visa_class, country)
        if series_key not in self.weights:
            return

        history_entry = self.history.get((series_key, knowledge_date))
        if not history_entry:
            return

        expert_preds = history_entry["expert_preds"]
        current_weights = self.weights[series_key]

        base_eta = 0.8 if action_type == "filing" else self.learning_rate
        eta = base_eta * regime_lr_multiplier

        if metric_config is None:
            metric_config = self.metric_config

        horizon_actuals: dict[int, date] = {1: actual_cutoff}
        if actuals_by_horizon:
            horizon_actuals.update(actuals_by_horizon)

        period_w = metric_config.period_weight(knowledge_date)

        updates = {}
        for name, pred in expert_preds.items():
            if pred is None:
                updates[name] = 1.0
                continue

            total_loss = 0.0
            total_hw = 0.0
            for h, actual in horizon_actuals.items():
                hw = metric_config.horizon_weights.get(h, 0.0)
                if hw <= 0:
                    continue
                error_days = (pred - actual).days
                loss_h = metric_config.expert_loss(error_days)
                total_loss += hw * loss_h
                total_hw += hw

            if total_hw > 0:
                avg_loss = total_loss / total_hw
            else:
                avg_loss = metric_config.expert_loss((pred - actual_cutoff).days)

            effective_loss = avg_loss * period_w
            update_factor = math.exp(-eta * effective_loss)
            updates[name] = update_factor

        new_total = 0.0
        for name, factor in updates.items():
            current_weights[name] *= factor
            new_total += current_weights[name]

        if new_total > 0:
            for name in current_weights:
                current_weights[name] /= new_total
        else:
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
        facts: list | None = None,
    ):
        """Replay history up to target_date to learn weights.

        Applies warmup_decay from MetricConfig so recent bulletins
        have more influence on final weights.
        """
        from lib.business.vqs.regime import classify_regime, regime_learning_rate
        from lib.business.vqs.seasonal_predictor import get_last_N_moves
        from models.visa_cutoff_date import VisaCutoffDate

        history = list(
            VisaCutoffDate.objects.filter(
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                bulletin__publication_date__lt=target_date,
                cutoff_date__isnull=False,
            )
            .select_related("bulletin")
            .order_by("bulletin__publication_date")
        )

        if not history:
            return

        series_key = self._get_series_key(visa_class, country)
        if series_key in self.warmed_series:
            return

        self._initialize_weights(series_key)

        cutoff_by_month: dict[tuple[int, int], date] = {}
        for row in history:
            pd = row.bulletin.publication_date
            cutoff_by_month[(pd.year, pd.month)] = row.cutoff_date

        fact_idx = 0
        n_facts = len(facts) if facts else 0
        horizons_needed = [h for h in self.metric_config.horizon_weights if h > 1]

        total_months = len(history)

        for idx, row in enumerate(history):
            pub_date = row.bulletin.publication_date
            actual_cutoff = row.cutoff_date

            current_facts = None
            if facts is not None:
                while fact_idx < n_facts and facts[fact_idx].publication_date <= pub_date:
                    fact_idx += 1
                current_facts = facts[:fact_idx]

            self.predict(
                visa_class, country, action_type, pub_date, facts=current_facts
            )

            actuals_by_horizon: dict[int, date] | None = None
            if horizons_needed:
                abh: dict[int, date] = {}
                for h in horizons_needed:
                    future_month = pub_date.month + (h - 1)
                    future_year = pub_date.year
                    while future_month > 12:
                        future_month -= 12
                        future_year += 1
                    future_cutoff = cutoff_by_month.get((future_year, future_month))
                    if future_cutoff is not None:
                        abh[h] = future_cutoff
                if abh:
                    actuals_by_horizon = abh

            # Regime-aware learning rate
            months_ago = total_months - idx - 1
            moves = get_last_N_moves(visa_class, country, action_type, pub_date, 6)
            regime_state = classify_regime(moves)
            lr_mult = regime_learning_rate(regime_state, base_lr=1.0)

            # Apply warmup decay: recent bulletins weight more
            decay_factor = self.metric_config.warmup_weight(months_ago)
            lr_mult *= decay_factor

            self.update(
                visa_class,
                country,
                pub_date,
                actual_cutoff,
                action_type=action_type,
                actuals_by_horizon=actuals_by_horizon,
                regime_lr_multiplier=lr_mult,
            )

        self.warmed_series.add(series_key)

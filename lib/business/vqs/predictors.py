import datetime
from typing import Protocol

from dateutil.relativedelta import relativedelta

from lib.business.vqs.data_cache import get_cutoff_at_date
from lib.business.vqs.expert_pool import trajectory_physics
from lib.business.vqs.solver import predict_regime_switched
from models.enums.country import Country

# EB-1 series that benefit from regime-switched predictor (backed by spaghetti data)
_EB1_SERIES = frozenset([
    (Country.INDIA.value, "1st"),
    (Country.CHINA.value, "1st"),
])


class TrajectoryPredictor(Protocol):
    def predict(self, visa_class: str, country: int, action_type: str, target_date: datetime.date, horizon: int) -> datetime.date | None:
        ...

class PersistencePredictor:
    def predict(self, visa_class: str, country: int, action_type: str, target_date: datetime.date, horizon: int) -> datetime.date | None:
        knowledge_date = target_date - relativedelta(months=horizon)
        return get_cutoff_at_date(visa_class, country, action_type, knowledge_date)

class PacePredictor:
    def predict(self, visa_class: str, country: int, action_type: str, target_date: datetime.date, horizon: int) -> datetime.date | None:
        pace_days_per_month = {
            (Country.INDIA.value, "2nd"): 7,
            (Country.INDIA.value, "3rd"): 7,
            (Country.INDIA.value, "1st"): 14,
            (Country.CHINA.value, "2nd"): 14,
            (Country.CHINA.value, "3rd"): 21,
            (Country.CHINA.value, "1st"): 21,
        }
        knowledge_date = target_date - relativedelta(months=horizon)
        current = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
        if not current:
            return None

        pace = pace_days_per_month.get((country, visa_class), 7)
        return current + datetime.timedelta(days=pace * horizon)

class DemandSupplyPredictor:
    def predict(self, visa_class: str, country: int, action_type: str, target_date: datetime.date, horizon: int) -> datetime.date | None:
        knowledge_date = target_date - relativedelta(months=horizon)

        # Pure physics trajectory, no stickiness/caps
        traj = trajectory_physics(
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            knowledge_date=knowledge_date,
            steps=horizon,
        )
        if traj and len(traj) >= horizon:
            return traj[horizon - 1]
        return None

class RegimeSwitchedPredictor:
    def predict(self, visa_class: str, country: int, action_type: str, target_date: datetime.date, horizon: int) -> datetime.date | None:
        knowledge_date = target_date - relativedelta(months=horizon)

        outcome = predict_regime_switched(
            knowledge_date=knowledge_date,
            visa_class=visa_class,
            country=country,
            action_type=action_type,
        )

        for res in outcome.results:
            if res.month.year == target_date.year and res.month.month == target_date.month:
                return res.cutoff_date

        if outcome.results:
            return outcome.results[-1].cutoff_date
        return None


class HybridPredictor:
    """Dispatches to the empirically best model per (series, horizon).

    Dispatch rules derived from spaghetti chart MAE data:
    - EB-1 (India/China) at any horizon: Regime-Switched
      (RS MAE: 130d India EB-1, 62.8d China EB-1 vs 147.5d, 73.1d persistence)
    - EB-2/3 (India/China) at h<=3: VQS Ensemble via solver
      (VQS 1m MAE: 86.6d India EB-2, 112.3d India EB-3, 52.8d China EB-2, 81.7d China EB-3)
    - EB-2/3 (India/China) at h>=6: Pace
      (Pace 6m MAE beats persistence on all 6 series)
    - All other series (ROW, Mexico, Philippines): Persistence
    """

    def __init__(self):
        self._rs = RegimeSwitchedPredictor()
        self._pace = PacePredictor()
        self._persistence = PersistencePredictor()

    def predict(self, visa_class: str, country: int, action_type: str, target_date: datetime.date, horizon: int) -> datetime.date | None:
        if (country, visa_class) in _EB1_SERIES:
            return self._rs.predict(visa_class, country, action_type, target_date, horizon)

        eb_oversubscribed = frozenset([
            (Country.INDIA.value, "2nd"), (Country.INDIA.value, "3rd"),
            (Country.CHINA.value, "2nd"), (Country.CHINA.value, "3rd"),
        ])
        if (country, visa_class) in eb_oversubscribed:
            if horizon >= 6:
                return self._pace.predict(visa_class, country, action_type, target_date, horizon)
            # For 1m and 3m, dispatch to VQS solver
            knowledge_date = target_date - relativedelta(months=horizon)
            from lib.business.vqs.aggregator import ExpertAggregator
            from lib.business.vqs.meta_params import VqsMetaParams
            from lib.business.vqs.solver import predict_next_bulletin_and_maturity
            from models.raw_facts import RawFactsLedger
            facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))
            aggregator = ExpertAggregator()
            meta = VqsMetaParams.defaults()
            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=knowledge_date,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                facts=facts,
                meta=meta,
                aggregator=aggregator,
            )
            if horizon == 1:
                return outcome.predicted_cutoff
            idx = horizon - 1
            if idx < len(outcome.results):
                return outcome.results[idx].cutoff_date
            return outcome.predicted_cutoff

        return self._persistence.predict(visa_class, country, action_type, target_date, horizon)


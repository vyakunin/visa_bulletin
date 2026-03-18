import datetime
import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.business.vqs.meta_params import VqsMetaParams
from lib.business.vqs.solver import predict_next_bulletin_and_maturity
from models.enums.country import Country


def test_dampening():
    knowledge_date = datetime.date(2024, 1, 1)
    visa_class = "2nd"
    country = Country.INDIA.value
    action_type = "final_action"

    # Use a custom meta_params with 0.5 blending to make it obvious
    meta = VqsMetaParams(
        ensemble_persistence_weight=0.5,
        blend_lambda=1.0,  # no blend lambda dampening
        stickiness_days=0,  # no stickiness
        cap_forward_days=999,  # no caps
        use_no_change_when_low_confidence=False,
    )

    # We need to simulate a situation where ensemble predicts a move.
    # To avoid relying on DB, we can just check the code logic.
    # But let's see if we can run it.

    try:
        predict_next_bulletin_and_maturity(
            knowledge_date=knowledge_date,
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            meta=meta,
        )

        # print(f"Prediction: {res[0]}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_dampening()

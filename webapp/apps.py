"""Django app configuration for webapp"""

import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webapp"
    verbose_name = "U.S. Immigration Data"

    def ready(self) -> None:
        # Eagerly import numpy at app load. Under gunicorn --preload the WSGI app
        # (and thus AppConfig.ready) runs once in the single-threaded master before
        # workers fork, so numpy is fully initialized and CoW-shared to every worker.
        # Without this, the first request to a numpy-using path (the GBM VQS expert)
        # could have two worker threads trigger numpy's first import concurrently,
        # raising "partially initialized module numpy" — a real but rare prod 500.
        # The cost is a one-time ~100ms master import, shared across workers via fork.
        import numpy  # noqa: F401

        # Warm the VQS ML stack in the gunicorn --preload MASTER so every forked
        # (and later --max-requests-recycled) worker inherits the loaded matplotlib
        # font cache + LightGBM/sklearn models CoW — instead of paying the ~11s lazy
        # import+model-load INSIDE a request. That penalty is the EB country-dashboard
        # /employment-based/{china,india}/ 10-17s cold-miss (profiled: aggregator 96ms,
        # but first VQS call 13.7s = ~11s import/model-load + 2.6s compute; steady-state
        # recompute is only 2.6s). One warmup predict here loads the whole chain once at
        # boot; the per-(country,action_type) VQS result cache still fills lazily
        # (~0.5s/class) but no request ever eats the import penalty again.
        #
        # Guarded by VQS_WARM=1 — set ONLY on the gunicorn process (NOT the sibling
        # `manage.py migrate`/collectstatic/test) so management commands stay fast.
        if os.environ.get("VQS_WARM") != "1":
            return
        try:
            from datetime import date

            from lib.business.vqs.solver import predict_regime_switched
            from models.bulletin import Bulletin
            from models.enums.country import Country

            knowledge_date = (
                Bulletin.objects.order_by("-publication_date")
                .values_list("publication_date", flat=True)
                .first()
                or date.today()
            )
            predict_regime_switched(
                knowledge_date=knowledge_date,
                visa_class="2nd",
                country=Country.INDIA.value,
                action_type="final_action",
                priority_date=None,
            )
            logger.info("VQS warmup complete (master preload) — workers inherit loaded models")
        except Exception:
            # Never block boot on warmup — a cold worker just reverts to paying the
            # lazy import on its first request (the pre-fix behavior).
            logger.exception("VQS warmup failed (non-fatal); workers will lazy-load")
        finally:
            # Close any DB connection opened during warmup so it is NOT inherited
            # across the gunicorn fork (a shared socket across workers corrupts reads).
            try:
                from django.db import connections

                connections.close_all()
            except Exception:
                logger.exception("close_all after VQS warmup failed (non-fatal)")

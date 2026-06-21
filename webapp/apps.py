"""Django app configuration for webapp"""

from django.apps import AppConfig


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

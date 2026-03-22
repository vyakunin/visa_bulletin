"""Request timing middleware for identifying slow views."""

import logging
import time

logger = logging.getLogger("django_config.middleware")

SLOW_REQUEST_THRESHOLD_MS = 500


class RequestTimingMiddleware:
    """Logs request duration for all requests, with extra detail for slow ones (>500ms)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - start) * 1000

        path = request.get_full_path()
        status = response.status_code

        if duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
            logger.warning(
                "SLOW REQUEST: %s %s -> %d in %.0fms",
                request.method,
                path,
                status,
                duration_ms,
            )
        elif duration_ms >= 100:
            logger.info(
                "%s %s -> %d in %.0fms",
                request.method,
                path,
                status,
                duration_ms,
            )

        return response

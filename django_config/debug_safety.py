"""
Defensive check preventing Django DEBUG=True on production.

Leaking DEBUG in prod exposes URL conf, settings, env vars, tracebacks, and
SQL queries on every 404/500. This module provides a pure function so it can
be unit-tested without pulling in the full Django settings module.
"""

PRODUCTION_HOSTNAMES = ("visa-bulletin.us", "www.visa-bulletin.us")


def assert_debug_is_safe(debug: bool, allowed_hosts: list[str]) -> None:
    if not debug:
        return
    offending = [h for h in PRODUCTION_HOSTNAMES if h in allowed_hosts]
    if offending:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "DEBUG=True is not permitted when ALLOWED_HOSTS contains a production "
            "hostname — would expose URL conf, settings and tracebacks. "
            f"Offending hostnames: {offending}. Unset DEBUG or remove the "
            "production hostname from ALLOWED_HOSTS."
        )

"""Page statistics precomputed into the `aggregates` store.

The largest job-title, sponsor, employer and (employer, role) pages, and the state
pages, aggregate up to millions of salary rows per render: tens of seconds on the
4-core prod box and past the web server's 45s query limit. scripts.cache.warm_profiles
stores their default render here; a request reads it and computes live only on a miss.

Salary data changes only at a data graduation, so the warmer runs on the staging DB
before the cutover and the resync carries the rows to prod. Keys of pages with a
year window carry its first fiscal year, so a new calendar year is a miss.
"""

from django.conf import settings
from django.db import connection

PRECOMPUTED_PROFILE_KEY_PREFIX = "profile."


def clear_precomputed_profiles() -> int:
    """Delete every stored profile. Cluster ids are reused by re-clustering, so a
    rebuild clears before it warms. Returns the number of rows deleted."""
    table = settings.CACHES[settings.AGGREGATES_CACHE_ALIAS]["LOCATION"]
    with connection.cursor() as cur:
        # DatabaseCache stores "<KEY_PREFIX>:<version>:<key>"; neither is set here.
        cur.execute(
            f"DELETE FROM {connection.ops.quote_name(table)} WHERE cache_key LIKE %s",
            [f":1:{PRECOMPUTED_PROFILE_KEY_PREFIX}%"],
        )
        return cur.rowcount


def stored_profile_keys() -> set[str]:
    """Keys (without the cache's own prefix) of every stored profile."""
    table = settings.CACHES[settings.AGGREGATES_CACHE_ALIAS]["LOCATION"]
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT cache_key FROM {connection.ops.quote_name(table)} WHERE cache_key LIKE %s",
            [f":1:{PRECOMPUTED_PROFILE_KEY_PREFIX}%"],
        )
        return {row[0][3:] for row in cur.fetchall()}

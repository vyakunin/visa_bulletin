from django.db import migrations


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("models", "0045_employercluster_search_avg_salary_and_more"),
    ]

    operations = [
        # Mirror of sr_ec_canonical_name_trgm (migration 0044) but on the
        # employer-level name_normalized column. _get_cluster_or_404 in
        # webapp/views/employers/profile.py falls back to
        # name_normalized__icontains when a slug doesn't resolve directly,
        # which is constantly hit by bot crawls of stale Google-indexed
        # /employer/<slug>/ URLs. Without this index it's a sequential scan
        # over ~287k rows (~1.1s each in production logs).
        # See docs/PERFORMANCE_IMPROVEMENTS.md §C.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "se_name_normalized_trgm "
                "ON salary_employer "
                "USING gin (upper(name_normalized) gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX CONCURRENTLY IF EXISTS se_name_normalized_trgm;"
            ),
        ),
    ]

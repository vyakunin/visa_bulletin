from django.db import migrations


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("models", "0046_employer_name_normalized_trigram_index"),
    ]

    operations = [
        # Django's __icontains lookup emits `WHERE UPPER(field::text) LIKE UPPER(%s)`
        # (not ILIKE), so a trigram index on the bare column is NOT usable by the
        # planner — the expression must match. /salaries/?q=<keyword> hits both
        # job_title and soc_title with that exact UPPER-wrapped LIKE. Without these
        # indexes the planner falls back to Index Scan Backward on wage_annual
        # (filter on UPPER(...) LIKE inline), which scans ~1.2M rows for a 50-row
        # LIMIT on high-match-low-wage keywords like CASHIER / KEEPER. Same
        # pattern as the existing se_name_normalized_trgm in migration 0046.
        # IF NOT EXISTS because the indexes were already applied live in prod
        # via CREATE INDEX CONCURRENTLY before this migration was authored.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "sr_job_title_upper_trgm "
                "ON salary_record "
                "USING gin (UPPER(job_title::text) gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX CONCURRENTLY IF EXISTS sr_job_title_upper_trgm;"
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "sr_soc_title_upper_trgm "
                "ON salary_record "
                "USING gin (UPPER(soc_title::text) gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX CONCURRENTLY IF EXISTS sr_soc_title_upper_trgm;"
            ),
        ),
    ]

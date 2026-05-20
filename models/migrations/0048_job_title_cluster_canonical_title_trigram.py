from django.db import migrations


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("models", "0047_salary_record_title_trigram_indexes"),
    ]

    operations = [
        # `/job-title/<slug>/` runs `canonical_title__icontains=<first_word>`
        # to build the "Similar Job Titles" sidebar. Django emits
        # `WHERE UPPER(canonical_title::text) LIKE UPPER(%s)`, which the
        # planner can satisfy via a GIN trigram index on UPPER(canonical_title).
        # Without this index the lookup is a SeqScan over salary_job_title_cluster
        # on every cache miss — every bot crawl over the slug space pays the
        # cost. Same pattern as 0046/0047.
        # IF NOT EXISTS to tolerate the prod-applied-out-of-band case.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "sjtc_canonical_title_upper_trgm "
                "ON salary_job_title_cluster "
                "USING gin (UPPER(canonical_title::text) gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX CONCURRENTLY IF EXISTS "
                "sjtc_canonical_title_upper_trgm;"
            ),
        ),
    ]

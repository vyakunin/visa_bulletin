from django.db import migrations


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("models", "0057_publishedfloor_and_more"),
    ]

    operations = [
        # SalaryRecord.soc_code declares db_index=True, but no index on the
        # column exists in production — it was dropped for a bulk load and never
        # recreated (see the missing-index audit in docs/PERFORMANCE_IMPROVEMENTS.md).
        # Every /h1b-salary/<occupation>/ aggregate filters
        # soc_code__startswith, which Django emits as `soc_code::text LIKE
        # 'prefix%'`, so without it each of the page's nine aggregates is a
        # parallel seq scan of the 1.24 GB heap (~490 ms each, ~4.4 s per page).
        #
        # varchar_pattern_ops, not the default opclass: the database collation is
        # en_US.utf8, under which a plain btree cannot serve a LIKE prefix. This
        # is the same index Django itself creates for a db_index=True CharField,
        # and the same one worksite_record already has on ITS soc_code — where
        # the identical predicate is a 3 ms bitmap index scan against
        # salary_record's 323 ms seq scan, on a table twice the size.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "sr_soc_code_pattern "
                "ON salary_record "
                "USING btree (soc_code varchar_pattern_ops);"
            ),
            reverse_sql=("DROP INDEX CONCURRENTLY IF EXISTS sr_soc_code_pattern;"),
        ),
    ]

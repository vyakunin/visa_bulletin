from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("models", "0043_alter_predictedbulletin_target_bulletin_month_and_more"),
    ]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "sr_ec_canonical_name_trgm "
                "ON salary_employer_cluster "
                "USING gin (upper(canonical_name) gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX CONCURRENTLY IF EXISTS sr_ec_canonical_name_trgm;"
            ),
        ),
    ]

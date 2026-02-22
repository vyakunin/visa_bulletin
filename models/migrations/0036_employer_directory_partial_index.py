from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0035_blogpost"),
    ]

    operations = [
        # Partial index covering only rows that appear in the employer directory.
        # Allows COUNT(*) on the directory base queryset to use an index-only scan
        # instead of a full sequential scan (~64ms → ~1ms).
        migrations.RunSQL(
            sql=(
                "CREATE INDEX emp_dir_count_idx ON salary_employer_cluster (id) "
                "WHERE slug IS NOT NULL "
                "AND canonical_name != 'Unknown' "
                "AND slug != 'unknown' "
                "AND (total_lca_count > 0 OR total_perm_count > 0);"
            ),
            reverse_sql="DROP INDEX IF EXISTS emp_dir_count_idx;",
        ),
    ]

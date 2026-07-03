# Reconciles the phantom-0050 migration-state drift for IngestRejectionStats.
#
# History: 0024 created the model; the model was removed from code in Jan 2026
# and 0026 auto-generated a DeleteModel (dropping it from migration state and,
# on fresh DBs, the table); the model was re-introduced in f77adbc (June 2026)
# WITHOUT a new migration, with the prod/staging table recreated out-of-band.
# Since then migration-derived state lacks the model, so every `makemigrations`
# re-proposes "Create model IngestRejectionStats" and every vb_web boot warns
# "models have changes not yet reflected in a migration".
#
# This migration makes state == models == DB in every environment:
#  - state: re-adds the model exactly as the autodetector renders it today.
#  - DB, existing deployments (prod/staging — table already exists): no table
#    create; only renames the two out-of-band index names to the Django-derived
#    names now recorded in state (metadata-only ALTERs, instant).
#  - DB, fresh databases (tests/CI/dev — 0026 dropped the table): creates the
#    table from the model state; the IF EXISTS renames then no-op.
import django.db.models.deletion
from django.db import migrations, models


def _ensure_table(apps, schema_editor):
    model = apps.get_model("models", "IngestRejectionStats")
    tables = schema_editor.connection.introspection.table_names()
    if model._meta.db_table not in tables:
        schema_editor.create_model(model)


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0054_alter_datasource_source_type_uscisemployerapproval"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="IngestRejectionStats",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "reason",
                            models.CharField(
                                choices=[
                                    ("missing_case_number", "Missing Case Number"),
                                    ("missing_employer_name", "Missing Employer Name"),
                                    ("unknown_employer_name", "Unknown Employer Name"),
                                    ("missing_job_title", "Missing Job Title"),
                                    ("unknown_job_title", "Unknown Job Title"),
                                    ("missing_wage_data", "Missing Wage Data"),
                                    ("invalid_wage_unit", "Invalid Wage Unit"),
                                    ("missing_dates", "Missing Decision/Submit Dates"),
                                    ("invalid_date_sequence", "Invalid Date Sequence"),
                                    ("missing_visa_class", "Missing Visa Class"),
                                    (
                                        "whitelist_filtered",
                                        "Filtered by Case Number Whitelist",
                                    ),
                                    ("worksite_skipped", "Worksite Record Skipped"),
                                    ("other", "Other Rejection Reason"),
                                ],
                                help_text="Reason for rejection",
                                max_length=50,
                            ),
                        ),
                        (
                            "count",
                            models.IntegerField(
                                default=0,
                                help_text="Number of records rejected for this reason",
                            ),
                        ),
                        (
                            "sample_case_numbers",
                            models.JSONField(
                                default=list,
                                help_text="Sample case numbers (up to 10) for investigation",
                            ),
                        ),
                        (
                            "run",
                            models.ForeignKey(
                                help_text="Ingest run these rejections occurred in",
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="rejection_stats",
                                to="models.ingestrun",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "Ingest Rejection Statistics",
                        "verbose_name_plural": "Ingest Rejection Statistics",
                        "db_table": "ingest_rejection_stats",
                        "indexes": [
                            models.Index(
                                fields=["run", "reason"],
                                name="ingest_reje_run_id_6a581e_idx",
                            ),
                            models.Index(
                                fields=["run", "count"],
                                name="ingest_reje_run_id_306fd6_idx",
                            ),
                        ],
                        "unique_together": {("run", "reason")},
                    },
                ),
            ],
        ),
        # Fresh DBs (0026 dropped the table): create it. Existing DBs: no-op.
        migrations.RunPython(_ensure_table, migrations.RunPython.noop),
        # Existing DBs carry out-of-band index names; align them with the names
        # recorded in state above. IF EXISTS makes this a no-op on fresh DBs.
        migrations.RunSQL(
            sql='ALTER INDEX IF EXISTS "ingest_reje_run_id_ae4b18_idx" '
            'RENAME TO "ingest_reje_run_id_6a581e_idx";',
            reverse_sql='ALTER INDEX IF EXISTS "ingest_reje_run_id_6a581e_idx" '
            'RENAME TO "ingest_reje_run_id_ae4b18_idx";',
        ),
        migrations.RunSQL(
            sql='ALTER INDEX IF EXISTS "ingest_reje_run_id_e2c9d5_idx" '
            'RENAME TO "ingest_reje_run_id_306fd6_idx";',
            reverse_sql='ALTER INDEX IF EXISTS "ingest_reje_run_id_306fd6_idx" '
            'RENAME TO "ingest_reje_run_id_e2c9d5_idx";',
        ),
    ]

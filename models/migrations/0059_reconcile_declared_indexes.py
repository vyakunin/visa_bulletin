"""Make salary_record's declared indexes and its actual indexes the same set.

Thirteen indexes the models declared did not exist on either stack. The audit that
found them, the per-index decision, and the measurements are in
docs/PERFORMANCE_IMPROVEMENTS.md § "Model-declared indexes that were not there".

Every index this drops from the declaration is one nothing queries, so no DROP runs
on a deployed stack; the DROP INDEX IF EXISTS statements only fire on a fresh
database, where the migration history had built them. The two indexes that stay are
re-declared under the names they already carry, and the one gap worth closing —
the ingest_version FK, which rollback deletes through — is built CONCURRENTLY.
"""

import django.contrib.postgres.indexes
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("models", "0058_salary_record_soc_code_pattern_index"),
    ]

    operations = [
        # Composites no query filters on both columns of. (employer_name, job_title)
        # and (job_title, worksite_state) predate the trigram indexes that took over
        # keyword search in 0047; (soc_code, worksite_state) never had a caller.
        migrations.RemoveIndex(
            model_name="salaryrecord",
            name="salary_reco_employe_c93e9a_idx",
        ),
        migrations.RemoveIndex(
            model_name="salaryrecord",
            name="salary_reco_job_tit_7b8349_idx",
        ),
        migrations.RemoveIndex(
            model_name="salaryrecord",
            name="salary_reco_soc_cod_8cdf26_idx",
        ),
        # (employer_id, is_worksite) is the leading pair of sr_emp_wk_fy_inc_wage,
        # which the planner already uses for that predicate alone — measured as an
        # Index Only Scan, so a second index would only duplicate the keys.
        migrations.RemoveIndex(
            model_name="salaryrecord",
            name="salary_reco_employe_892342_idx",
        ),
        migrations.AlterField(
            model_name="ingestrejectionstats",
            name="run",
            field=models.ForeignKey(
                db_index=False,
                help_text="Ingest run these rejections occurred in",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rejection_stats",
                to="models.ingestrun",
            ),
        ),
        migrations.AlterField(
            model_name="salaryrecord",
            name="employer_name",
            field=models.CharField(
                help_text="Employer name from DOL data", max_length=255
            ),
        ),
        migrations.AlterField(
            model_name="salaryrecord",
            name="job_title",
            field=models.CharField(help_text="Job title", max_length=255),
        ),
        # Declared BEFORE soc_code's AlterField, not after: dropping db_index makes
        # Django drop every index it introspects on the column that the model does
        # not yet declare, and on a database where 0058 has just run that is
        # sr_soc_code_pattern itself. Verified on staging, where the reverse order
        # left the migration reporting OK and the index gone.
        #
        # 0058 already built it, so only the state needs the declaration.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddIndex(
                    model_name="salaryrecord",
                    index=models.Index(
                        django.contrib.postgres.indexes.OpClass(
                            models.F("soc_code"), name="varchar_pattern_ops"
                        ),
                        name="sr_soc_code_pattern",
                    ),
                ),
            ],
        ),
        migrations.AlterField(
            model_name="salaryrecord",
            name="soc_code",
            field=models.CharField(
                blank=True,
                help_text="Standard Occupational Classification code",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="salaryrecord",
            name="source_file_date",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Date when source file was created/modified "
                    "(for duplicate resolution)"
                ),
                null=True,
            ),
        ),
        # source_file's varchar_pattern_ops index already exists under the name
        # Django derived from db_index=True. Dropping db_index and adding the
        # declaration would make Django drop and rebuild it — an AccessExclusiveLock
        # over 1.24 GB — for an index whose definition does not change, so the
        # database side is a rename, which is metadata only. The CREATE covers a
        # database that has neither, and is a no-op after the rename.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "DO $$ BEGIN "
                        "IF to_regclass('public.salary_record_source_file_a0692cee_like') "
                        "IS NOT NULL AND to_regclass('public.sr_source_file_pattern') IS NULL "
                        "THEN ALTER INDEX salary_record_source_file_a0692cee_like "
                        "RENAME TO sr_source_file_pattern; END IF; END $$;"
                    ),
                    reverse_sql=(
                        "DO $$ BEGIN "
                        "IF to_regclass('public.sr_source_file_pattern') IS NOT NULL "
                        "AND to_regclass('public.salary_record_source_file_a0692cee_like') "
                        "IS NULL THEN ALTER INDEX sr_source_file_pattern "
                        "RENAME TO salary_record_source_file_a0692cee_like; END IF; END $$;"
                    ),
                ),
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS sr_source_file_pattern "
                        "ON salary_record USING btree (source_file varchar_pattern_ops);"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="salaryrecord",
                    name="source_file",
                    field=models.CharField(
                        blank=True, help_text="Source CSV file name", max_length=255
                    ),
                ),
                migrations.AddIndex(
                    model_name="salaryrecord",
                    index=models.Index(
                        django.contrib.postgres.indexes.OpClass(
                            models.F("source_file"), name="varchar_pattern_ops"
                        ),
                        name="sr_source_file_pattern",
                    ),
                ),
            ],
        ),
        # The FK the rollback path deletes through: SalaryRecord.objects
        # .filter(ingest_version=v).delete() over 55 versions averaging ~30k rows,
        # and the SET_NULL sweep Django runs when an IngestVersion is deleted. Both
        # are a full scan of the 1.66M-row table without it. Declared by the model
        # all along, so a fresh database already has it and this is a repair.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "salary_record_ingest_version_id_ad9dc99b "
                "ON salary_record USING btree (ingest_version_id);"
            ),
            reverse_sql=(
                "DROP INDEX CONCURRENTLY IF EXISTS "
                "salary_record_ingest_version_id_ad9dc99b;"
            ),
        ),
    ]

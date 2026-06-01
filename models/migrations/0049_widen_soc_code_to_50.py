from django.db import migrations, models


class Migration(migrations.Migration):
    # Pure varchar length increase. In PostgreSQL, growing a varchar(N) limit
    # (or dropping it) is a catalog-only change — no table rewrite, no
    # AccessExclusiveLock beyond the brief catalog update — so this is safe on
    # the 1.5M-row salary_record without the CONCURRENTLY dance.
    dependencies = [
        ("models", "0048_job_title_cluster_canonical_title_trigram"),
    ]

    operations = [
        migrations.AlterField(
            model_name="salaryrecord",
            name="soc_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Standard Occupational Classification code",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="worksiterecord",
            name="soc_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Standard Occupational Classification code",
                max_length=50,
            ),
        ),
    ]

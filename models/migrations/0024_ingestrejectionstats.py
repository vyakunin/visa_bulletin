# Generated manually
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0023_jobtitlecluster_slug_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='IngestRejectionStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.CharField(choices=[('missing_case_number', 'Missing Case Number'), ('missing_employer_name', 'Missing Employer Name'), ('unknown_employer_name', 'Unknown Employer Name'), ('missing_job_title', 'Missing Job Title'), ('unknown_job_title', 'Unknown Job Title'), ('missing_wage_data', 'Missing Wage Data'), ('invalid_wage_unit', 'Invalid Wage Unit'), ('missing_dates', 'Missing Decision/Submit Dates'), ('invalid_date_sequence', 'Invalid Date Sequence'), ('missing_visa_class', 'Missing Visa Class'), ('whitelist_filtered', 'Filtered by Case Number Whitelist'), ('worksite_skipped', 'Worksite Record Skipped'), ('other', 'Other Rejection Reason')], help_text='Reason for rejection', max_length=50)),
                ('count', models.IntegerField(default=0, help_text='Number of records rejected for this reason')),
                ('sample_case_numbers', models.JSONField(default=list, help_text='Sample case numbers (up to 10) for investigation')),
                ('run', models.ForeignKey(help_text='Ingest run these rejections occurred in', on_delete=django.db.models.deletion.CASCADE, related_name='rejection_stats', to='models.ingestrun')),
            ],
            options={
                'verbose_name': 'Ingest Rejection Statistics',
                'verbose_name_plural': 'Ingest Rejection Statistics',
                'db_table': 'ingest_rejection_stats',
            },
        ),
        migrations.AddIndex(
            model_name='ingestrejectionstats',
            index=models.Index(fields=['run', 'reason'], name='ingest_reje_run_id_ae4b18_idx'),
        ),
        migrations.AddIndex(
            model_name='ingestrejectionstats',
            index=models.Index(fields=['run', 'count'], name='ingest_reje_run_id_e2c9d5_idx'),
        ),
        migrations.AddConstraint(
            model_name='ingestrejectionstats',
            constraint=models.UniqueConstraint(fields=('run', 'reason'), name='models_ingestrejectionstats_run_id_reason_4f2b6c_uniq'),
        ),
    ]

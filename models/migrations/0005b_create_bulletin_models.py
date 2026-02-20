# Generated migration to create Bulletin and VisaCutoffDate models
# These models must be created before 0007 (which references VisaCutoffDate)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0005_alter_ingestrun_stage_alter_ingestrun_status"),
        (
            "models",
            "0002_datasource_ingestrun_ingestversion_and_more",
        ),  # For IngestVersion FK
    ]

    operations = [
        migrations.CreateModel(
            name="Bulletin",
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
                    "publication_date",
                    models.DateField(
                        help_text="First day of the publication month (e.g., 2025-12-01)",
                        unique=True,
                    ),
                ),
                (
                    "url",
                    models.URLField(
                        blank=True,
                        help_text="URL to the official bulletin on travel.state.gov",
                        max_length=500,
                        null=True,
                    ),
                ),
                (
                    "fetched_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this bulletin was fetched and saved",
                    ),
                ),
            ],
            options={
                "db_table": "bulletin",
                "ordering": ["-publication_date"],
            },
        ),
        migrations.CreateModel(
            name="VisaCutoffDate",
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
                    "visa_category",
                    models.CharField(
                        choices=[
                            ("family_sponsored", "Family-Sponsored"),
                            ("employment_based", "Employment-Based"),
                        ],
                        help_text="Family-Sponsored or Employment-Based",
                        max_length=20,
                    ),
                ),
                (
                    "visa_class",
                    models.CharField(
                        help_text="F1, F2A, EB1, EB2, etc.", max_length=50
                    ),
                ),
                (
                    "action_type",
                    models.CharField(
                        choices=[
                            ("final_action", "Final Action"),
                            ("filing", "Dates for Filing"),
                        ],
                        help_text="Final Action or Dates for Filing",
                        max_length=20,
                    ),
                ),
                (
                    "country",
                    models.CharField(
                        choices=[
                            ("all", "Other Countries"),
                            ("china", "China (mainland born)"),
                            ("india", "India"),
                            ("mexico", "Mexico"),
                            ("philippines", "Philippines"),
                            (
                                "el_salvador_guatemala_honduras",
                                "El Salvador/Guatemala/Honduras",
                            ),
                        ],
                        help_text="Country/region for chargeability",
                        max_length=50,
                    ),
                ),
                (
                    "cutoff_value",
                    models.CharField(
                        help_text="Raw value: date string, 'C', or 'U'", max_length=20
                    ),
                ),
                (
                    "cutoff_date",
                    models.DateField(
                        blank=True, help_text="Parsed date (NULL for C/U)", null=True
                    ),
                ),
                (
                    "is_current",
                    models.BooleanField(
                        default=False, help_text="True if cutoff is 'C' (Current)"
                    ),
                ),
                (
                    "is_unavailable",
                    models.BooleanField(
                        default=False, help_text="True if cutoff is 'U' (Unavailable)"
                    ),
                ),
                (
                    "bulletin",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cutoff_dates",
                        to="models.bulletin",
                    ),
                ),
                (
                    "ingest_version",
                    models.ForeignKey(
                        blank=True,
                        help_text="Ingest version this record belongs to (for rollback)",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cutoff_dates",
                        to="models.ingestversion",
                    ),
                ),
            ],
            options={
                "db_table": "visa_cutoff_date",
                "ordering": ["bulletin", "visa_category", "visa_class", "country"],
                "unique_together": {
                    (
                        "bulletin",
                        "visa_category",
                        "visa_class",
                        "action_type",
                        "country",
                    )
                },
            },
        ),
        migrations.AddIndex(
            model_name="visacutoffdate",
            index=models.Index(
                fields=["visa_class", "country", "action_type", "bulletin"],
                name="visa_cutoff_visa_cl_4a8b2c_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="visacutoffdate",
            index=models.Index(
                fields=["visa_category", "country"],
                name="visa_cutoff_visa_ca_5c9d3e_idx",
            ),
        ),
    ]

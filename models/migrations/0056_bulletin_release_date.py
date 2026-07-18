"""Add the real State Department release date to Bulletin.

``publication_date`` is the governing month; ``fetched_at`` only approximates the
release date for live-ingested rows. These fields carry the release date itself
plus its provenance, so the "when does the next bulletin come out?" page can be
built on observed history instead of the handful of live ingests.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("models", "0055_reconcile_ingestrejectionstats"),
    ]

    operations = [
        migrations.AddField(
            model_name="bulletin",
            name="released_on",
            field=models.DateField(
                blank=True,
                db_index=True,
                help_text=(
                    "Date the State Department published this bulletin. See "
                    "released_on_source for provenance — wayback-sourced dates are "
                    "an upper bound."
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="bulletin",
            name="released_on_source",
            field=models.CharField(
                blank=True,
                choices=[
                    ("live", "Live ingest (fetched_at, exact to the day)"),
                    ("wayback", "Wayback first capture (upper bound)"),
                ],
                default="",
                help_text="Where released_on came from. Empty means unknown.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="bulletin",
            name="released_on_gap_days",
            field=models.IntegerField(
                blank=True,
                help_text=(
                    "Wayback rows only: days between the first and second archived "
                    "capture. A crawl-density proxy — a large gap means released_on "
                    "may overstate the real release date by a comparable margin."
                ),
                null=True,
            ),
        ),
    ]

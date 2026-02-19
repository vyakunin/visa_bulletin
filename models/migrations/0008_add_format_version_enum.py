# Generated migration to add FormatVersion enum to DataSource.format_version

import re

from django.db import migrations, models


def convert_years_to_format_versions(apps, schema_editor):
    """Convert year strings to FormatVersion enum values"""
    DataSource = apps.get_model('models', 'DataSource')

    for source in DataSource.objects.all():
        if not source.format_version or source.format_version == '':
            source.format_version = 'unknown'
        else:
            # Extract year from format_version string
            year_match = re.search(r'(\d{4})', source.format_version)
            if year_match:
                year = int(year_match.group(1))
                # Map year to format version
                # Visa bulletins changed format around 2015
                # DOL formats also changed around 2015
                if year < 2015:
                    source.format_version = 'legacy'
                else:
                    source.format_version = 'modern'
            else:
                source.format_version = 'unknown'
        source.save()


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0007_convert_enums_to_integers'),
    ]

    operations = [
        # First, convert existing year strings to format versions
        migrations.RunPython(convert_years_to_format_versions, migrations.RunPython.noop),

        # Then, update the field to use enum choices
        migrations.AlterField(
            model_name='datasource',
            name='format_version',
            field=models.CharField(
                choices=[('legacy', 'Legacy Format (2001-2014)'), ('modern', 'Modern Format (2015+)'), ('unknown', 'Unknown Format')],
                default='unknown',
                help_text='Schema format version (determines parser selection)',
                max_length=20
            ),
        ),
    ]











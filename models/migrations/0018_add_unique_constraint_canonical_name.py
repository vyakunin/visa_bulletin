# Generated migration for adding unique constraint to EmployerCluster.canonical_name

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0017_salaryrecord_source_file_date'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='employercluster',
            constraint=models.UniqueConstraint(
                fields=['canonical_name'],
                name='unique_canonical_name'
            ),
        ),
    ]


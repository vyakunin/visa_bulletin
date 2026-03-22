# Generated migration for movement_probability field on PredictedCutoff

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0041_predictedcutoff_model_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='predictedcutoff',
            name='movement_probability',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='P(|cutoff_move| > 50 days) from GBM classifier, at 1m horizon for oversubscribed series',
            ),
        ),
    ]

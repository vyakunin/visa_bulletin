from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias)


def drop_cache_table(apps, schema_editor):
    schema_editor.execute("DROP TABLE IF EXISTS precomputed_aggregate")


class Migration(migrations.Migration):

    dependencies = [
        ("models", "0060_delete_jobtitleclusteringreview"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]

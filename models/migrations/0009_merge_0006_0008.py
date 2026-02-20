# Generated migration to merge 0006 and 0008
# Both depend on 0007, creating a conflict that needs resolution

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0006_alter_salaryrecord_case_status_and_more"),
        ("models", "0008_add_format_version_enum"),
    ]

    operations = [
        # Merge migration - no operations needed, just resolves dependency conflict
    ]

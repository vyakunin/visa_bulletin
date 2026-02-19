# Generated manually to populate is_worksite field

from django.db import migrations


def populate_is_worksite(apps, schema_editor):
    """Populate is_worksite field based on source_file pattern"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')

    # Update all records in batches to avoid memory issues
    batch_size = 10000
    total_updated = 0

    # Get all records that should be marked as worksite
    # Use raw SQL for efficiency on large dataset
    with schema_editor.connection.cursor() as cursor:
        # Mark worksite records
        # Use database-agnostic boolean comparison
        # PostgreSQL uses boolean, SQLite uses integer (0/1)
        db_vendor = schema_editor.connection.vendor
        if db_vendor == 'postgresql':
            cursor.execute("""
                UPDATE salary_record 
                SET is_worksite = true 
                WHERE (source_file LIKE 'LCA_Worksites%' 
                       OR source_file LIKE '%_Worksites_%' 
                       OR source_file LIKE '%worksite%')
                AND is_worksite = false
            """)
        else:
            cursor.execute("""
                UPDATE salary_record 
                SET is_worksite = 1 
                WHERE (source_file LIKE 'LCA_Worksites%' 
                       OR source_file LIKE '%_Worksites_%' 
                       OR source_file LIKE '%worksite%')
                AND is_worksite = 0
            """)
        total_updated = cursor.rowcount

    print(f"Updated {total_updated} records with is_worksite=True")


def reverse_populate_is_worksite(apps, schema_editor):
    """Reverse: set all is_worksite to False"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')
    SalaryRecord.objects.all().update(is_worksite=False)


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0013_salaryrecord_is_worksite_alter_ingestrun_stage_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_is_worksite, reverse_populate_is_worksite),
    ]

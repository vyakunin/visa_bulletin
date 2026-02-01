# Generated migration to convert TextChoices to IntegerChoices
# This migration converts existing string values to integers atomically

from django.db import migrations


def convert_visa_program_to_int(apps, schema_editor):
    """Convert visa_program from string to integer"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')
    
    # Mapping: string -> integer
    visa_program_mapping = {
        'h1b': 0,
        'h1b1': 1,
        'e3': 2,
        'perm': 3,
    }
    
    # Update all records
    for string_value, int_value in visa_program_mapping.items():
        SalaryRecord.objects.filter(visa_program=string_value).update(visa_program=int_value)


def convert_case_status_to_int(apps, schema_editor):
    """Convert case_status from string to integer"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')
    
    # Mapping: string -> integer
    case_status_mapping = {
        'certified': 0,
        'denied': 1,
        'withdrawn': 2,
        'certified_withdrawn': 3,
    }
    
    # Update all records
    for string_value, int_value in case_status_mapping.items():
        SalaryRecord.objects.filter(case_status=string_value).update(case_status=int_value)


def convert_country_to_int(apps, schema_editor):
    """Convert country from string to integer"""
    VisaCutoffDate = apps.get_model('models', 'VisaCutoffDate')
    
    # Mapping: string -> integer
    country_mapping = {
        'all': 0,
        'china': 1,
        'india': 2,
        'mexico': 3,
        'philippines': 4,
        'el_salvador_guatemala_honduras': 5,
    }
    
    # Update all records
    for string_value, int_value in country_mapping.items():
        VisaCutoffDate.objects.filter(country=string_value).update(country=int_value)


def reverse_visa_program_to_string(apps, schema_editor):
    """Reverse: convert visa_program from integer to string"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')
    
    int_to_string = {
        0: 'h1b',
        1: 'h1b1',
        2: 'e3',
        3: 'perm',
    }
    
    for int_value, string_value in int_to_string.items():
        SalaryRecord.objects.filter(visa_program=int_value).update(visa_program=string_value)


def reverse_case_status_to_string(apps, schema_editor):
    """Reverse: convert case_status from integer to string"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')
    
    int_to_string = {
        0: 'certified',
        1: 'denied',
        2: 'withdrawn',
        3: 'certified_withdrawn',
    }
    
    for int_value, string_value in int_to_string.items():
        SalaryRecord.objects.filter(case_status=int_value).update(case_status=string_value)


def reverse_country_to_string(apps, schema_editor):
    """Reverse: convert country from integer to string"""
    VisaCutoffDate = apps.get_model('models', 'VisaCutoffDate')
    
    int_to_string = {
        0: 'all',
        1: 'china',
        2: 'india',
        3: 'mexico',
        4: 'philippines',
        5: 'el_salvador_guatemala_honduras',
    }
    
    for int_value, string_value in int_to_string.items():
        VisaCutoffDate.objects.filter(country=int_value).update(country=string_value)


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0005_alter_ingestrun_stage_alter_ingestrun_status'),
        ('models', '0005b_create_bulletin_models'),  # Bulletin and VisaCutoffDate must exist first
    ]

    operations = [
        # Convert data BEFORE changing field types
        migrations.RunPython(convert_visa_program_to_int, reverse_visa_program_to_string),
        migrations.RunPython(convert_case_status_to_int, reverse_case_status_to_string),
        migrations.RunPython(convert_country_to_int, reverse_country_to_string),
    ]











# Migration to reserve 0 for invalid/unknown in IntegerChoices
# Shifts all existing enum values by +1 to make room for INVALID = 0

from django.db import migrations


def shift_country_values(apps, schema_editor):
    """Shift all Country enum values by +1 (0->1, 1->2, ..., 5->6)"""
    VisaCutoffDate = apps.get_model('models', 'VisaCutoffDate')

    # Shift values: old -> new
    shifts = [
        (5, 6),  # EL_SALVADOR_GUATEMALA_HONDURAS: 5 -> 6
        (4, 5),  # PHILIPPINES: 4 -> 5
        (3, 4),  # MEXICO: 3 -> 4
        (2, 3),  # INDIA: 2 -> 3
        (1, 2),  # CHINA: 1 -> 2
        (0, 1),  # ALL: 0 -> 1
    ]

    for old_value, new_value in shifts:
        VisaCutoffDate.objects.filter(country=old_value).update(country=new_value)


def shift_visa_program_values(apps, schema_editor):
    """Shift all VisaProgram enum values by +1 (0->1, 1->2, 2->3, 3->4)"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')

    shifts = [
        (3, 4),  # PERM: 3 -> 4
        (2, 3),  # E3: 2 -> 3
        (1, 2),  # H1B1: 1 -> 2
        (0, 1),  # H1B: 0 -> 1
    ]

    for old_value, new_value in shifts:
        SalaryRecord.objects.filter(visa_program=old_value).update(visa_program=new_value)


def shift_case_status_values(apps, schema_editor):
    """Shift all CaseStatus enum values by +1 (0->1, 1->2, 2->3, 3->4)"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')

    shifts = [
        (3, 4),  # CERTIFIED_WITHDRAWN: 3 -> 4
        (2, 3),  # WITHDRAWN: 2 -> 3
        (1, 2),  # DENIED: 1 -> 2
        (0, 1),  # CERTIFIED: 0 -> 1
    ]

    for old_value, new_value in shifts:
        SalaryRecord.objects.filter(case_status=old_value).update(case_status=new_value)


def shift_ingest_status_values(apps, schema_editor):
    """Shift all IngestStatus enum values by +1 (0->1, 1->2, 2->3, 3->4, 4->5)"""
    IngestRun = apps.get_model('models', 'IngestRun')

    shifts = [
        (4, 5),  # CANCELLED: 4 -> 5
        (3, 4),  # FAILED: 3 -> 4
        (2, 3),  # COMPLETED: 2 -> 3
        (1, 2),  # RUNNING: 1 -> 2
        (0, 1),  # PENDING: 0 -> 1
    ]

    for old_value, new_value in shifts:
        IngestRun.objects.filter(status=old_value).update(status=new_value)


def shift_ingest_stage_values(apps, schema_editor):
    """Shift all IngestStage enum values by +1 (0->1, 1->2, 2->3, 3->4, 4->5, 5->6)"""
    IngestRun = apps.get_model('models', 'IngestRun')

    shifts = [
        (5, 6),  # COMPLETED: 5 -> 6
        (4, 5),  # LOADING: 4 -> 5
        (3, 4),  # TRANSFORMING: 3 -> 4
        (2, 3),  # PARSING: 2 -> 3
        (1, 2),  # DOWNLOADING: 1 -> 2
        (0, 1),  # PENDING: 0 -> 1
    ]

    for old_value, new_value in shifts:
        IngestRun.objects.filter(stage=old_value).update(stage=new_value)


def reverse_country_values(apps, schema_editor):
    """Reverse: shift Country enum values back by -1"""
    VisaCutoffDate = apps.get_model('models', 'VisaCutoffDate')

    shifts = [
        (1, 0),  # ALL: 1 -> 0
        (2, 1),  # CHINA: 2 -> 1
        (3, 2),  # INDIA: 3 -> 2
        (4, 3),  # MEXICO: 4 -> 3
        (5, 4),  # PHILIPPINES: 5 -> 4
        (6, 5),  # EL_SALVADOR_GUATEMALA_HONDURAS: 6 -> 5
    ]

    for new_value, old_value in shifts:
        VisaCutoffDate.objects.filter(country=new_value).update(country=old_value)


def reverse_visa_program_values(apps, schema_editor):
    """Reverse: shift VisaProgram enum values back by -1"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')

    shifts = [
        (1, 0),  # H1B: 1 -> 0
        (2, 1),  # H1B1: 2 -> 1
        (3, 2),  # E3: 3 -> 2
        (4, 3),  # PERM: 4 -> 3
    ]

    for new_value, old_value in shifts:
        SalaryRecord.objects.filter(visa_program=new_value).update(visa_program=old_value)


def reverse_case_status_values(apps, schema_editor):
    """Reverse: shift CaseStatus enum values back by -1"""
    SalaryRecord = apps.get_model('models', 'SalaryRecord')

    shifts = [
        (1, 0),  # CERTIFIED: 1 -> 0
        (2, 1),  # DENIED: 2 -> 1
        (3, 2),  # WITHDRAWN: 3 -> 2
        (4, 3),  # CERTIFIED_WITHDRAWN: 4 -> 3
    ]

    for new_value, old_value in shifts:
        SalaryRecord.objects.filter(case_status=new_value).update(case_status=old_value)


def reverse_ingest_status_values(apps, schema_editor):
    """Reverse: shift IngestStatus enum values back by -1"""
    IngestRun = apps.get_model('models', 'IngestRun')

    shifts = [
        (1, 0),  # PENDING: 1 -> 0
        (2, 1),  # RUNNING: 2 -> 1
        (3, 2),  # COMPLETED: 3 -> 2
        (4, 3),  # FAILED: 4 -> 3
        (5, 4),  # CANCELLED: 5 -> 4
    ]

    for new_value, old_value in shifts:
        IngestRun.objects.filter(status=new_value).update(status=old_value)


def reverse_ingest_stage_values(apps, schema_editor):
    """Reverse: shift IngestStage enum values back by -1"""
    IngestRun = apps.get_model('models', 'IngestRun')

    shifts = [
        (1, 0),  # PENDING: 1 -> 0
        (2, 1),  # DOWNLOADING: 2 -> 1
        (3, 2),  # PARSING: 3 -> 2
        (4, 3),  # TRANSFORMING: 4 -> 3
        (5, 4),  # LOADING: 5 -> 4
        (6, 5),  # COMPLETED: 6 -> 5
    ]

    for new_value, old_value in shifts:
        IngestRun.objects.filter(stage=new_value).update(stage=old_value)


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0011_alter_salaryrecord_source_file'),
    ]

    operations = [
        migrations.RunPython(shift_country_values, reverse_country_values),
        migrations.RunPython(shift_visa_program_values, reverse_visa_program_values),
        migrations.RunPython(shift_case_status_values, reverse_case_status_values),
        migrations.RunPython(shift_ingest_status_values, reverse_ingest_status_values),
        migrations.RunPython(shift_ingest_stage_values, reverse_ingest_stage_values),
    ]











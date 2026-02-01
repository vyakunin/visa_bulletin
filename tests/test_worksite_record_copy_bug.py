"""Test to reproduce the wage_to 'year' bug in COPY operation

This test reproduces the exact bug found in FY2024 Q1 ingestion at row 95467:
- COPY worksite_record, line 7466, column wage_to: "year"

The bug: wage_unit enum value is being written to wage_to column during COPY,
suggesting field order mismatch or improper enum-to-value conversion.
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from decimal import Decimal
from models.salary import WorksiteRecord, Employer
from models.enums.visa_program import VisaProgram, WageUnit, CaseStatus


def test_worksite_record_copy_bug_row_95467():
    """Reproduce the exact bug from row 96186 of FY2024 Q1
    
    The bug: soc_title with trailing backslash causes field misalignment in COPY.
    Example: 'Software Developers, Systems Software\' followed by TAB
    Without proper escaping, the backslash escapes the TAB, merging it into the field value.
    """
    
    # Clean up any existing record from previous test runs
    WorksiteRecord.objects.filter(case_number='I-200-20309-899072').delete()
    
    # Create WorksiteRecord with data from row 96186 - HAS TRAILING BACKSLASH IN SOC_TITLE
    record = WorksiteRecord(
        case_number='I-200-20309-899072',
        visa_program=VisaProgram.H1B,
        case_status=None,  # Can be NULL
        job_title='SOFTWARE ENGINEER',
        soc_code='15-1133.00',
        soc_title='Software Developers, Systems Software\\',  # ❗ TRAILING BACKSLASH - the bug!
        worksite_city='DEARBORN',
        worksite_state='MI',
        worksite_zip='',
        wage_from=Decimal('93184'),
        wage_to=None,
        wage_unit=WageUnit.YEAR,
        wage_annual=Decimal('93184'),
        prevailing_wage=Decimal('93184'),
        prevailing_wage_unit=WageUnit.YEAR,
        fiscal_year=2024,
    )
    
    # Check that wage fields are correct BEFORE saving
    assert record.wage_from == Decimal('93184')
    assert record.wage_to is None
    assert record.wage_unit == WageUnit.YEAR
    assert hasattr(record.wage_unit, 'value')
    assert record.wage_unit.value == 'year'
    assert record.soc_title == 'Software Developers, Systems Software\\'  # Verify trailing backslash
    
    print(f"✅ Record created successfully")
    print(f"   wage_from: {record.wage_from!r} (type: {type(record.wage_from).__name__})")
    print(f"   wage_to: {record.wage_to!r} (type: {type(record.wage_to).__name__})")
    print(f"   wage_unit: {record.wage_unit!r} (type: {type(record.wage_unit).__name__})")
    print(f"   wage_unit.value: {record.wage_unit.value!r}")
    
    # Now test the COPY operation by simulating what orchestrator does
    from io import StringIO
    buffer = StringIO()
    fields = [f for f in WorksiteRecord._meta.fields if not f.primary_key]
    field_names = [f.attname for f in fields]
    
    print(f"\n📋 Field order for COPY ({len(fields)} fields):")
    for i, f in enumerate(fields):
        print(f"   {i:2d}. {f.attname}")
    
    # Build COPY data like orchestrator does
    values = []
    for field in fields:
        value = getattr(record, field.attname, None)
        if value is None:
            values.append('')
            continue
        
        # Convert enum values to their string representation
        if hasattr(value, 'value'):
            original_value = value
            value = value.value
            print(f"   ⚙️  Converted {field.attname}: {original_value!r} -> {value!r}")
        
        # Check for DecimalField
        if isinstance(field, django.db.models.DecimalField):
            values.append(str(value))
        elif isinstance(value, str):
            # Escape for PostgreSQL COPY
            value = value.replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')
            values.append(value)
        else:
            values.append(str(value))
    
    # Create COPY line
    copy_line = '\t'.join(values)
    buffer.write(copy_line + '\n')
    
    print(f"\n📝 COPY line preview (first 500 chars):")
    print(f"   {copy_line[:500]}...")
    
    # Check specific wage field positions
    wage_from_idx = field_names.index('wage_from')
    wage_to_idx = field_names.index('wage_to')
    wage_unit_idx = field_names.index('wage_unit')
    
    print(f"\n🔍 Wage field positions:")
    print(f"   wage_from: position {wage_from_idx}, value: {values[wage_from_idx]!r}")
    print(f"   wage_to: position {wage_to_idx}, value: {values[wage_to_idx]!r}")
    print(f"   wage_unit: position {wage_unit_idx}, value: {values[wage_unit_idx]!r}")
    
    # THE BUG CHECK: Is 'year' being written to wage_to position?
    if values[wage_to_idx] == 'year':
        print(f"\n🐛 BUG REPRODUCED: 'year' is in wage_to position!")
        print(f"   This will cause: invalid input syntax for type numeric: \"year\"")
        assert False, "Bug reproduced: wage_unit value ('year') is in wage_to position"
    elif values[wage_to_idx] == '':
        print(f"\n✅ CORRECT: wage_to is empty (None)")
    else:
        print(f"\n⚠️  UNEXPECTED: wage_to has value {values[wage_to_idx]!r}")
    
    # Now test the ACTUAL COPY operation through PostgreSQL
    print(f"\n🔬 Testing actual PostgreSQL COPY operation...")
    try:
        from django.db import connection
        
        # Build column list for COPY
        columns = ','.join(field_names)
        table_name = WorksiteRecord._meta.db_table
        
        # Reset buffer
        buffer.seek(0)
        
        with connection.cursor() as cursor:
            cursor.copy_expert(
                f"COPY {table_name} ({columns}) FROM STDIN WITH (FORMAT TEXT, NULL '')",
                buffer
            )
        
        print(f"✅ COPY operation succeeded!")
        
        # Verify record was inserted correctly
        inserted = WorksiteRecord.objects.get(case_number='I-200-20309-899072')
        print(f"\n✅ Verification: Record inserted correctly")
        print(f"   wage_from: {inserted.wage_from}")
        print(f"   wage_to: {inserted.wage_to}")
        print(f"   wage_unit: {inserted.wage_unit}")
        
        # Clean up
        inserted.delete()
        
    except Exception as e:
        print(f"\n🐛 COPY operation FAILED: {e}")
        print(f"   This reproduces the production bug!")
        raise


if __name__ == '__main__':
    test_worksite_record_copy_bug_row_95467()

"""Test to reproduce the wage_to 'year' bug in COPY operation.

This test reproduces the exact bug found in FY2024 Q1 ingestion at row 95467:
- COPY worksite_record, line 7466, column wage_to: "year"

The bug: wage_unit enum value is being written to wage_to column during COPY,
suggesting field order mismatch or improper enum-to-value conversion.
"""

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

from django.db import connection, models

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.enums.visa_program import VisaProgram, WageUnit
from models.salary import WorksiteRecord


class TestWorksiteRecordCopyBug(TestCase):
    """Reproduce the exact bug from row 96186 of FY2024 Q1.

    The bug: soc_title with trailing backslash causes field misalignment in COPY.
    Example: 'Software Developers, Systems Software\' followed by TAB
    Without proper escaping, the backslash escapes the TAB, merging it into the field value.
    """

    def test_worksite_record_copy_bug_row_95467(self):
        WorksiteRecord.objects.filter(case_number="I-200-20309-899072").delete()

        record = WorksiteRecord(
            case_number="I-200-20309-899072",
            visa_program=VisaProgram.H1B,
            case_status=None,
            job_title="SOFTWARE ENGINEER",
            soc_code="15-1133.00",
            soc_title="Software Developers, Systems Software\\",
            worksite_city="DEARBORN",
            worksite_state="MI",
            worksite_zip="",
            wage_from=Decimal("93184"),
            wage_to=None,
            wage_unit=WageUnit.YEAR,
            wage_annual=Decimal("93184"),
            prevailing_wage=Decimal("93184"),
            prevailing_wage_unit=WageUnit.YEAR,
            fiscal_year=2024,
        )

        self.assertEqual(record.wage_from, Decimal("93184"))
        self.assertIsNone(record.wage_to)
        self.assertEqual(record.wage_unit, WageUnit.YEAR)
        self.assertEqual(record.wage_unit.value, "year")
        self.assertEqual(record.soc_title, "Software Developers, Systems Software\\")

        buffer = StringIO()
        now_ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S+00")
        # Exclude PK; include all others (auto_now fields need explicit values for COPY).
        fields = [f for f in WorksiteRecord._meta.fields if not f.primary_key]
        field_names = [f.attname for f in fields]

        # Use '\N' for SQL NULL so '' stays as empty string (worksite_zip is NOT NULL, blank=True).
        null_marker = "\\N"
        values = []
        for field in fields:
            if getattr(field, "auto_now_add", False) or getattr(
                field, "auto_now", False
            ):
                values.append(now_ts)
                continue
            value = getattr(record, field.attname, None)
            if value is None:
                values.append(null_marker)
                continue
            if hasattr(value, "value"):
                value = value.value
            if isinstance(field, models.DecimalField):
                values.append(str(value))
            elif isinstance(value, str):
                value = (
                    value.replace("\\", "\\\\")
                    .replace("\t", "\\t")
                    .replace("\n", "\\n")
                    .replace("\r", "\\r")
                )
                values.append(value)
            else:
                values.append(str(value))

        copy_line = "\t".join(values)
        buffer.write(copy_line + "\n")

        wage_to_idx = field_names.index("wage_to")
        self.assertNotEqual(
            values[wage_to_idx], "year", "Bug: wage_unit value in wage_to position"
        )
        self.assertEqual(values[wage_to_idx], "\\N", "wage_to is None -> null marker")

        buffer.seek(0)
        table_name = WorksiteRecord._meta.db_table
        columns = ",".join(field_names)
        with connection.cursor() as cursor:
            cursor.copy_expert(
                f"COPY {table_name} ({columns}) FROM STDIN WITH (FORMAT TEXT, NULL '\\N')",
                buffer,
            )

        inserted = WorksiteRecord.objects.get(case_number="I-200-20309-899072")
        self.assertEqual(inserted.wage_from, Decimal("93184"))
        self.assertIsNone(inserted.wage_to)
        self.assertEqual(inserted.wage_unit, WageUnit.YEAR)
        inserted.delete()


if __name__ == "__main__":
    unittest.main()

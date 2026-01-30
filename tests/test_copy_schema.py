"""Tests for ModelCopySchema field position lookups."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from lib.ingest.schema import ModelCopySchema
from models.salary import SalaryRecord


def test_schema_returns_positions_via_attributes():
    schema = ModelCopySchema.from_model(SalaryRecord)
    fields = [f for f in SalaryRecord._meta.fields if not f.primary_key]
    field_names = [f.attname for f in fields]

    assert schema.wage_from == field_names.index("wage_from")
    assert schema.wage_to == field_names.index("wage_to")
    assert schema.wage_unit == field_names.index("wage_unit")


def test_schema_invalid_attribute_raises():
    schema = ModelCopySchema.from_model(SalaryRecord)
    try:
        _ = schema.not_a_field
    except AttributeError as exc:
        assert "not_a_field" in str(exc)
    else:
        assert False, "Expected AttributeError for missing field"


def test_schema_get_field_position_explicit_method():
    schema = ModelCopySchema.from_model(SalaryRecord)
    fields = [f for f in SalaryRecord._meta.fields if not f.primary_key]
    field_names = [f.attname for f in fields]

    assert schema.get_field_position("case_number") == field_names.index("case_number")


def test_schema_cache_returns_same_instance():
    schema_one = ModelCopySchema.from_model(SalaryRecord)
    schema_two = ModelCopySchema.from_model(SalaryRecord)

    assert schema_one is schema_two

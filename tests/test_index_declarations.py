"""The database holds exactly the indexes the models declare.

The DB half is what catches a `db_index=True` added without a migration, or a
RunSQL index whose name no declaration matches. It runs against a freshly migrated
test database, so it pins migrations-vs-models and says nothing about a deployed
stack — an index dropped out of band there is only visible to
`scripts/db/audit_indexes` run against that stack.
"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import pytest  # noqa: E402

from lib.utils.index_audit import (  # noqa: E402
    DeclaredIndex,
    _index_columns,
    coverage_for,
)


def _declared(name, sql, unique=False):
    return DeclaredIndex(
        name=name,
        table="salary_record",
        model_label="models.SalaryRecord",
        sql=sql,
        is_unique=unique,
    )


class TestConcurrentSql:
    def test_rewrites_a_plain_create_to_a_re_runnable_online_build(self):
        index = _declared(
            "sr_x", 'CREATE INDEX "sr_x" ON "salary_record" ("soc_code")'
        )
        assert index.concurrent_sql() == (
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS "sr_x" ON "salary_record" ("soc_code")'
        )

    def test_keeps_the_unique_keyword(self):
        index = _declared(
            "sr_u",
            'CREATE UNIQUE INDEX "sr_u" ON "salary_record" ("case_number")',
            unique=True,
        )
        assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS" in index.concurrent_sql()

    def test_rewrites_only_the_leading_verb(self):
        # A column literally named like the verb must not be rewritten too.
        index = _declared(
            "sr_y", 'CREATE INDEX "sr_y" ON "t" ("a") WHERE note = \'CREATE INDEX \''
        )
        assert index.concurrent_sql().count("CONCURRENTLY") == 1


class TestIndexColumns:
    def test_reads_the_key_list_without_the_include_clause(self):
        assert (
            _index_columns(
                "CREATE INDEX x ON t USING btree (employer_id, is_worksite, fiscal_year) "
                "INCLUDE (wage_annual)"
            )
            == "employer_id, is_worksite, fiscal_year"
        )

    def test_strips_quoting_and_case(self):
        assert (
            _index_columns('CREATE INDEX "x" ON "t" ("Employer_Id", "is_worksite")')
            == "employer_id, is_worksite"
        )


class TestCoverage:
    ACTUAL = {
        "sr_emp_wk_fy_inc_wage": (
            "CREATE INDEX sr_emp_wk_fy_inc_wage ON public.salary_record USING btree "
            "(employer_id, is_worksite, fiscal_year) INCLUDE (wage_annual)"
        ),
        "sr_worksite_employer": (
            "CREATE INDEX sr_worksite_employer ON public.salary_record USING btree "
            "(worksite_state, employer_id)"
        ),
    }

    def test_names_a_composite_whose_leading_keys_match(self):
        missing = _declared(
            "sr_emp_wk",
            'CREATE INDEX "sr_emp_wk" ON "salary_record" ("employer_id", "is_worksite")',
        )
        assert coverage_for(missing, self.ACTUAL) == ["sr_emp_wk_fy_inc_wage"]

    def test_a_leading_column_alone_is_covered(self):
        missing = _declared(
            "sr_emp", 'CREATE INDEX "sr_emp" ON "salary_record" ("employer_id")'
        )
        assert coverage_for(missing, self.ACTUAL) == ["sr_emp_wk_fy_inc_wage"]

    def test_a_key_that_leads_nowhere_is_not_coverage(self):
        # fiscal_year is the third key of one index and absent from the other, and
        # a btree cannot be entered on a key its prefix does not reach.
        missing = _declared(
            "sr_fy", 'CREATE INDEX "sr_fy" ON "salary_record" ("fiscal_year")'
        )
        assert coverage_for(missing, self.ACTUAL) == []

    def test_a_longer_prefix_than_the_index_has_is_not_coverage(self):
        missing = _declared(
            "sr_ws_emp_fy",
            'CREATE INDEX "sr_ws_emp_fy" ON "salary_record" '
            '("worksite_state", "employer_id", "fiscal_year")',
        )
        assert coverage_for(missing, self.ACTUAL) == []


@pytest.mark.django_db
class TestDeclarationsMatchTheDatabase:
    def test_no_model_declares_an_index_the_migrations_do_not_build(self):
        from lib.utils.index_audit import audit

        gaps = {
            entry.table: [i.name for i in entry.missing]
            for entry in audit()
            if entry.missing
        }
        assert gaps == {}, (
            "Models declare indexes the migrated schema does not have. Either add the "
            "migration that builds them, or drop the declaration: " + repr(gaps)
        )

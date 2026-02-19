"""Golden test for DOL plugin transform methods.

Tests both PERM and H1B plugins' transform() methods using real file samples
with manually annotated expected results.

Usage:
    bazel test //tests:test_dol_transform_golden
    bazel test //tests:test_dol_transform_golden --test_filter=TestDOLTransformGolden.test_perm_cases
"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from pathlib import Path

import pytest
import yaml

from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from lib.utils.bazel_runfiles import get_data_file_path
from models.salary import SalaryRecord, WorksiteRecord


@pytest.mark.django_db
class TestDOLTransformGolden:
    """Golden test for PERM and H1B transform methods using real file samples"""

    @classmethod
    def load_test_data(cls) -> list[dict]:
        """Load golden test data from YAML file"""
        test_data_file = get_data_file_path('tests/data/dol_golden_test_data.yaml')

        if test_data_file is None:
            # Fallback: try workspace directory
            import os
            workspace_dir = os.environ.get('BUILD_WORKSPACE_DIRECTORY')
            if workspace_dir:
                test_data_file = Path(workspace_dir) / 'tests' / 'data' / 'dol_golden_test_data.yaml'
            else:
                raise FileNotFoundError("Could not find test data file: tests/data/dol_golden_test_data.yaml")

        with open(test_data_file) as f:
            data = yaml.safe_load(f)

        return data.get('test_cases', [])

    def serialize_record(self, record: SalaryRecord | WorksiteRecord | None) -> dict | None:
        """
        Serialize record to dict for comparison.
        
        Returns None if record is None, otherwise uses record.to_dict()
        """
        if record is None:
            return None
        return record.to_dict()

    def compare_records(
        self,
        actual: dict | None,
        expected: dict | None,
        record_type: str
    ) -> list[str]:
        """
        Compare actual and expected records, return list of differences.
        
        Args:
            actual: Actual serialized record (from transform())
            expected: Expected serialized record (from YAML)
            record_type: "SalaryRecord" or "WorksiteRecord"
        
        Returns:
            List of difference descriptions (empty if match)
        """
        differences = []

        # Handle None cases
        if actual is None and expected is None:
            return []  # Both None - match
        if actual is None and expected is not None:
            return [f"Expected {record_type} but got None"]
        if actual is not None and expected is None:
            return [f"Expected None but got {record_type}"]

        # Both are dicts - compare fields
        # Get all unique keys from both dicts
        all_keys = set(actual.keys()) | set(expected.keys())

        for key in sorted(all_keys):
            actual_val = actual.get(key)
            expected_val = expected.get(key)

            # Handle employer_id specially (may differ due to get_or_create)
            if key == 'employer_id' and record_type == 'SalaryRecord':
                # For SalaryRecord, we only check that employer_id is not None if expected is not None
                if expected_val is not None and actual_val is None:
                    differences.append(f"{key}: expected {expected_val} but got None")
                elif expected_val is None and actual_val is not None:
                    differences.append(f"{key}: expected None but got {actual_val}")
                # If both are not None, we don't compare exact values (employer creation may differ)
                continue

            # Compare values
            if actual_val != expected_val:
                differences.append(
                    f"{key}: expected {expected_val!r} but got {actual_val!r}"
                )

        return differences

    def test_all_golden_cases(self):
        """Test all golden test cases"""
        test_cases = self.load_test_data()

        assert len(test_cases) > 0, "No test cases found in golden test data"

        failures = []

        for i, test_case in enumerate(test_cases):
            plugin_type = test_case.get('plugin_type')
            record_type = test_case.get('record_type')
            input_dict = test_case.get('input', {})
            expected_result = test_case.get('expected_result')
            expected_error = test_case.get('expected_error')
            source_file = test_case.get('source_file', 'unknown')
            row_number = test_case.get('row_number', 'unknown')

            # Skip if not annotated yet
            if record_type is None:
                continue

            # Create plugin instance
            if plugin_type == 'PERM':
                plugin = PERMSalaryDataSourcePlugin(skip_clustering=True)
            elif plugin_type == 'H1B':
                plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
            else:
                failures.append(
                    f"Case {i+1} ({source_file}:{row_number}): Unknown plugin_type: {plugin_type}"
                )
                continue

            # Call transform()
            try:
                result = plugin.transform(input_dict)
            except Exception as e:
                failures.append(
                    f"Case {i+1} ({source_file}:{row_number}): Exception in transform(): {e}"
                )
                continue

            # Verify record type
            if record_type == 'SalaryRecord':
                if not isinstance(result, SalaryRecord):
                    failures.append(
                        f"Case {i+1} ({source_file}:{row_number}): "
                        f"Expected SalaryRecord but got {type(result).__name__}"
                    )
                    continue
            elif record_type == 'WorksiteRecord':
                if not isinstance(result, WorksiteRecord):
                    failures.append(
                        f"Case {i+1} ({source_file}:{row_number}): "
                        f"Expected WorksiteRecord but got {type(result).__name__}"
                    )
                    continue

            # Verify expected result
            if expected_error:
                # Should be None (validation failure)
                if result is not None:
                    failures.append(
                        f"Case {i+1} ({source_file}:{row_number}): "
                        f"Expected None (error: {expected_error}) but got {type(result).__name__}"
                    )
            else:
                # Should succeed - compare fields
                actual_dict = self.serialize_record(result)
                differences = self.compare_records(actual_dict, expected_result, record_type)

                if differences:
                    failures.append(
                        f"Case {i+1} ({source_file}:{row_number}): Field differences:\n"
                        + "\n".join(f"  - {d}" for d in differences)
                    )

        if failures:
            pytest.fail(
                f"Failed {len(failures)}/{len(test_cases)} test cases:\n\n"
                + "\n\n".join(failures)
            )

    def test_perm_cases(self):
        """Test only PERM cases"""
        test_cases = self.load_test_data()
        perm_cases = [tc for tc in test_cases if tc.get('plugin_type') == 'PERM']

        if not perm_cases:
            pytest.skip("No PERM test cases found")

        # Reuse test_all_golden_cases logic but filter to PERM
        plugin = PERMSalaryDataSourcePlugin(skip_clustering=True)
        failures = []

        for i, test_case in enumerate(perm_cases):
            record_type = test_case.get('record_type')
            input_dict = test_case.get('input', {})
            expected_result = test_case.get('expected_result')
            expected_error = test_case.get('expected_error')
            source_file = test_case.get('source_file', 'unknown')
            row_number = test_case.get('row_number', 'unknown')

            if record_type is None:
                continue

            try:
                result = plugin.transform(input_dict)
            except Exception as e:
                failures.append(
                    f"PERM case {i+1} ({source_file}:{row_number}): Exception: {e}"
                )
                continue

            if expected_error:
                if result is not None:
                    failures.append(
                        f"PERM case {i+1} ({source_file}:{row_number}): "
                        f"Expected None (error: {expected_error}) but got {type(result).__name__}"
                    )
            else:
                if not isinstance(result, SalaryRecord):
                    failures.append(
                        f"PERM case {i+1} ({source_file}:{row_number}): "
                        f"Expected SalaryRecord but got {type(result).__name__}"
                    )
                    continue

                actual_dict = self.serialize_record(result)
                differences = self.compare_records(actual_dict, expected_result, record_type)

                if differences:
                    failures.append(
                        f"PERM case {i+1} ({source_file}:{row_number}): Differences:\n"
                        + "\n".join(f"  - {d}" for d in differences)
                    )

        if failures:
            pytest.fail(f"Failed {len(failures)}/{len(perm_cases)} PERM cases:\n\n" + "\n\n".join(failures))

    def test_h1b_salary_cases(self):
        """Test only H1B SalaryRecord cases"""
        test_cases = self.load_test_data()
        h1b_salary_cases = [
            tc for tc in test_cases
            if tc.get('plugin_type') == 'H1B' and tc.get('record_type') == 'SalaryRecord'
        ]

        if not h1b_salary_cases:
            pytest.skip("No H1B SalaryRecord test cases found")

        plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
        failures = []

        for i, test_case in enumerate(h1b_salary_cases):
            input_dict = test_case.get('input', {})
            expected_result = test_case.get('expected_result')
            expected_error = test_case.get('expected_error')
            source_file = test_case.get('source_file', 'unknown')
            row_number = test_case.get('row_number', 'unknown')

            try:
                result = plugin.transform(input_dict)
            except Exception as e:
                failures.append(
                    f"H1B SalaryRecord case {i+1} ({source_file}:{row_number}): Exception: {e}"
                )
                continue

            if expected_error:
                if result is not None:
                    failures.append(
                        f"H1B SalaryRecord case {i+1} ({source_file}:{row_number}): "
                        f"Expected None (error: {expected_error}) but got {type(result).__name__}"
                    )
            else:
                if not isinstance(result, SalaryRecord):
                    failures.append(
                        f"H1B SalaryRecord case {i+1} ({source_file}:{row_number}): "
                        f"Expected SalaryRecord but got {type(result).__name__}"
                    )
                    continue

                actual_dict = self.serialize_record(result)
                differences = self.compare_records(actual_dict, expected_result, 'SalaryRecord')

                if differences:
                    failures.append(
                        f"H1B SalaryRecord case {i+1} ({source_file}:{row_number}): Differences:\n"
                        + "\n".join(f"  - {d}" for d in differences)
                    )

        if failures:
            pytest.fail(
                f"Failed {len(failures)}/{len(h1b_salary_cases)} H1B SalaryRecord cases:\n\n"
                + "\n\n".join(failures)
            )

    def test_h1b_worksite_cases(self):
        """Test only H1B WorksiteRecord cases (I-200 routing)"""
        test_cases = self.load_test_data()
        h1b_worksite_cases = [
            tc for tc in test_cases
            if tc.get('plugin_type') == 'H1B' and tc.get('record_type') == 'WorksiteRecord'
        ]

        if not h1b_worksite_cases:
            pytest.skip("No H1B WorksiteRecord test cases found")

        plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
        failures = []

        for i, test_case in enumerate(h1b_worksite_cases):
            input_dict = test_case.get('input', {})
            expected_result = test_case.get('expected_result')
            expected_error = test_case.get('expected_error')
            source_file = test_case.get('source_file', 'unknown')
            row_number = test_case.get('row_number', 'unknown')

            try:
                result = plugin.transform(input_dict)
            except Exception as e:
                failures.append(
                    f"H1B WorksiteRecord case {i+1} ({source_file}:{row_number}): Exception: {e}"
                )
                continue

            if expected_error:
                if result is not None:
                    failures.append(
                        f"H1B WorksiteRecord case {i+1} ({source_file}:{row_number}): "
                        f"Expected None (error: {expected_error}) but got {type(result).__name__}"
                    )
            else:
                if not isinstance(result, WorksiteRecord):
                    failures.append(
                        f"H1B WorksiteRecord case {i+1} ({source_file}:{row_number}): "
                        f"Expected WorksiteRecord but got {type(result).__name__}"
                    )
                    continue

                actual_dict = self.serialize_record(result)
                differences = self.compare_records(actual_dict, expected_result, 'WorksiteRecord')

                if differences:
                    failures.append(
                        f"H1B WorksiteRecord case {i+1} ({source_file}:{row_number}): Differences:\n"
                        + "\n".join(f"  - {d}" for d in differences)
                    )

        if failures:
            pytest.fail(
                f"Failed {len(failures)}/{len(h1b_worksite_cases)} H1B WorksiteRecord cases:\n\n"
                + "\n\n".join(failures)
            )


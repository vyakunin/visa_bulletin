#!/usr/bin/env python3
"""Regenerate the DOL transform golden baseline (tests/data/dol_golden_test_data.yaml).

The golden was hand-annotated before date-enrichment, employer get_or_create,
state-code normalization, the PERM/H1B employer-title preference, and wage-unit
annualization landed. Its `expected_result` for the 440 annotated non-error
cases drifted from current transform output. Every drift was verified
(2026-06-23) to be one of: None->value enrichment (dates, employer_id,
prevailing_wage_unit), worksite_state full-name->2-letter, the resolved
job_title employer-title preference, or the wage-unit annualization fix — with
ZERO field losses. With sign-off, this rebaselines `expected_result` from the
(now-correct) transform output so the golden becomes a live regression guard.

Only annotated, non-error cases are rebaselined. Cases with `expected_error`
(or record_type=None) are left untouched. If any previously-annotated case now
returns None or raises, the script ABORTS without writing — that would be a real
transform regression, not a benign drift.

Usage:
    bazel run //scripts/oneoff:regen_dol_golden
"""

import os
from pathlib import Path

import yaml

# Django apps must be configured before importing any models/plugins.
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin  # noqa: E402
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin  # noqa: E402
from lib.utils.logging_utils import log_context  # noqa: E402


def _golden_path() -> Path:
    workspace = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", os.getcwd()))
    return workspace / "tests" / "data" / "dol_golden_test_data.yaml"


def _serialize(record) -> dict | None:
    if record is None:
        return None
    return record.to_dict()


def main() -> int:
    log_context("Regenerate DOL transform golden baseline (verified-drift rebaseline)")
    setup_django_for_tests()

    path = _golden_path()
    data = yaml.safe_load(path.read_text())
    cases = data.get("test_cases", [])

    perm = PERMSalaryDataSourcePlugin(skip_clustering=True)
    h1b = H1BSalaryDataSourcePlugin(skip_clustering=True)

    regenerated = 0
    skipped_error = 0
    skipped_unannotated = 0
    regressions: list[str] = []

    for i, case in enumerate(cases):
        plugin_type = case.get("plugin_type")
        record_type = case.get("record_type")
        expected_error = case.get("expected_error")
        src = f"{case.get('source_file','?')}:{case.get('row_number','?')}"

        # Untouched: error cases and unannotated rows (test skips record_type=None).
        if expected_error or record_type is None:
            if expected_error:
                skipped_error += 1
            else:
                skipped_unannotated += 1
            continue

        plugin = perm if plugin_type == "PERM" else h1b
        try:
            result = plugin.transform(case.get("input", {}))
        except Exception as e:  # regression guard
            regressions.append(f"Case {i+1} ({src}): transform RAISED: {e}")
            continue

        if result is None:
            regressions.append(
                f"Case {i+1} ({src}): annotated {record_type} now transforms to None"
            )
            continue

        actual_type = type(result).__name__
        if actual_type != record_type:
            regressions.append(
                f"Case {i+1} ({src}): record_type {record_type} -> {actual_type}"
            )
            continue

        case["expected_result"] = _serialize(result)
        regenerated += 1

    if regressions:
        print(f"ABORT: {len(regressions)} regression(s) — NOT writing golden:")
        for r in regressions:
            print(f"  - {r}")
        return 1

    # Dump back, preserving key order and emitting block style.
    out = yaml.safe_dump(
        data, sort_keys=False, default_flow_style=False, allow_unicode=True, width=4096
    )
    path.write_text(out)

    print(
        f"Rebaselined {regenerated} annotated cases "
        f"(left {skipped_error} expected_error + {skipped_unannotated} unannotated untouched). "
        f"Wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

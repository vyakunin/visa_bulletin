from django.db import migrations

_INDEX = "i129_petition_dol_eta_idx"
_TABLE = "i129_petition"
_COL = "dol_eta_case_number"


def _concurrently(schema_editor) -> str:
    # Django names test databases "test_<name>". CREATE/DROP INDEX CONCURRENTLY
    # waits for all concurrent transactions on the table to finish; under the
    # parallel test-DB setup/teardown of the suite that wait hangs (60s timeout).
    # On a test DB the table is empty, so a plain index is instant and lock-free
    # anyway — only real deploys need CONCURRENTLY (online build on the ~373k-row
    # serving table, no AccessExclusiveLock; see deployment.md).
    name = schema_editor.connection.settings_dict.get("NAME") or ""
    return "" if name.startswith("test_") else "CONCURRENTLY"


def _create_index(apps, schema_editor):
    c = _concurrently(schema_editor)
    schema_editor.execute(
        f"CREATE INDEX {c} IF NOT EXISTS {_INDEX} ON {_TABLE} ({_COL});"
    )


def _drop_index(apps, schema_editor):
    c = _concurrently(schema_editor)
    schema_editor.execute(f"DROP INDEX {c} IF EXISTS {_INDEX};")


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("models", "0051_i129petition"),
    ]

    operations = [
        # Index the join column for the actual-pay comparison
        # (lib/business/i129/pay_comparison.py joins i129_petition to
        # worksite_record on dol_eta_case_number). Without it the planner
        # seq-scans ~373k petitions per query (~13s on staging); with it the
        # occupation-page comparison drops to ~0.4s. Emits CONCURRENTLY only on
        # real DBs (see _concurrently). Not declared in the model Meta on purpose
        # (raw-SQL index, same convention as migrations 0044-0048); makemigrations
        # only reconciles Meta-declared indexes, so this creates no drift.
        migrations.RunPython(_create_index, _drop_index),
    ]

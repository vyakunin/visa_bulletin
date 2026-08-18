"""Reconcile the indexes Django's model layer declares against the ones the database holds.

A declared index the database lacks is a lie in the model, and it is invisible to
migrations: nothing re-checks state that was changed out of band. The bulk-load
drop/restore in ``scripts/salary/manage_salary_indexes.py`` restores a snapshot of
what existed, so a loss ratchets — the snapshot is the loss.

``missing_indexes`` is the whole contract: declared-by-name minus present-by-name,
per table. ``coverage_for`` explains a gap without deciding it, since a prefix
match tells a human where to look and is not evidence that the gap is harmless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.apps import apps
from django.db import connection

# ``CREATE [UNIQUE] INDEX "name" ON "table" (cols) [INCLUDE (...)]`` — the shape
# every statement _model_indexes_sql emits takes, including the postgres backend's
# implicit ``_like`` companions for indexed text columns.
_CREATE_RE = re.compile(
    r'^CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+"(?P<name>[^"]+)"\s+ON\s+"(?P<table>[^"]+)"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeclaredIndex:
    """One index Django would create for a model, with the SQL that creates it."""

    name: str
    table: str
    model_label: str
    sql: str
    is_unique: bool

    def concurrent_sql(self) -> str:
        """The same statement as a re-runnable online build.

        CONCURRENTLY cannot run inside a transaction; the caller owns that.
        """
        verb = "CREATE UNIQUE INDEX " if self.is_unique else "CREATE INDEX "
        return self.sql.replace(verb, f"{verb}CONCURRENTLY IF NOT EXISTS ", 1)


@dataclass
class TableAudit:
    """Declared-vs-actual for one table."""

    table: str
    declared: list[DeclaredIndex] = field(default_factory=list)
    actual: dict[str, str] = field(default_factory=dict)

    @property
    def missing(self) -> list[DeclaredIndex]:
        return [d for d in self.declared if d.name not in self.actual]

    @property
    def undeclared(self) -> list[str]:
        """Indexes the database holds that no model declares.

        Informational: constraint-backing indexes and hand-written ones
        (trigram, opclass) legitimately live here.
        """
        names = {d.name for d in self.declared}
        return sorted(n for n in self.actual if n not in names)


def declared_indexes(model) -> list[DeclaredIndex]:
    """Every index Django would create for ``model``, as Django itself writes it.

    Uses the live schema editor rather than a re-derivation, so opclass companions,
    INCLUDE columns and Django's own name hashing are whatever this Django version
    actually produces.
    """
    label = model._meta.label
    out: list[DeclaredIndex] = []
    with connection.schema_editor(collect_sql=True) as editor:
        statements = editor._model_indexes_sql(model)
    for statement in statements:
        sql = str(statement)
        match = _CREATE_RE.match(sql)
        if not match:
            continue
        out.append(
            DeclaredIndex(
                name=match.group("name"),
                table=match.group("table"),
                model_label=label,
                sql=sql,
                is_unique=bool(match.group("unique")),
            )
        )
    return out


def actual_indexes(tables: list[str]) -> dict[str, dict[str, str]]:
    """``{table: {index_name: indexdef}}`` for the given tables, from pg_indexes."""
    if not tables:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = ANY(%s)",
            [list(tables)],
        )
        rows = cursor.fetchall()
    out: dict[str, dict[str, str]] = {t: {} for t in tables}
    for table, name, definition in rows:
        out.setdefault(table, {})[name] = definition
    return out


def _managed_models(table: str | None = None):
    for model in apps.get_models():
        if not model._meta.managed or model._meta.proxy:
            continue
        if table and model._meta.db_table != table:
            continue
        yield model


def audit(table: str | None = None) -> list[TableAudit]:
    """Audit one table, or every managed model's table when ``table`` is None."""
    by_table: dict[str, TableAudit] = {}
    for model in _managed_models(table):
        name = model._meta.db_table
        entry = by_table.setdefault(name, TableAudit(table=name))
        entry.declared.extend(declared_indexes(model))
    live = actual_indexes(sorted(by_table))
    for name, entry in by_table.items():
        entry.actual = live.get(name, {})
    return [by_table[t] for t in sorted(by_table)]


def _index_columns(indexdef: str) -> str:
    """The parenthesised key list of an indexdef, normalised for comparison."""
    start = indexdef.find("(")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(indexdef)):
        if indexdef[i] == "(":
            depth += 1
        elif indexdef[i] == ")":
            depth -= 1
            if depth == 0:
                body = indexdef[start + 1 : i]
                break
    else:
        return ""
    return ", ".join(
        part.strip().strip('"').lower() for part in body.split(",")
    )


def coverage_for(missing: DeclaredIndex, actual: dict[str, str]) -> list[str]:
    """Existing indexes whose leading keys start with the missing index's keys.

    A hint for the reader, never a verdict: a composite can serve a query on its
    leading columns, and an opclass index can serve equality but not ordering, so
    whether a prefix match makes the gap harmless is a question about the queries.
    """
    want = _index_columns(missing.sql)
    if not want:
        return []
    hits = []
    for name, definition in sorted(actual.items()):
        have = _index_columns(definition)
        if have == want or have.startswith(want + ", "):
            hits.append(name)
    return hits

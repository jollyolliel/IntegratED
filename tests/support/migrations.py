"""Replay the Alembic chain onto an empty database and diff it against the models.

Runs the real ``flask db upgrade`` — the migration ``flask release`` runs before
every deploy — in a subprocess pointed at a throwaway database through
``TEST_DATABASE_URL``, then reflects the result against ``db.metadata``.

A failed upgrade prints no traceback: ``migrations/env.py``'s ``fileConfig()``
disables the logger the app's excepthook reports through. The last
``Running upgrade X -> Y`` line in the output names the revision that failed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Columns no model maps any more but no migration drops yet: the revision serving during a
#: deploy still read them, so the drop ships one deploy later (docs/operations/database.md).
#: Remove an entry in the same change as the migration that drops its column.
AWAITING_DROP = {
    ("remove_column", "schools", "invite_code_expires_at"),
}

def flask_db(database_url: str, *args: str) -> subprocess.CompletedProcess:
    """Run ``flask db <args>`` against ``database_url`` in a fresh process."""

    return flask_command(database_url, "db", *args)


def flask_command(database_url: str, *args: str, bucket: str | None = None) -> subprocess.CompletedProcess:
    """Run ``flask <args>`` against ``database_url`` in a fresh process, with ``bucket`` as its dev bucket."""

    env = {
        key: value
        for key, value in os.environ.items()
        # Any of these would point the app at a production database instead.
        if key not in {"DATABASE_URL", "APP_ENV"}
    }
    env.update(APP_ENV="development", TEST_DATABASE_URL=database_url, POSTHOG_API_KEY="")
    if bucket is not None:
        env["LOCAL_BUCKET_DIR"] = bucket
    return subprocess.run(
        [sys.executable, "-m", "flask", "--app", "main", *args],
        check=False,  # the caller asserts on returncode and reports stderr
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def _describe(diff) -> tuple:
    """Reduce one Alembic diff entry to a comparable, readable tuple."""

    if isinstance(diff, list):  # modify_* entries arrive grouped per column
        kind, _schema, table, column = diff[0][:4]
        return (kind, table, column)
    kind, subject = diff[0], diff[-1]
    if kind in {"add_table", "remove_table"}:
        return (kind, subject.name)
    if kind in {"add_column", "remove_column"}:
        return (kind, diff[2], subject.name)
    if kind in {"add_index", "remove_index", "add_constraint", "remove_constraint"}:
        return (kind, subject.table.name, subject.name)
    if kind in {"add_fk", "remove_fk"}:
        return (kind, subject.table.name, tuple(c.name for c in subject.columns), subject.referred_table.name)
    return (kind, repr(diff))


def _unique_column_sets(inspector, table_name: str) -> set[tuple[str, ...]]:
    constraints = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table_name)}
    indexes = {tuple(i["column_names"]) for i in inspector.get_indexes(table_name) if i["unique"]}
    return constraints | indexes


def _model_unique_column_sets(table) -> set[tuple[str, ...]]:
    import sqlalchemy as sa

    constraints = {
        tuple(c.name for c in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    indexes = {tuple(c.name for c in index.columns) for index in table.indexes if index.unique}
    return constraints | indexes


def _uniqueness_drift(inspector, metadata) -> set[tuple]:
    """Unique column sets that differ between the database and the models.

    Alembic skips *unnamed* unique constraints when comparing on SQLite, so a
    leftover `UNIQUE (learner_id)` is invisible to `compare_metadata` there.
    """

    drift = set()
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        actual = _unique_column_sets(inspector, table.name)
        declared = _model_unique_column_sets(table)
        drift |= {("remove_unique", table.name, cols) for cols in actual - declared}
        drift |= {("add_unique", table.name, cols) for cols in declared - actual}
    return drift


def drift_from_models(database_url: str) -> set[tuple]:
    import sqlalchemy as sa
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from extensions import db

    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            drift = {_describe(diff) for diff in compare_metadata(context, db.metadata)}
            drift |= _uniqueness_drift(sa.inspect(connection), db.metadata)
    finally:
        engine.dispose()
    # Alembic's own bookkeeping table is not a model.
    drift.discard(("remove_table", "alembic_version"))
    return drift - AWAITING_DROP

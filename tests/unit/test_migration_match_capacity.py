import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _migration():
    path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "b6d4f2a91c05_volunteer_match_capacity.py"
    )
    spec = importlib.util.spec_from_file_location("match_capacity_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeInspector:
    """Stands in for sa.inspect(conn) — only the two reflection calls the
    migration's unique-constraint lookup makes."""

    def __init__(self, unique_constraints, indexes):
        self._unique_constraints = unique_constraints
        self._indexes = indexes

    def get_unique_constraints(self, table):
        assert table == "learners"
        return self._unique_constraints

    def get_indexes(self, table):
        assert table == "learners"
        return self._indexes


def test_postgres_backing_index_is_not_dropped_twice():
    """Postgres reports a UNIQUE constraint and the index backing it under the
    same name. DROP CONSTRAINT already removes that index, so a following
    DROP INDEX raises UndefinedObject and rolls the whole migration back."""
    migration = _migration()
    inspector = _FakeInspector(
        unique_constraints=[
            {"name": "learners_volunteer_id_key", "column_names": ["volunteer_id"]}
        ],
        indexes=[
            {
                "name": "learners_volunteer_id_key",
                "column_names": ["volunteer_id"],
                "unique": True,
            }
        ],
    )

    assert migration._drop_plan(inspector) == ("learners_volunteer_id_key", None)


def test_separately_named_unique_index_is_still_dropped():
    migration = _migration()
    inspector = _FakeInspector(
        unique_constraints=[
            {"name": "uq_learners_volunteer_id", "column_names": ["volunteer_id"]}
        ],
        indexes=[
            {
                "name": "ix_learners_volunteer_id_unique",
                "column_names": ["volunteer_id"],
                "unique": True,
            }
        ],
    )

    assert migration._drop_plan(inspector) == (
        "uq_learners_volunteer_id",
        "ix_learners_volunteer_id_unique",
    )


def test_unique_index_without_a_constraint_is_dropped():
    migration = _migration()
    inspector = _FakeInspector(
        unique_constraints=[],
        indexes=[
            {
                "name": "ix_learners_volunteer_id_unique",
                "column_names": ["volunteer_id"],
                "unique": True,
            }
        ],
    )

    assert migration._drop_plan(inspector) == (None, "ix_learners_volunteer_id_unique")


def test_nothing_to_drop_once_the_uniqueness_is_gone():
    migration = _migration()
    inspector = _FakeInspector(
        unique_constraints=[],
        indexes=[
            {
                "name": "ix_learners_volunteer_id",
                "column_names": ["volunteer_id"],
                "unique": False,
            }
        ],
    )

    assert migration._drop_plan(inspector) == (None, None)

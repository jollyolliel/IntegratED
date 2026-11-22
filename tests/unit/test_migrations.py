import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _migration():
    path = Path(__file__).parents[2] / "migrations" / "versions" / "f8ed8d0dea3d_per_person_attendance_records.py"
    spec = importlib.util.spec_from_file_location("attendance_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_attendance_migration_adds_learner_row_without_a_volunteer():
    migration = _migration()

    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE attendance (
            id INTEGER PRIMARY KEY, date TEXT NOT NULL, duration REAL NOT NULL,
            teacher_id INTEGER NOT NULL, learner_id INTEGER NOT NULL,
            volunteer_id INTEGER, status TEXT NOT NULL DEFAULT 'present', notes TEXT,
            volunteer_status TEXT, volunteer_duration REAL, volunteer_notes TEXT,
            user_id INTEGER, partner_id INTEGER, is_present BOOLEAN
        )"""
    )
    connection.execute("INSERT INTO attendance (date, duration, teacher_id, learner_id) VALUES ('2026-08-10', 1.5, 1, 4)")
    connection.commit()

    connection.execute(migration.BACKFILL_UPDATE_SQL)
    connection.execute(migration.BACKFILL_INSERT_SQL)

    assert connection.execute("SELECT user_id, duration FROM attendance").fetchall() == [(4, 1.5)]

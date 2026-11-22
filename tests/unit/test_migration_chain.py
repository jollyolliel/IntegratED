"""Static checks over ``migrations/versions/`` that need no database."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"

#: `ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS` parse on Postgres only;
#: SQLite rejects them, so a revision using them can never replay in dev.
POSTGRES_ONLY_COLUMN_DDL = re.compile(r"\b(ADD|DROP)\s+COLUMN\s+IF\s+(NOT\s+)?EXISTS\b", re.IGNORECASE)


def test_no_revision_emits_postgres_only_column_ddl():
    offenders = sorted(
        path.name
        for path in VERSIONS.glob("*.py")
        if POSTGRES_ONLY_COLUMN_DDL.search(path.read_text(encoding="utf-8"))
    )

    assert offenders == []

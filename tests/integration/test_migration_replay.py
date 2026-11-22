"""The Alembic chain alone builds what ``models.py`` declares, from an empty SQLite file.

The Postgres twin is ``test_migration_replay_postgres.py``.
"""

import pytest

pytestmark = pytest.mark.integration


def test_the_chain_builds_the_models_schema_from_base_on_sqlite(app, tmp_path):
    from tests.support.migrations import drift_from_models, flask_db

    database_url = f"sqlite:///{(tmp_path / 'replay.db').as_posix()}"

    result = flask_db(database_url, "upgrade")

    assert result.returncode == 0, result.stderr[-4000:]
    assert drift_from_models(database_url) == set()

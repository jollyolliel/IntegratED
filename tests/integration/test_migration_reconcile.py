"""The schema-reconciliation revision, against databases that did not come from replay.

Prod and every dev database were built by ``db.create_all()`` at some point, so
the revision has to be a no-op where the shape is already right, and has to
clear rows the new ``learning_sessions.lesson_id`` foreign key would reject.
"""

import pytest

pytestmark = pytest.mark.integration

#: The head before the reconciliation revision.
PREVIOUS_HEAD = "cf3700945711"


def test_reconciling_a_create_all_database_changes_nothing(app, tmp_path):
    import sqlalchemy as sa

    from extensions import db
    from tests.support.migrations import drift_from_models, flask_db

    database_url = f"sqlite:///{(tmp_path / 'create_all.db').as_posix()}"
    engine = sa.create_engine(database_url)
    db.metadata.create_all(engine)
    engine.dispose()
    assert flask_db(database_url, "stamp", PREVIOUS_HEAD).returncode == 0

    result = flask_db(database_url, "upgrade")

    assert result.returncode == 0, result.stderr[-4000:]
    assert drift_from_models(database_url) == set()


def test_reconciling_drops_sessions_whose_lesson_no_longer_exists(app, tmp_path):
    import sqlalchemy as sa

    from tests.support.migrations import flask_db

    database_url = f"sqlite:///{(tmp_path / 'orphans.db').as_posix()}"
    assert flask_db(database_url, "upgrade", PREVIOUS_HEAD).returncode == 0
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO learning_sessions (id, learner_id, session_type, lesson_id, subject_state, asked_ids, history) "
            "VALUES (1, 1, 'placement', NULL, '{}', '[]', '[]'), (2, 2, 'quiz', 999, '{}', '[]', '[]')"
        ))

    result = flask_db(database_url, "upgrade")

    assert result.returncode == 0, result.stderr[-4000:]
    with engine.connect() as connection:
        remaining = connection.execute(sa.text("SELECT id FROM learning_sessions ORDER BY id")).scalars().all()
    engine.dispose()
    # The orphan (2) is gone; so is the placement session (1), which b5e2d8a4c7f3 clears once on purpose.
    assert remaining == []

"""Fast schema and database isolation fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def schema(app):
    from extensions import db

    with app.app_context():
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def db_session(app, schema):
    """An empty database, inside one application context.

    Cleaning and the session share a single context on purpose: pushing a
    second one per test bought nothing and the push/pop is a measurable
    fraction of a fast test's runtime.

    Rows are cleared on setup rather than teardown, so a failing test leaves
    its data behind to inspect and the next test cleans up.
    """

    from extensions import db

    from .factories import reset_sequences

    with app.app_context():
        db.session.remove()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        reset_sequences()
        yield db.session
        db.session.remove()


@pytest.fixture
def clean_database(db_session):
    """An empty database for a test that needs no session handle."""

    return db_session


@pytest.fixture
def isolated_database(app):
    """A fresh schema for tests that explicitly exercise schema operations."""

    from extensions import db

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()
        # Restore the session-wide schema for tests that follow this explicit
        # destructive boundary fixture.
        db.create_all()

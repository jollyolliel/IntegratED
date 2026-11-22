"""The Alembic chain alone builds what ``models.py`` declares, on real Postgres.

Marked ``external`` only — never part of ``--suite=all``. CI's ``migrations``
job runs it against a ``postgres:17`` service container (Neon's major version);
locally, point ``MIGRATION_TEST_POSTGRES_URL`` at an empty database and run
``uv run -m pytest --suite=external``.
"""

import os

import pytest

pytestmark = pytest.mark.external

POSTGRES_URL_ENV = "MIGRATION_TEST_POSTGRES_URL"


def test_the_chain_builds_the_models_schema_from_base_on_postgres(app):
    import sqlalchemy as sa

    from main import sqlalchemy_database_url
    from tests.support.migrations import drift_from_models, flask_db

    database_url = os.environ.get(POSTGRES_URL_ENV)
    assert database_url, f"{POSTGRES_URL_ENV} must name an empty Postgres database"
    database_url = sqlalchemy_database_url(database_url)
    engine = sa.create_engine(database_url)
    try:
        existing = sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()
    assert existing == [], f"refusing to replay migrations into a non-empty database: {existing}"

    result = flask_db(database_url, "upgrade")

    assert result.returncode == 0, result.stderr[-4000:]
    assert drift_from_models(database_url) == set()

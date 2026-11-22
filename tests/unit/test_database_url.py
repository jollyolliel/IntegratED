"""How a Postgres URL from the environment is handed to SQLAlchemy."""

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw", ["postgres://u:pw@host/db", "postgresql://u:pw@host/db"])
def test_a_bare_postgres_url_loads_the_installed_psycopg2_driver(raw):
    # SQLAlchemy 2.1 maps a bare postgresql:// to psycopg 3, which is not a dependency.
    import sqlalchemy as sa

    from main import sqlalchemy_database_url

    assert sa.engine.make_url(sqlalchemy_database_url(raw)).get_dialect().driver == "psycopg2"


def test_the_rest_of_the_url_is_kept():
    from main import sqlalchemy_database_url

    url = sqlalchemy_database_url("postgres://u:pw@host:5432/db?sslmode=require")

    assert url == "postgresql+psycopg2://u:pw@host:5432/db?sslmode=require"


@pytest.mark.parametrize(
    "url",
    ["postgresql+psycopg://u@host/db", "postgresql+psycopg2://u@host/db", "sqlite:///instance/site.db"],
)
def test_a_url_that_already_names_its_driver_is_left_alone(url):
    from main import sqlalchemy_database_url

    assert sqlalchemy_database_url(url) == url

"""The administrator database console (routes/administrator/db_console.py): the SQL guard, the
table browser and its foreign-key links, and export/import."""

from __future__ import annotations

import io
import json

import pytest
from sqlalchemy import func, select

from tests.support.assertions import assert_redirects_to, assert_success
from tests.support.factories import (
    make_school,
    make_teacher,
)

pytestmark = pytest.mark.web


# ── the SQL guard ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "  select * from users  ",
        "/* comment */ SELECT 1",
        "-- note\nSELECT 1",
        "SELECT 1;",
    ],
)
def test_read_only_statements_are_allowed(app, sql):
    from routes.administrator import _safe_is_select

    assert _safe_is_select(sql) is True


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM users",
        "DROP TABLE users",
        "UPDATE users SET name = 'x'",
        "INSERT INTO users (id) VALUES (1)",
        "SELECT 1; DROP TABLE users",
        "/* SELECT */ DELETE FROM users",
        "",
    ],
)
def test_writes_and_stacked_statements_are_refused(app, sql):
    """The console is read-only; a stacked statement must not slip past."""

    from routes.administrator import _safe_is_select

    assert _safe_is_select(sql) is False


def test_the_query_console_runs_a_select(client, db_session, authenticated_admin):
    make_school(db_session, name="Queryable")

    body = assert_success(
        client.post("/admin/db/query", data={"sql": "SELECT name FROM schools"})
    ).get_data(as_text=True)

    assert "Queryable" in body


def test_the_query_console_refuses_a_write(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="Keep Me")

    client.post("/admin/db/query", data={"sql": "DELETE FROM schools"})

    assert db_session.scalar(select(func.count()).select_from(School)) == 1


# ── the table browser ────────────────────────────────────────────────────────


def test_the_table_browser_renders_rows(client, db_session, authenticated_admin):
    make_school(db_session, name="Browsable")

    body = assert_success(client.get("/admin/db/table/schools")).get_data(as_text=True)

    assert "Browsable" in body


def test_an_unknown_table_is_a_404(client, authenticated_admin):
    assert client.get("/admin/db/table/not_a_table").status_code == 404


def test_the_table_browser_paginates(client, db_session, authenticated_admin):
    for index in range(3):
        make_school(db_session, name=f"School {index}")

    assert_success(client.get("/admin/db/table/schools?page=2"))


def test_an_out_of_range_table_page_clamps_to_the_last_page_and_highlights_it(
    client, db_session, authenticated_admin, monkeypatch
):
    from routes.administrator import db_console

    monkeypatch.setattr(db_console, "_DB_PAGE_SIZE", 2)
    for index in range(5):
        make_school(db_session, name=f"School {index}")

    # 5 rows at page size 2 -> 3 pages; ?page=999 clamps to the last one.
    body = assert_success(client.get("/admin/db/table/schools?page=999")).get_data(as_text=True)

    assert "page 3/3" in body
    assert 'aria-current="page"' in body


def test_a_row_can_be_edited(client, db_session, authenticated_admin):
    from models import School

    school = make_school(db_session, name="Before")

    response = client.post(
        "/admin/db/table/schools/update-row",
        json={"pk": {"id": school.id}, "updates": {"name": "After"}},
    )

    assert_success(response)
    db_session.expire_all()
    assert db_session.get(School, school.id).name == "After"


def test_editing_without_a_primary_key_is_refused(client, authenticated_admin):
    response = client.post(
        "/admin/db/table/schools/update-row", json={"updates": {"name": "x"}}
    )

    assert response.status_code == 400


def test_editing_an_unknown_table_is_a_404(client, authenticated_admin):
    response = client.post(
        "/admin/db/table/nope/update-row", json={"pk": {"id": 1}, "updates": {"a": "b"}}
    )

    assert response.status_code == 404


def test_a_row_can_be_deleted(client, db_session, authenticated_admin):
    from models import School

    school_id = make_school(db_session).id

    response = client.post(
        "/admin/db/table/schools/delete-row", json={"pk": {"id": school_id}}
    )

    assert_success(response)
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(School).filter_by(id=school_id)) == 0


def test_deleting_a_row_that_matches_nothing_is_a_404(client, db_session, authenticated_admin):
    response = client.post(
        "/admin/db/table/schools/delete-row", json={"pk": {"id": 999999}}
    )

    assert response.status_code == 404


def test_a_row_can_be_added(client, db_session, authenticated_admin):
    from models import School

    response = client.post(
        "/admin/db/table/schools/add-row", json={"row": {"name": "Inserted"}}
    )

    assert_success(response)
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(School).filter_by(name="Inserted")) == 1


def test_adding_a_row_with_no_data_is_refused(client, authenticated_admin):
    assert client.post("/admin/db/table/schools/add-row", json={}).status_code == 400


def test_a_failing_insert_reports_the_error(client, db_session, authenticated_admin):
    """A NOT NULL violation must come back as a JSON error, not a 500 page."""

    response = client.post(
        "/admin/db/table/schools/add-row", json={"row": {"mission_statement": "no name"}}
    )

    assert response.status_code == 500
    error = response.get_json()["error"]
    assert error
    # The driver's own text (SQL, constraint and driver names) stays in the server log.
    assert "NOT NULL" not in error
    assert "sqlite" not in error.lower()


# ── identifiers in request bodies never reach the SQL unchecked ──────────────


def test_editing_an_unknown_column_is_refused(client, db_session, authenticated_admin):
    from models import School

    school = make_school(db_session, name="Before")

    response = client.post(
        "/admin/db/table/schools/update-row",
        json={"pk": {"id": school.id}, "updates": {'name" = \'x\', "id': "7"}},
    )

    assert response.status_code == 400
    db_session.expire_all()
    assert db_session.get(School, school.id).name == "Before"


def test_editing_by_a_column_that_is_not_the_primary_key_is_refused(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="One")
    make_school(db_session, name="Two")

    response = client.post(
        "/admin/db/table/schools/update-row",
        json={"pk": {"name": "One"}, "updates": {"name": "Changed"}},
    )

    assert response.status_code == 400
    db_session.expire_all()
    assert sorted(s.name for s in db_session.scalars(select(School))) == ["One", "Two"]


def test_deleting_by_an_unknown_column_is_refused(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session)

    response = client.post(
        "/admin/db/table/schools/delete-row", json={"pk": {'id" OR 1=1 --': 1}}
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(School)) == 1


def test_adding_a_row_with_an_unknown_column_is_refused(client, db_session, authenticated_admin):
    from models import School

    response = client.post(
        "/admin/db/table/schools/add-row", json={"row": {"name": "x", 'nope") --': "y"}}
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(School)) == 0


def test_importing_rows_with_an_unknown_column_changes_nothing(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="Kept")

    client.post(
        "/admin/db/import",
        data=_upload([{"id": 42, 'name") --': "x"}], mode="replace_table", table_name="schools"),
        content_type="multipart/form-data",
    )

    db_session.expire_all()
    assert [s.name for s in db_session.scalars(select(School))] == ["Kept"]


# ── the query console is read-only even past the SELECT guard ────────────────


def test_the_query_console_runs_on_a_read_only_connection(client, db_session, authenticated_admin, monkeypatch):
    """`_safe_is_select` is a prefix check; the connection itself must refuse a write it misses."""
    from models import School
    from routes.administrator import db_console

    make_school(db_session, name="Keep Me")
    monkeypatch.setattr(db_console, "_safe_is_select", lambda _sql: True)

    body = assert_success(
        client.post("/admin/db/query", data={"sql": "DELETE FROM schools"})
    ).get_data(as_text=True)

    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(School)) == 1
    assert "read-only" in body.lower() or "readonly" in body.lower()


def test_the_database_is_writable_again_after_a_console_query(client, db_session, authenticated_admin):
    from models import School

    client.post("/admin/db/query", data={"sql": "SELECT 1"})

    make_school(db_session, name="Written After")
    assert db_session.scalar(select(func.count()).select_from(School)) == 1


def test_an_unterminated_comment_is_refused_quickly(app):
    """Linear in the input: no quadratic rescans of `/*` on a hostile string."""
    import time

    from routes.administrator import _safe_is_select

    started = time.perf_counter()
    assert _safe_is_select("/*" + "a/*" * 50_000) is False
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("sql", "allowed"),
    [
        ("/* a */ /* b */ SELECT 1", True),
        ("/* unterminated SELECT 1", False),
        ("SELECT 1 /* trailing ; */", True),
        ("SELECT 1 -- ; DROP TABLE users", True),
        ("/* x */ DROP TABLE users /* SELECT */", False),
    ],
)
def test_comments_are_stripped_before_the_guard_decides(app, sql, allowed):
    from routes.administrator import _safe_is_select

    assert _safe_is_select(sql) is allowed


# ── export and import ────────────────────────────────────────────────────────


def test_the_full_database_exports_as_json(client, db_session, authenticated_admin):
    make_school(db_session, name="Exported")

    response = assert_success(client.get("/admin/db/export"))

    payload = json.loads(response.get_data(as_text=True))
    assert any(row["name"] == "Exported" for row in payload["schools"])
    assert "attachment" in response.headers["Content-Disposition"]


def test_one_table_exports_as_json(client, db_session, authenticated_admin):
    make_school(db_session, name="Solo")

    response = assert_success(client.get("/admin/db/export/schools"))

    assert [row["name"] for row in json.loads(response.get_data(as_text=True))] == ["Solo"]


def test_exporting_an_unknown_table_is_a_404(client, authenticated_admin):
    assert client.get("/admin/db/export/nope").status_code == 404


def _upload(payload, **fields):
    data = {
        "file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "dump.json"),
        **fields,
    }
    return data


def test_importing_a_table_replaces_its_rows(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="Old")

    client.post(
        "/admin/db/import",
        data=_upload([{"id": 99, "name": "Imported"}], mode="replace_table", table_name="schools"),
        content_type="multipart/form-data",
    )

    db_session.expire_all()
    assert [s.name for s in db_session.scalars(select(School)).all()] == ["Imported"]


def test_importing_rows_can_merge_by_primary_key(client, db_session, authenticated_admin):
    from models import School

    school = make_school(db_session, name="Original")

    client.post(
        "/admin/db/import",
        data=_upload(
            [{"id": school.id, "name": "Updated"}], mode="merge_rows", table_name="schools"
        ),
        content_type="multipart/form-data",
    )

    db_session.expire_all()
    assert db_session.get(School, school.id).name == "Updated"
    assert db_session.scalar(select(func.count()).select_from(School)) == 1


def test_importing_a_full_database_merges_tables(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="Replaced")

    client.post(
        "/admin/db/import",
        data=_upload({"schools": [{"id": 5, "name": "Fresh"}]}, mode="merge_tables"),
        content_type="multipart/form-data",
    )

    db_session.expire_all()
    assert [s.name for s in db_session.scalars(select(School)).all()] == ["Fresh"]


def test_an_import_with_no_file_is_reported(client, authenticated_admin):
    response = client.post("/admin/db/import", data={"mode": "replace_table"})

    assert_redirects_to(response, "/admin/db")


def test_an_invalid_json_import_is_reported(client, authenticated_admin):
    data = {"file": (io.BytesIO(b"not json"), "dump.json"), "mode": "replace_table"}

    response = client.post("/admin/db/import", data=data, content_type="multipart/form-data")

    assert_redirects_to(response, "/admin/db")


def test_an_unknown_import_mode_is_reported(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="Untouched")

    client.post(
        "/admin/db/import",
        data=_upload([{"name": "x"}], mode="teleport", table_name="schools"),
        content_type="multipart/form-data",
    )

    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(School)) == 1


def test_importing_into_an_unknown_table_is_reported(client, authenticated_admin):
    response = client.post(
        "/admin/db/import",
        data=_upload([{"name": "x"}], mode="replace_table", table_name="nope"),
        content_type="multipart/form-data",
    )

    assert_redirects_to(response, "/admin/db")


# ── table browser: foreign-key links and row focus ───────────────────────────


def test_a_foreign_key_cell_links_to_the_referenced_row(client, db_session, authenticated_admin):
    school = make_school(db_session, name="Linked School")
    make_teacher(db_session, school=school)

    body = assert_success(client.get("/admin/db/table/teachers")).get_data(as_text=True)

    assert f"/admin/db/table/schools?focus_col=id&amp;focus_val={school.id}" in body


def test_focusing_a_row_shows_the_whole_table_and_marks_only_that_row(client, db_session, authenticated_admin):
    target = make_school(db_session, name="Focus Target")
    make_school(db_session, name="Bystander")

    body = assert_success(
        client.get(f"/admin/db/table/schools?focus_col=id&focus_val={target.id}")
    ).get_data(as_text=True)

    assert "Focus Target" in body
    assert "Bystander" in body
    assert body.count(" data-focused>") == 1


def test_focusing_a_row_lands_on_the_page_that_holds_it(client, db_session, authenticated_admin, monkeypatch):
    from routes.administrator import db_console

    monkeypatch.setattr(db_console, "_DB_PAGE_SIZE", 2)
    schools = [make_school(db_session, name=f"School {index}") for index in range(5)]

    body = assert_success(
        client.get(f"/admin/db/table/schools?focus_col=id&focus_val={schools[4].id}")
    ).get_data(as_text=True)

    assert "page 3/3" in body
    assert body.count(" data-focused>") == 1


def test_focusing_an_unknown_column_is_ignored(client, db_session, authenticated_admin):
    make_school(db_session, name="Still Listed")

    body = assert_success(
        client.get("/admin/db/table/schools?focus_col=nope%22%3B--&focus_val=1")
    ).get_data(as_text=True)

    assert "Still Listed" in body
    assert " data-focused>" not in body


def test_query_results_render_inside_the_sql_panel_under_the_form(client, db_session, authenticated_admin):
    from html.parser import HTMLParser

    make_school(db_session, name="Ordered")
    body = assert_success(
        client.post("/admin/db/query", data={"sql": "SELECT name FROM schools"})
    ).get_data(as_text=True)

    class Nesting(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.found_in_panel = [], False

        def handle_starttag(self, tag, attrs):
            attr = dict(attrs)
            if tag == "div":
                self.stack.append(attr.get("id"))
            if attr.get("id") == "queryResults" and "sqlPanel" in self.stack:
                self.found_in_panel = True

        def handle_endtag(self, tag):
            if tag == "div" and self.stack:
                self.stack.pop()

    parser = Nesting()
    parser.feed(body)
    assert parser.found_in_panel
    assert body.index('id="sqlPanel"') < body.index("Run Query") < body.index('id="queryResults"')

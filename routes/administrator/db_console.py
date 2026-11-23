"""Raw-SQL admin console — ad-hoc query runner, table browser, and JSON
export/import. Isolated in its own module so an AI editing the CMS or
people routes doesn't need to load the injection-guard code alongside them.

Every statement except the ad-hoc query is built with SQLAlchemy Core
against a lightweight `table()` whose columns are read from the live DB:
a table or column name from a URL or request body is looked up there first
(unknown → 404 / 400) and is then quoted by the dialect's compiler, never
pasted into a SQL string. Columns are untyped (`NullType`), so values pass
to the driver exactly as `text()` bind parameters would — no ORM coercion."""

import json
import os
from datetime import datetime
from typing import Any, cast

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import and_, column, delete, func, insert, select, table, text, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.sql.expression import TableClause

from extensions import db
from helpers.render import render_template
from helpers.utils import clamp_page, utcnow_naive, wants_fragment
from routes.administrator import admin_required, administrator_bp

# ===================== DB Stats =====================

def _strip_sql_comments(sql):
    """`sql` with `/* block */` and `-- line` comments removed, in one linear
    pass (a regex over `/* … */` rescans the rest of the string from every
    `/*`, which is quadratic on a hostile input). An unterminated block
    comment swallows the rest of the string, as the database would. It does
    not understand string literals — a `'--'` inside quotes is treated as a
    comment start, which can only make the guard below refuse more."""
    out = []
    i, n = 0, len(sql)
    while i < n:
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                break
            out.append(" ")
            i = end + 2
        elif sql.startswith("--", i):
            end = sql.find("\n", i + 2)
            if end == -1:
                break
            i = end
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)

def _safe_is_select(sql):
    """First gate for the admin ad-hoc SQL console (`db_query` below); the
    second is the read-only connection `_run_read_only` runs it on.

    Allows exactly one thing: a single statement whose first token is
    `SELECT`. Strips `/* block */` and `-- line` comments first so a
    semicolon or a leading verb can't hide inside one, then rejects any `;`
    that isn't a single optional trailing terminator — this blocks
    statement-stacking (`SELECT 1; DROP TABLE users`). It is a prefix check,
    not a parser: it does not understand CTEs (`WITH ... SELECT` is
    rejected), and a `SELECT` can still call a function that writes — which
    is what the read-only connection is for. It only decides read-vs-write;
    it does not scope *which* rows or tables a SELECT may touch."""
    clean = _strip_sql_comments(sql).strip()
    if ';' in clean.rstrip(';'):
        return False
    return clean.upper().startswith('SELECT')

def _run_read_only(sql):
    """Run the admin's SELECT on its own connection that the database itself
    holds read-only — Postgres `SET TRANSACTION READ ONLY` (plus a statement
    timeout), SQLite `PRAGMA query_only` — and always roll back. Returns
    (column names, up to 100 rows)."""
    with db.engine.connect() as conn:
        dialect = conn.dialect.name
        if dialect == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '15s'"))
        elif dialect == "sqlite":
            conn.exec_driver_sql("PRAGMA query_only = ON")
        try:
            # The console's whole job is running SQL an administrator typed: `_safe_is_select`
            # and the read-only transaction above are its guards, not parameterisation.
            res = conn.execute(text(sql))
            return list(res.keys()), [list(row) for row in res.fetchmany(100)]
        finally:
            conn.rollback()
            if dialect == "sqlite":
                conn.exec_driver_sql("PRAGMA query_only = OFF")

def _build_db_stats():
    """Row count per table for the `/db` landing page. A table that fails to
    count (e.g. locked, or a dialect-specific quirk) shows "—" instead."""
    all_tables = _get_all_table_names()
    stats = {}
    for name in all_tables:
        try:
            stats[name] = db.session.execute(
                select(func.count()).select_from(table(name))
            ).scalar()
        except Exception:  # noqa: BLE001 - per-table best-effort count against an arbitrary/unmodeled table; failure surface is dialect- and table-specific, must not 500 the whole stats page
            db.session.rollback()
            stats[name] = "—"
    return stats, all_tables

@administrator_bp.route("/db")
@login_required
@admin_required
def db_stats():
    """Landing page for the DB console: per-table counts + DB size, no query
    run yet. `db_query` below renders the same page with a query result or
    error filled in."""
    stats, all_tables = _build_db_stats()
    db_size = _get_db_size()
    return render_template(
        "@pages/administrator/db_stats.jx",
        stats=stats,
        db_size=db_size,
        all_tables=all_tables,
        query_result=None,
        query_error=None,
        query_sql="",
    )

@administrator_bp.route("/db/query", methods=["POST"])
@login_required
@admin_required
def db_query():
    """Run an admin-typed SQL string and show up to 100 rows. Two guards:
    `_safe_is_select` refuses anything that isn't one SELECT, and
    `_run_read_only` runs what passes on a read-only connection, so a write
    the prefix check misses fails in the database. Any DB error (bad syntax,
    missing table, a refused write) is shown as `query_error` — an admin
    debugging SQL needs the database's own words."""
    sql = request.form.get("sql", "").strip()
    columns = []
    rows = []
    query_error = None

    if not _safe_is_select(sql):
        query_error = "Only SELECT statements are allowed. No semicolons mid-statement."
    else:
        try:
            columns, rows = _run_read_only(sql)
        except Exception as e:  # noqa: BLE001 - admin console runs arbitrary ad-hoc SQL; any DB error must be shown as query_error, not raised
            query_error = str(e)

    stats, all_tables = _build_db_stats()
    db_size = _get_db_size()
    return render_template(
        "@pages/administrator/db_stats.jx",
        stats=stats,
        db_size=db_size,
        all_tables=all_tables,
        query_result={"columns": columns, "rows": rows} if not query_error else None,
        query_error=query_error,
        query_sql=sql,
    )

def _get_db_size():
    """Human-readable DB size for the stats page — SQLite reads the file
    directly off disk, Postgres asks the server (`pg_database_size`), since
    there's no file to stat in that dialect. Returns None (rendered blank)
    on any failure or an unrecognized dialect."""
    try:
        if db.engine.dialect.name == "sqlite":
            from helpers.paths import get_data_path
            db_path = get_data_path("site.db")
            if os.path.exists(db_path):
                size = os.path.getsize(db_path)
                return f"{size / 1024:.1f} KB"
        elif db.engine.dialect.name == "postgresql":
            result = db.session.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            )
            return result.scalar()
    except Exception:  # noqa: BLE001, S110 - cosmetic DB size stat, dialect-specific failure surface; docstring documents the silent None-on-failure fallback so the stats page never 500s over it
        pass
    return None

# ===================== Identifiers and errors =====================

class _UnknownColumn(ValueError):
    """A request body named a column the table doesn't have."""

def _table(table_name):
    """`table_name` as a Core table with every column the live DB gives it,
    or None when the DB has no such table."""
    inspector = sa_inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return None
    return table(table_name, *(column(c["name"]) for c in inspector.get_columns(table_name)))

def _col(tbl: TableClause, name):
    """The table's own column called `name`; `_UnknownColumn` for anything else."""
    if not isinstance(name, str) or name not in tbl.c:
        raise _UnknownColumn(name)
    return tbl.c[name]

def _values(tbl: TableClause, row: dict[str, Any], *, blank_is_null=False):
    """`{column: value}` for a request-body row, every key checked against the table."""
    return {_col(tbl, k): (None if blank_is_null and v == "" else v) for k, v in row.items()}

def _pk_clause(tbl: TableClause, pk_cols, pk_values: dict[str, Any]):
    """`WHERE pk1 = :a AND pk2 = :b` — the body must name exactly the table's
    primary-key columns, so an edit or delete addresses one row and never a
    set of rows picked by some other column."""
    if not pk_cols or set(pk_values) != set(pk_cols):
        raise _UnknownColumn(None)
    return and_(*(_col(tbl, k) == v for k, v in pk_values.items()))

def _db_error_message(exc):
    """What the admin sees when a write fails. The driver's own text names
    constraints, SQL and the driver itself, so it goes to the server log
    and the response carries a fixed line per kind of failure."""
    if isinstance(exc, _UnknownColumn):
        return "That names a column this table doesn't have, or not exactly its primary key."
    current_app.logger.warning("DB console write refused by the database", exc_info=exc)
    if isinstance(exc, IntegrityError):
        return ("The database refused it: a required value is missing, a value is already "
                "taken, or a referenced row doesn't exist.")
    if isinstance(exc, DataError):
        return "A value doesn't fit its column's type."
    return "The database refused it. The server log has the details."

# ===================== DB Table Browser =====================

_DB_PAGE_SIZE = 50

def _get_all_table_names():
    """Every table the live DB actually has, read from the engine (not from
    `db.metadata`) — so it includes tables outside the app's own models too,
    and reflects what a migration has actually applied rather than what the
    code currently declares."""
    inspector = sa_inspect(db.engine)
    return sorted(inspector.get_table_names())

def _get_table_meta(table_name):
    """Returns (columns_info, pk_col_names) or (None, None) if table missing."""
    inspector = sa_inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return None, None
    cols = inspector.get_columns(table_name)
    pk_cols = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
    return cols, pk_cols

def _get_fk_map(table_name):
    """{column: (referenced_table, column)} for single-column foreign keys."""
    fk_map = {}
    for fk in sa_inspect(db.engine).get_foreign_keys(table_name):
        local, remote = fk["constrained_columns"], fk["referred_columns"]
        if len(local) == 1 and len(remote) == 1:
            fk_map[local[0]] = (fk["referred_table"], remote[0])
    return fk_map

def _parse_focus(cols_info):
    """The `?focus_col=&focus_val=` pair a foreign-key link carries, as
    (column, value coerced to the column's Python type), or None when absent,
    naming no real column, or not coercible — a bad link just shows the whole
    table."""
    col = request.args.get("focus_col", "")
    raw = request.args.get("focus_val")
    by_name = {c["name"]: c for c in cols_info}
    if col not in by_name or raw is None:
        return None
    try:
        py_type = by_name[col]["type"].python_type
    except NotImplementedError:
        py_type = str
    try:
        value = raw if py_type is str else py_type(raw)
    except (TypeError, ValueError):
        return None
    return col, value

@administrator_bp.route("/db/table/<table_name>")
@login_required
@admin_required
def db_table(table_name):
    """Paginated raw dump of one table, any table the DB has — `table_name`
    is only checked against the live DB's own table list, not against a
    fixed allowlist, so this (and its sibling update/delete/add-row routes)
    reaches every table including ones with no app-level model."""
    cols_info, pk_cols = _get_table_meta(table_name)
    tbl = _table(table_name)
    if cols_info is None or tbl is None:
        abort(404)

    try:
        total = db.session.execute(select(func.count()).select_from(tbl)).scalar_one()
    except Exception as e:  # noqa: BLE001 - reads an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, shown to the admin rather than raised
        db.session.rollback()
        flash(f"Error reading table: {_db_error_message(e)}", "error")
        return redirect(url_for("administrator.db_stats"))

    # Single-column primary keys give a stable order, so pages don't shuffle
    # and a focused row's page can be computed.
    pk = tbl.c[pk_cols[0]] if len(pk_cols) == 1 else None
    focus = _parse_focus(cols_info)
    focus_page = None
    if focus and pk is not None and "page" not in request.args:
        try:
            target = db.session.execute(
                select(pk).where(tbl.c[focus[0]] == focus[1]).order_by(pk).limit(1)
            ).scalar()
            if target is not None:
                before = db.session.execute(
                    select(func.count()).select_from(tbl).where(pk < target)
                ).scalar_one()
                focus_page = before // _DB_PAGE_SIZE + 1
        except Exception:  # noqa: BLE001 - best-effort page lookup on an arbitrary table; failure just means no jump
            db.session.rollback()

    page, total_pages = clamp_page(total, _DB_PAGE_SIZE)
    if focus_page:
        page = min(focus_page, total_pages)
    offset = (page - 1) * _DB_PAGE_SIZE

    query = select(tbl)
    if pk is not None:
        query = query.order_by(pk)
    try:
        result = db.session.execute(query.limit(_DB_PAGE_SIZE).offset(offset))
        col_names = list(result.keys())
        rows = [list(row) for row in result.fetchall()]
    except Exception as e:  # noqa: BLE001 - reads an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, shown to the admin rather than raised
        db.session.rollback()
        flash(f"Error reading table: {_db_error_message(e)}", "error")
        return redirect(url_for("administrator.db_stats"))

    ctx = {
        'table_name': table_name,
        'col_names': col_names,
        'rows': rows,
        'pk_cols': pk_cols,
        'page': page,
        'total_pages': total_pages,
        'total': total,
        'page_size': _DB_PAGE_SIZE,
        'all_tables': _get_all_table_names(),
        'fk_map': _get_fk_map(table_name),
        'focus': {"col": focus[0], "val": request.args["focus_val"]} if focus else None,
    }
    if wants_fragment():
        return render_template("@page_components/administrator/db_table_results.jx", **ctx)
    return render_template("@pages/administrator/db_table.jx", **ctx)

@administrator_bp.route("/db/table/<table_name>/update-row", methods=["POST"])
@login_required
@admin_required
def db_update_row(table_name):
    """Update one row in any table by primary key, bypassing every ORM
    validator/hook a model would normally run (password hashing, cascades,
    `is_matched` sync, etc.) — this writes columns directly. An empty-string
    value is coerced to `NULL`, since the table editor UI has no other way
    to express "clear this field". `pk` must name exactly the table's
    primary-key columns and `updates` only its own columns (else 400)."""
    _, pk_cols = _get_table_meta(table_name)
    tbl = _table(table_name)
    if pk_cols is None or tbl is None:
        return jsonify({"error": "Table not found"}), 404

    data = request.get_json(silent=True)
    pk_values = data.get("pk") if isinstance(data, dict) else None
    updates = data.get("updates") if isinstance(data, dict) else None
    if not isinstance(pk_values, dict) or not isinstance(updates, dict) or not pk_values or not updates:
        return jsonify({"error": "Missing pk or updates"}), 400

    try:
        stmt = update(tbl).where(_pk_clause(tbl, pk_cols, pk_values)).values(
            _values(tbl, updates, blank_is_null=True)
        )
    except _UnknownColumn as e:
        return jsonify({"error": _db_error_message(e)}), 400
    try:
        db.session.execute(stmt)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001 - writes an admin-chosen table with no fixed schema, bypassing ORM validation; error surface is dialect- and table-specific, returned as JSON rather than raised
        db.session.rollback()
        return jsonify({"error": _db_error_message(e)}), 500

@administrator_bp.route("/db/table/<table_name>/delete-row", methods=["POST"])
@login_required
@admin_required
def db_delete_row(table_name):
    """Delete one row by primary key from any table — a raw `DELETE`, so no
    cascade/unmatch logic a model-level delete would trigger runs here.
    404s when the pk matched no row, distinct from a 500, so the UI can tell
    "already gone" from "the delete failed". `pk` must name exactly the
    table's primary-key columns (else 400)."""
    _, pk_cols = _get_table_meta(table_name)
    tbl = _table(table_name)
    if pk_cols is None or tbl is None:
        return jsonify({"error": "Table not found"}), 404

    data = request.get_json(silent=True)
    pk_values = data.get("pk") if isinstance(data, dict) else None
    if not isinstance(pk_values, dict) or not pk_values:
        return jsonify({"error": "Missing pk"}), 400

    try:
        stmt = delete(tbl).where(_pk_clause(tbl, pk_cols, pk_values))
    except _UnknownColumn as e:
        return jsonify({"error": _db_error_message(e)}), 400
    try:
        # A DELETE always executes as a CursorResult at runtime;
        # Session.execute()'s general overload just doesn't say so statically.
        result = cast(CursorResult, db.session.execute(stmt))
        if result.rowcount == 0:
            db.session.rollback()
            return jsonify({"error": "No row matched that primary key"}), 404
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001 - deletes from an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, returned as JSON rather than raised
        db.session.rollback()
        return jsonify({"error": _db_error_message(e)}), 500

@administrator_bp.route("/db/table/<table_name>/add-row", methods=["POST"])
@login_required
@admin_required
def db_add_row(table_name):
    """Insert one row into any table from raw column values — no model
    validation, no default/hook logic (e.g. no password hashing if the
    table is a user subtype), just a parameterized `INSERT`. Empty-string
    values are coerced to `NULL`, same convention as `db_update_row`; a
    key that isn't one of the table's columns is a 400."""
    tbl = _table(table_name)
    if tbl is None:
        return jsonify({"error": "Table not found"}), 404

    data = request.get_json(silent=True)
    row = data.get("row") if isinstance(data, dict) else None
    if not isinstance(row, dict) or not row:
        return jsonify({"error": "No row data"}), 400

    try:
        stmt = insert(tbl).values(_values(tbl, row, blank_is_null=True))
    except _UnknownColumn as e:
        return jsonify({"error": _db_error_message(e)}), 400
    try:
        db.session.execute(stmt)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001 - inserts into an admin-chosen table with no fixed schema, bypassing ORM validation; error surface is dialect- and table-specific, returned as JSON rather than raised
        db.session.rollback()
        return jsonify({"error": _db_error_message(e)}), 500

# ===================== DB Export =====================

def _serialize_val(v):
    """JSON can't represent a `datetime` — everything else round-trips
    as-is (including password hashes and other sensitive columns; the
    export routes below apply no field filtering)."""
    if isinstance(v, datetime):
        return v.isoformat()
    return v

def _export_rows(tbl: TableClause):
    result = db.session.execute(select(tbl))
    col_names = list(result.keys())
    return [
        {col: _serialize_val(val) for col, val in zip(col_names, row)}
        for row in result.fetchall()
    ]

@administrator_bp.route("/db/export")
@login_required
@admin_required
def db_export_full():
    """Dump every table to one JSON file — full fidelity, no column
    filtering, including password hashes and any other sensitive fields.
    Treat the download as equivalent in sensitivity to a raw DB backup, and
    as the exact shape `db_import`'s "Full DB" mode expects back. A table
    that fails to read exports as `[]`."""
    export = {}
    for name in _get_all_table_names():
        tbl = _table(name)
        try:
            export[name] = _export_rows(tbl) if tbl is not None else []
        except Exception:  # noqa: BLE001 - per-table best-effort export of an arbitrary/unmodeled table; a failure must not abort the whole export file
            db.session.rollback()
            export[name] = []

    ts = utcnow_naive().strftime("%Y%m%d_%H%M%S")
    return Response(
        json.dumps(export, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=integrated_db_{ts}.json"},
    )

@administrator_bp.route("/db/export/<table_name>")
@login_required
@admin_required
def db_export_table(table_name):
    """Single-table counterpart to `db_export_full` — same no-filtering
    caveat applies, and the output shape (a bare JSON array of row objects)
    is what `db_import`'s "table" mode expects back."""
    tbl = _table(table_name)
    if tbl is None:
        abort(404)

    try:
        rows = _export_rows(tbl)
    except Exception as e:  # noqa: BLE001 - reads an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, shown to the admin rather than raised
        db.session.rollback()
        flash(f"Export error: {_db_error_message(e)}", "error")
        return redirect(url_for("administrator.db_table", table_name=table_name))

    ts = utcnow_naive().strftime("%Y%m%d_%H%M%S")
    return Response(
        json.dumps(rows, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={tbl.name}_{ts}.json"},
    )

# ===================== DB Import =====================

def _insert_ignoring_conflicts(tbl: TableClause, row: dict[str, Any]):
    """`INSERT … ON CONFLICT DO NOTHING` (Postgres) / `INSERT OR IGNORE` (SQLite)."""
    values = _values(tbl, row)
    if db.engine.dialect.name == "postgresql":
        return postgresql.insert(tbl).values(values).on_conflict_do_nothing()
    return insert(tbl).values(values).prefix_with("OR IGNORE")

def _bulk_insert(tbl: TableClause, rows):
    """Insert every row, silently skipping (not erroring on) any that
    collides with an existing primary key — `ON CONFLICT DO NOTHING` /
    `INSERT OR IGNORE`. Used for "replace" import modes where the table was
    just wiped so collisions aren't expected, and for merge modes where a
    caller has already decided a plain insert (not an upsert) is correct."""
    for row in rows:
        if row:
            db.session.execute(_insert_ignoring_conflicts(tbl, row))

def _upsert_rows(tbl: TableClause, rows, pk_cols):
    """Update-if-exists, insert-if-not, keyed on the table's actual primary
    key columns. A row with no pk value present is just inserted (can't be
    matched to an existing one). This silently overwrites every non-pk
    column of a matching existing row with the imported value — there is no
    dry-run or diff step before it commits."""
    for row in rows:
        if not row:
            continue
        pk_vals = {col: row[col] for col in pk_cols if col in row}
        if not pk_vals:
            _bulk_insert(tbl, [row])
            continue

        where = and_(*(_col(tbl, col) == pk_vals.get(col) for col in pk_cols))
        exists = db.session.execute(select(1).select_from(tbl).where(where)).scalar()

        if exists:
            changes = {k: v for k, v in row.items() if k not in pk_cols}
            if changes:
                db.session.execute(update(tbl).where(where).values(_values(tbl, changes)))
        else:
            db.session.execute(insert(tbl).values(_values(tbl, row)))

def _check_rows(tbl: TableClause, rows):
    """Raise `_UnknownColumn` before anything is deleted if any row names a
    column the table doesn't have — so a bad file can't wipe a table and
    then fail on its first insert."""
    if not isinstance(rows, list):
        raise _UnknownColumn(None)
    for row in rows:
        if not isinstance(row, dict):
            raise _UnknownColumn(None)
        for key in row:
            _col(tbl, key)

@administrator_bp.route("/db/import", methods=["POST"])
@login_required
@admin_required
def db_import():
    """Restore or merge a JSON export back into the DB. The most destructive
    route in the admin panel — no confirmation step beyond the form itself,
    no automatic backup. Modes: `replace_all`/`merge_tables` (full-DB import,
    JSON object of table->rows) and `replace_table`/`merge_rows` (single-table
    import, bare JSON array + `table_name` — see `_bulk_insert`/`_upsert_rows`
    for exact per-mode delete/rollback semantics). Input shape (object vs
    array) picks full-DB vs single-table automatically. Every row's columns
    are checked against its table before anything is deleted."""
    f = request.files.get("file")
    mode = request.form.get("mode", "")
    target_table = request.form.get("table_name", "").strip()

    if not f:
        flash("No file uploaded.", "error")
        return redirect(url_for("administrator.db_stats"))

    try:
        data = json.loads(f.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - admin-uploaded file; a bad encoding or malformed JSON must show as a flash message, not raise
        flash("Invalid JSON file.", "error")
        return redirect(url_for("administrator.db_stats"))

    is_full_db = isinstance(data, dict) and all(isinstance(v, list) for v in data.values())
    is_table_data = isinstance(data, list)
    all_tables = _get_all_table_names()

    try:
        if is_full_db:
            if mode not in ("replace_all", "merge_tables"):
                flash("Unknown import mode.", "error")
                return redirect(url_for("administrator.db_stats"))
            # Tables the file names that the DB doesn't have are skipped, as before.
            imports = []
            for name, rows in data.items():
                tbl = _table(name) if name in all_tables else None
                if tbl is not None:
                    _check_rows(tbl, rows)
                    imports.append((tbl, rows))
            if mode == "replace_all":
                # This delete is committed on its own, before any insert — unlike
                # every other mode below, a wipe here is NOT covered by the
                # rollback on the insert phase's exception handler. An insert
                # failure leaves that table's data permanently gone.
                for name in reversed(all_tables):
                    tbl = _table(name)
                    if tbl is not None:
                        db.session.execute(delete(tbl))
                db.session.commit()
                for tbl, rows in imports:
                    _bulk_insert(tbl, rows)
            else:
                for tbl, rows in imports:
                    db.session.execute(delete(tbl))
                    _bulk_insert(tbl, rows)
            db.session.commit()
            flash(f"Full DB imported ({mode}).", "success")

        elif is_table_data and target_table:
            tbl = _table(target_table)
            if tbl is None:
                flash("That table was not found.", "error")
                return redirect(url_for("administrator.db_stats"))
            if mode not in ("replace_table", "merge_rows"):
                flash("Unknown import mode.", "error")
                return redirect(url_for("administrator.db_stats"))
            _check_rows(tbl, data)
            _, pk_cols = _get_table_meta(target_table)
            if mode == "replace_table":
                db.session.execute(delete(tbl))
                _bulk_insert(tbl, data)
            else:
                _upsert_rows(tbl, data, pk_cols or [])
            db.session.commit()
            flash(f"Table '{tbl.name}' imported ({mode}).", "success")

        else:
            flash("Cannot determine import type. Full DB = JSON object; table = JSON array with table selected.", "error")
    except Exception as e:  # noqa: BLE001 - imports arbitrary admin-uploaded data into arbitrary/unmodeled tables; error surface is dialect- and data-specific, shown as a flash message rather than raised
        db.session.rollback()
        flash(f"Import failed: {_db_error_message(e)}", "error")

    return redirect(url_for("administrator.db_stats"))

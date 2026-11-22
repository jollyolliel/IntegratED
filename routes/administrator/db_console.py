"""Raw-SQL admin console — ad-hoc query runner, table browser, and JSON
export/import. Isolated in its own module so an AI editing the CMS or
people routes doesn't need to load the injection-guard code alongside them."""

import json
import os
import re
from datetime import datetime
from typing import cast

from flask import (
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.engine import CursorResult

from extensions import db
from helpers.render import render_template
from helpers.utils import clamp_page, utcnow_naive, wants_fragment
from routes.administrator import admin_required, administrator_bp

# ===================== DB Stats =====================

def _safe_is_select(sql):
    """Gate for the admin ad-hoc SQL console (`db_query` below) — the only
    thing standing between an admin-authenticated request and an arbitrary
    write/DDL statement run directly against prod.

    Allows exactly one thing: a single statement whose first token is
    `SELECT`. Strips `/* block */` and `-- line` comments first so a
    semicolon or a leading verb can't hide inside one, then rejects any `;`
    that isn't a single optional trailing terminator — this blocks
    statement-stacking (`SELECT 1; DROP TABLE users`). It is a prefix check,
    not a parser: it does not understand CTEs (`WITH ... SELECT` is
    rejected), multi-statement batching via other DB-specific separators, or
    whether the SELECT reads something sensitive. It only decides
    read-vs-write; it does not scope *which* rows or tables a SELECT may
    touch, and it does not apply to `db_table`, `db_update_row`,
    `db_delete_row`, or `db_add_row` below, which build their own
    parameterized SQL against an admin-chosen table directly and are not
    routed through this guard."""
    clean = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    clean = re.sub(r'--[^\n]*', '', clean)
    clean = clean.strip()
    if ';' in clean.rstrip(';'):
        return False
    return clean.upper().startswith('SELECT')

def _build_db_stats():
    """Row count per table for the `/db` landing page. A table that fails to
    count (e.g. locked, or a dialect-specific quirk) shows "—" instead."""
    all_tables = _get_all_table_names()
    stats = {}
    for table in all_tables:
        try:
            count = db.session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            stats[table] = count
        except Exception:  # noqa: BLE001 - per-table best-effort count against an arbitrary/unmodeled table; failure surface is dialect- and table-specific, must not 500 the whole stats page
            stats[table] = "—"
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
    """Run an admin-typed SQL string and show up to 100 rows. Safety is
    entirely `_safe_is_select`'s job (see its docstring for exactly what it
    does and doesn't block) — this handler trusts that gate completely and
    otherwise just executes the raw string via `text()`. Any DB error (bad
    syntax, missing table) is shown as `query_error`."""
    sql = request.form.get("sql", "").strip()
    columns = []
    rows = []
    query_error = None

    if not _safe_is_select(sql):
        query_error = "Only SELECT statements are allowed. No semicolons mid-statement."
    else:
        try:
            res = db.session.execute(text(sql))
            columns = list(res.keys())
            rows = [list(row) for row in res.fetchmany(100)]
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
    table. The column name is checked against the table's own columns, which
    is what makes it safe to quote into SQL."""
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
    is only checked against `_get_all_table_names()`/`_get_table_meta`, not
    against a fixed allowlist, so this (and its sibling update/delete/add-row
    routes) reaches every table including ones with no app-level model."""
    cols_info, pk_cols = _get_table_meta(table_name)
    if cols_info is None:
        abort(404)

    try:
        total = db.session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
    except Exception as e:  # noqa: BLE001 - reads an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, shown to the admin rather than raised
        flash(f"Error reading table: {e}", "error")
        return redirect(url_for("administrator.db_stats"))

    # Single-column primary keys give a stable order, so pages don't shuffle
    # and a focused row's page can be computed.
    order = f' ORDER BY "{pk_cols[0]}"' if len(pk_cols) == 1 else ""
    focus = _parse_focus(cols_info)
    focus_page = None
    if focus and order and "page" not in request.args:
        try:
            pk = pk_cols[0]
            target = db.session.execute(
                text(f'SELECT "{pk}" FROM "{table_name}" WHERE "{focus[0]}" = :v{order} LIMIT 1'),
                {"v": focus[1]},
            ).scalar()
            if target is not None:
                before = db.session.execute(
                    text(f'SELECT COUNT(*) FROM "{table_name}" WHERE "{pk}" < :t'), {"t": target}
                ).scalar_one()
                focus_page = before // _DB_PAGE_SIZE + 1
        except Exception:  # noqa: BLE001 - best-effort page lookup on an arbitrary table; failure just means no jump
            db.session.rollback()

    page, total_pages = clamp_page(total, _DB_PAGE_SIZE)
    if focus_page:
        page = min(focus_page, total_pages)
    offset = (page - 1) * _DB_PAGE_SIZE

    try:
        result = db.session.execute(
            text(f'SELECT * FROM "{table_name}"{order} LIMIT :lim OFFSET :off'),
            {"lim": _DB_PAGE_SIZE, "off": offset},
        )
        col_names = list(result.keys())
        rows = [list(row) for row in result.fetchall()]
    except Exception as e:  # noqa: BLE001 - reads an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, shown to the admin rather than raised
        flash(f"Error reading table: {e}", "error")
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
    to express "clear this field"."""
    _, pk_cols = _get_table_meta(table_name)
    if pk_cols is None:
        return jsonify({"error": "Table not found"}), 404

    data = request.get_json()
    pk_values = data.get("pk") if data else None
    updates = data.get("updates") if data else None
    if not pk_values or not updates:
        return jsonify({"error": "Missing pk or updates"}), 400

    set_parts = []
    params = {}
    for i, (col, val) in enumerate(updates.items()):
        set_parts.append(f'"{col}" = :val_{i}')
        params[f"val_{i}"] = None if val == "" else val

    where_parts = []
    for i, (col, val) in enumerate(pk_values.items()):
        where_parts.append(f'"{col}" = :pk_{i}')
        params[f"pk_{i}"] = val

    sql = f'UPDATE "{table_name}" SET {", ".join(set_parts)} WHERE {" AND ".join(where_parts)}'
    try:
        db.session.execute(text(sql), params)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001 - writes an admin-chosen table with no fixed schema, bypassing ORM validation; error surface is dialect- and table-specific, returned as JSON rather than raised
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@administrator_bp.route("/db/table/<table_name>/delete-row", methods=["POST"])
@login_required
@admin_required
def db_delete_row(table_name):
    """Delete one row by primary key from any table — a raw `DELETE`, so no
    cascade/unmatch logic a model-level delete would trigger runs here.
    404s when the pk matched no row, distinct from a 500, so the UI can tell
    "already gone" from "the delete failed"."""
    _, pk_cols = _get_table_meta(table_name)
    if pk_cols is None:
        return jsonify({"error": "Table not found"}), 404

    data = request.get_json()
    pk_values = data.get("pk") if data else None
    if not pk_values:
        return jsonify({"error": "Missing pk"}), 400

    where_parts = []
    params = {}
    for i, (col, val) in enumerate(pk_values.items()):
        where_parts.append(f'"{col}" = :pk_{i}')
        params[f"pk_{i}"] = val

    sql = f'DELETE FROM "{table_name}" WHERE {" AND ".join(where_parts)}'
    try:
        # A DELETE via text() always executes as a CursorResult at runtime;
        # Session.execute()'s general overload just doesn't say so statically.
        result = cast(CursorResult, db.session.execute(text(sql), params))
        if result.rowcount == 0:
            db.session.rollback()
            return jsonify({"error": "No row matched that primary key"}), 404
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001 - deletes from an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, returned as JSON rather than raised
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@administrator_bp.route("/db/table/<table_name>/add-row", methods=["POST"])
@login_required
@admin_required
def db_add_row(table_name):
    """Insert one row into any table from raw column values — no model
    validation, no default/hook logic (e.g. no password hashing if the
    table is a user subtype), just a parameterized `INSERT`. Empty-string
    values are coerced to `NULL`, same convention as `db_update_row`."""
    cols_info, _ = _get_table_meta(table_name)
    if cols_info is None:
        return jsonify({"error": "Table not found"}), 404

    data = request.get_json()
    row = data.get("row") if data else None
    if not row:
        return jsonify({"error": "No row data"}), 400

    col_parts = [f'"{c}"' for c in row]
    val_parts = [f":v_{i}" for i in range(len(row))]
    params = {f"v_{i}": (None if v == "" else v) for i, v in enumerate(row.values())}

    sql = f'INSERT INTO "{table_name}" ({", ".join(col_parts)}) VALUES ({", ".join(val_parts)})'
    try:
        db.session.execute(text(sql), params)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:  # noqa: BLE001 - inserts into an admin-chosen table with no fixed schema, bypassing ORM validation; error surface is dialect- and table-specific, returned as JSON rather than raised
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ===================== DB Export =====================

def _serialize_val(v):
    """JSON can't represent a `datetime` — everything else round-trips
    as-is (including password hashes and other sensitive columns; the
    export routes below apply no field filtering)."""
    if isinstance(v, datetime):
        return v.isoformat()
    return v

@administrator_bp.route("/db/export")
@login_required
@admin_required
def db_export_full():
    """Dump every table to one JSON file — full fidelity, no column
    filtering, including password hashes and any other sensitive fields.
    Treat the download as equivalent in sensitivity to a raw DB backup, and
    as the exact shape `db_import`'s "Full DB" mode expects back. A table
    that fails to read exports as `[]`."""
    tables = _get_all_table_names()
    export = {}
    for table in tables:
        try:
            result = db.session.execute(text(f'SELECT * FROM "{table}"'))
            col_names = list(result.keys())
            export[table] = [
                {col: _serialize_val(val) for col, val in zip(col_names, row)}
                for row in result.fetchall()
            ]
        except Exception:  # noqa: BLE001 - per-table best-effort export of an arbitrary/unmodeled table; a failure must not abort the whole export file
            export[table] = []

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
    cols_info, _ = _get_table_meta(table_name)
    if cols_info is None:
        abort(404)

    try:
        result = db.session.execute(text(f'SELECT * FROM "{table_name}"'))
        col_names = list(result.keys())
        rows = [
            {col: _serialize_val(val) for col, val in zip(col_names, row)}
            for row in result.fetchall()
        ]
    except Exception as e:  # noqa: BLE001 - reads an admin-chosen table with no fixed schema; error surface is dialect- and table-specific, shown to the admin rather than raised
        flash(f"Export error: {e}", "error")
        return redirect(url_for("administrator.db_table", table_name=table_name))

    ts = utcnow_naive().strftime("%Y%m%d_%H%M%S")
    return Response(
        json.dumps(rows, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={table_name}_{ts}.json"},
    )

# ===================== DB Import =====================

def _bulk_insert(table_name, rows):
    """Insert every row, silently skipping (not erroring on) any that
    collides with an existing primary key — `ON CONFLICT DO NOTHING` /
    `INSERT OR IGNORE`. Used for "replace" import modes where the table was
    just wiped so collisions aren't expected, and for merge modes where a
    caller has already decided a plain insert (not an upsert) is correct."""
    is_pg = db.engine.dialect.name == "postgresql"
    for row in rows:
        if not row:
            continue
        col_parts = [f'"{c}"' for c in row]
        val_parts = [f":v_{i}" for i in range(len(row))]
        params = {f"v_{i}": v for i, v in enumerate(row.values())}
        if is_pg:
            sql = f'INSERT INTO "{table_name}" ({", ".join(col_parts)}) VALUES ({", ".join(val_parts)}) ON CONFLICT DO NOTHING'
        else:
            sql = f'INSERT OR IGNORE INTO "{table_name}" ({", ".join(col_parts)}) VALUES ({", ".join(val_parts)})'
        db.session.execute(text(sql), params)

def _upsert_rows(table_name, rows, pk_cols):
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
            _bulk_insert(table_name, [row])
            continue

        where_parts = [f'"{col}" = :pk_{i}' for i, col in enumerate(pk_cols)]
        where_params = {f"pk_{i}": pk_vals[col] for i, col in enumerate(pk_cols)}
        exists = db.session.execute(
            text(f'SELECT 1 FROM "{table_name}" WHERE {" AND ".join(where_parts)}'),
            where_params,
        ).scalar()

        if exists:
            set_parts = []
            upd_params = dict(where_params)
            for j, (col, val) in enumerate(row.items()):
                if col not in pk_cols:
                    set_parts.append(f'"{col}" = :u_{j}')
                    upd_params[f"u_{j}"] = val
            if set_parts:
                db.session.execute(
                    text(f'UPDATE "{table_name}" SET {", ".join(set_parts)} WHERE {" AND ".join(where_parts)}'),
                    upd_params,
                )
        else:
            col_parts = [f'"{c}"' for c in row]
            val_parts = [f":v_{i}" for i in range(len(row))]
            params = {f"v_{i}": v for i, v in enumerate(row.values())}
            db.session.execute(
                text(f'INSERT INTO "{table_name}" ({", ".join(col_parts)}) VALUES ({", ".join(val_parts)})'),
                params,
            )

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
    array) picks full-DB vs single-table automatically."""
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
            if mode == "replace_all":
                # This delete is committed on its own, before any insert — unlike
                # every other mode below, a wipe here is NOT covered by the
                # rollback on the insert phase's exception handler. A missing
                # table, malformed JSON, or an insert failure leaves that
                # table's data permanently gone.
                for table in reversed(all_tables):
                    db.session.execute(text(f'DELETE FROM "{table}"'))
                db.session.commit()
                for table_name, rows in data.items():
                    if table_name in all_tables:
                        _bulk_insert(table_name, rows)
            elif mode == "merge_tables":
                for table_name, rows in data.items():
                    if table_name in all_tables:
                        db.session.execute(text(f'DELETE FROM "{table_name}"'))
                        _bulk_insert(table_name, rows)
            else:
                flash("Unknown import mode.", "error")
                return redirect(url_for("administrator.db_stats"))
            db.session.commit()
            flash(f"Full DB imported ({mode}).", "success")

        elif is_table_data and target_table:
            if target_table not in all_tables:
                flash(f"Table '{target_table}' not found.", "error")
                return redirect(url_for("administrator.db_stats"))
            _, pk_cols = _get_table_meta(target_table)
            if mode == "replace_table":
                db.session.execute(text(f'DELETE FROM "{target_table}"'))
                _bulk_insert(target_table, data)
            elif mode == "merge_rows":
                _upsert_rows(target_table, data, pk_cols)
            else:
                flash("Unknown import mode.", "error")
                return redirect(url_for("administrator.db_stats"))
            db.session.commit()
            flash(f"Table '{target_table}' imported ({mode}).", "success")

        else:
            flash("Cannot determine import type. Full DB = JSON object; table = JSON array with table selected.", "error")
    except Exception as e:  # noqa: BLE001 - imports arbitrary admin-uploaded data into arbitrary/unmodeled tables; error surface is dialect- and data-specific, shown as a flash message rather than raised
        db.session.rollback()
        flash(f"Import failed: {e}", "error")

    return redirect(url_for("administrator.db_stats"))

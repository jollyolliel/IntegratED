"""PR previews only (ADR 0013): `/_preview/` and what every preview response carries.

  GET  /_preview/                          the hub: personas, the PR's links, reseed, commit
  GET  /_preview/enter?as=<slug>&next=...  sign in as that persona and go to `next`
  POST /_preview/reseed  size=small|large  rebuild the fake data

`main.py` imports this only under `APP_ENV=preview`, so in any other environment these routes
do not exist. They sign people in without a password; what keeps strangers out is IAP in front
of the whole service. `enter` is a GET so a link can use it, which is CSRF-able: accepted,
because it only switches between fake accounts.

Every response is marked `noindex` and carries `Server-Timing` (total and database time, for
comparing a PR against the `main` preview); every page gets a "fake data" banner. No PostHog
events and no translation keys: it is a developer tool.
"""

from __future__ import annotations

from time import perf_counter

from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    flash,
    g,
    has_request_context,
    redirect,
    request,
    url_for,
)
from flask_login import logout_user
from markupsafe import escape
from sqlalchemy import event

from extensions import db, limiter
from helpers.auth_utils import dashboard_url, sign_in
from helpers.preview.links import decode_links, enter_path
from helpers.preview.personas import PERSONAS, PERSONAS_BY_SLUG
from helpers.preview.seed import SIZES, find_persona, seed_preview
from helpers.render import render_template
from helpers.utils import inject_version, safe_local_path
from settings import get_settings

__all__ = ["init_preview"]

preview_bp = Blueprint("preview", __name__, url_prefix="/_preview")

BANNER_ID = "integrated-preview-banner"


@preview_bp.route("/")
def hub():
    links = [
        {"persona": persona, "path": path, "href": enter_path(persona, path)}
        for persona, path in decode_links(get_settings().preview_links)
    ]
    return render_template(
        "@pages/preview/hub.jx", personas=PERSONAS, links=links, sizes=SIZES,
        pr=get_settings().preview_pr, sha=inject_version()["app_version"],
    )


@preview_bp.route("/enter")
def enter():
    slug = request.args.get("as", "")
    if slug not in PERSONAS_BY_SLUG:
        abort(404)
    user = find_persona(slug)
    if user is None:  # a reviewer deleted it; reseeding brings it back
        flash(f"The {slug} account is gone. Reset the data to bring it back.", "error")
        return redirect(url_for("preview.hub"))
    sign_in(user)
    return redirect(safe_local_path(request.args.get("next")) or dashboard_url(user))


@preview_bp.route("/reseed", methods=["POST"])
@limiter.limit("6 per minute")
def reseed():
    size = request.form.get("size", "")
    if size not in SIZES:
        abort(400)
    # Ids are reused by the new rows, so a kept session could point at someone else.
    logout_user()
    started = perf_counter()
    seed_preview(size)
    flash(f"Reset to the {size} data in {perf_counter() - started:.1f}s. Sign in again.", "success")
    return redirect(url_for("preview.hub"))


def _banner() -> str:
    pr = get_settings().preview_pr
    label = f"PREVIEW · PR #{pr}" if pr else "PREVIEW"
    # Inline styles: it is injected into every page, whatever stylesheets that page loads. Clicks
    # pass through it except on its link, so it never blocks the page underneath.
    return (
        f'<div id="{BANNER_ID}" dir="ltr" style="position:fixed;left:8px;bottom:8px;z-index:2147483647;'
        "pointer-events:none;background:#7c2d12;color:#fff;font:600 12px/1.4 system-ui,sans-serif;"
        'padding:6px 10px;border-radius:8px;max-width:calc(100vw - 16px)">'
        f"{escape(label)} · fake data · "
        '<a href="/_preview/" style="pointer-events:auto;color:#fff;text-decoration:underline">switch persona</a>'
        "</div>"
    )


def _start_timing() -> None:
    g.preview_started = perf_counter()
    g.preview_db_seconds = 0.0
    g.preview_queries = 0


def _mark_response(response: Response) -> Response:
    response.headers["X-Robots-Tag"] = "noindex"
    started = g.get("preview_started")
    if started is not None:
        response.headers["Server-Timing"] = (
            f"total;dur={(perf_counter() - started) * 1000:.1f}, "
            f'db;dur={g.preview_db_seconds * 1000:.1f};desc="{g.preview_queries} queries"'
        )
    if response.mimetype == "text/html" and not response.direct_passthrough and not response.is_streamed:
        page = response.get_data(as_text=True)
        end = page.rfind("</body>")
        if end != -1:  # fragments have no body of their own
            response.set_data(page[:end] + _banner() + page[end:])
    return response


def _before_query(conn, cursor, statement, parameters, context, executemany) -> None:
    context.preview_query_started = perf_counter()


def _after_query(conn, cursor, statement, parameters, context, executemany) -> None:
    if has_request_context() and "preview_queries" in g:
        g.preview_db_seconds += perf_counter() - context.preview_query_started
        g.preview_queries += 1


def init_preview(app: Flask) -> None:
    """Register `/_preview/*`, the response marks and the query timer on a preview app.

    Args:
        app (Flask): An app running with `APP_ENV=preview`.
    """
    app.register_blueprint(preview_bp)
    app.before_request(_start_timing)
    # Registered after flask-compress, so it runs before it and sees the page uncompressed.
    app.after_request(_mark_response)
    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", _before_query)
        event.listen(db.engine, "after_cursor_execute", _after_query)

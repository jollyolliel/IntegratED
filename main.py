print("Custom message: first python run", flush=True)

import os

import dotenv

dotenv.load_dotenv(override=False)

from pathlib import Path
from typing import Any

import stripe
from flask import Flask, abort, jsonify, make_response, request
from sqlalchemy.exc import InterfaceError, OperationalError
from werkzeug.exceptions import HTTPException

from commands import register_commands
from extensions import compress, db, limiter, login_manager, migrate, oauth
from helpers.i18n import i18n_context_processor
from helpers.jx_catalog import build_catalog
from helpers.paths import get_data_path
from helpers.render import render_template
from helpers.seed import SeedError, seed_development
from helpers.utils import (
    inject_now,
    inject_site_settings,
    inject_version,
    is_cross_site_write,
    render_markdown,
    safe_local_path,
    same_site_referrer_path,
)
from models import User
from settings import Settings

# Module-level binding so `global google` inside create_app() (and `from main
# import google` in routes/auth/_oauth.py) resolve to a real symbol. Only
# meaningfully set once create_app() runs `oauth.register(...)` — it needs the
# app to exist first, so this can't be built at import time. `Any` because
# Authlib's `OAuth.register()` is untyped — there is no real type to give it.
google: Any = None

def sqlalchemy_database_url(url: str) -> str:
    """Name the psycopg2 driver on a bare Postgres URL; return any other URL as-is."""
    # SQLAlchemy 2.1 maps bare postgresql:// to psycopg 3 (not installed) and rejects postgres://.
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg2://" + url[len(scheme):]
    return url

def create_app(config_class=None):
    """Build and configure the Flask app: settings from `APP_ENV`, DB config
    (Postgres in production, SQLite in development, `TEST_DATABASE_URL` for
    tests), extension init, blueprint registration, request hooks, error
    handlers, then — inside an app context — `db.create_all()` and
    development-only seeding (skipped under `TESTING_DB`). Nothing here may block on the database; see
    "Startup diagnostic logs" for why. The module-level `app` this returns
    into is what gunicorn serves as `main:app`."""
    app = Flask(__name__)

    # Configuration
    settings = Settings.from_env()
    app.config["SETTINGS"] = settings
    if settings.is_development:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    if settings.is_production:
        app.config["SQLALCHEMY_DATABASE_URI"] = sqlalchemy_database_url(settings.database_url)
        # Neon (and other hosted PG) closes idle connections after ~5 min.
        # pool_pre_ping tests the connection before use — avoids OperationalError/PendingRollbackError
        # on first request after idle period. pool_recycle discards connections older than 5 min.
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 280,
            # Neon serverless suspends compute on idle (scale-to-zero); the first
            # connection after idle blocks while it wakes. A short connect_timeout
            # makes that attempt fail fast (~3s) instead of hanging ~10s — the
            # failed attempt still triggers the wake, and the OperationalError it
            # raises is caught below to serve the "starting up" page.
            "connect_args": {"connect_timeout": 3},
        }
    elif settings.test_database_url:
        # TEST_DATABASE_URL points the app at a throwaway DB for the test suite.
        # Deliberately NOT DATABASE_URL: that name is commonly a real database in
        # a developer's .env, and conftest.py's fixtures call db.drop_all().
        app.config["SQLALCHEMY_DATABASE_URI"] = settings.test_database_url
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{get_data_path('site.db')}"
    # The test suite runs as development against TEST_DATABASE_URL and brings its own schema.
    app.config["TESTING_DB"] = settings.is_development and bool(settings.test_database_url)

    app.config["SECRET_KEY"] = settings.secret_key
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit
    # With the Origin check in `refuse_cross_site_writes`, the app's CSRF guard:
    # a cross-site POST never carries the session. Lax, not Strict, so arriving
    # from Google OAuth or a Stripe redirect (top-level GETs) stays signed in.
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    stripe.api_key = settings.stripe_secret_key or None

    # Bucket: GCS in production; in development a folder with the same keys, `instance/bucket/`
    # unless LOCAL_BUCKET_DIR names another. The test suite swaps in a throwaway one (conftest.py).
    if settings.is_production:
        # Cloud Run's front end appends the client's address to X-Forwarded-For; without this,
        # remote_addr is the proxy's, and every visitor shares one rate-limit bucket.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)  # ty: ignore[invalid-assignment]  # Flask documents wrapping wsgi_app with middleware; its stub types it as a method
        from helpers.storage import GCSBucket
        app.config["BUCKET"] = GCSBucket(settings.gcs_bucket_name)
    else:
        from helpers.storage import LocalBucket
        app.config["BUCKET"] = LocalBucket(settings.local_bucket_dir or get_data_path("bucket"))

    if config_class:
        app.config.from_object(config_class)

    # Initialize Extensions
    db.init_app(app)

    # No database work at import in production: --preload imports the app
    # before gunicorn opens its port, so a connect here holds the first
    # request for a Neon wake (ADR 0015).

    # Tests bring their own schema + fixtures (conftest.py's setup_db drops and
    # recreates everything per test), so seeding here would be thrown away —
    # skip it and keep the suite fast and deterministic. Production lands
    # content and announcements with `flask release` at deploy (ADR 0015),
    # because a query here would hold gunicorn's port shut while Neon wakes.
    if settings.is_development and not app.config["TESTING_DB"]:
        # Dev: run synchronously — no need for the loading gate locally
        with app.app_context():
            db.create_all()
            try:
                created = seed_development()
                if created is not None:
                    print(f" * Seeded from seed/seed.toml: {created}")
            except SeedError as e:
                db.session.rollback()
                print(f" * seed/seed.toml skipped: {e}")

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    
    # Initialize OAuth with app directly
    oauth.init_app(app)
    
    global google
    google = oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    migrate.init_app(app, db)
    limiter.init_app(app)
    compress.init_app(app)

    # Register Blueprints
    from routes.administrator import administrator_bp
    from routes.api import api_bp
    from routes.assistant import assistant_bp
    from routes.auth import auth_bp
    from routes.base import base_bp
    from routes.learner import learner_bp
    from routes.school_admin import school_admin_bp
    from routes.teacher import teacher_bp
    from routes.volunteer import volunteer_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(base_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(volunteer_bp)
    app.register_blueprint(learner_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(administrator_bp, url_prefix="/admin")
    app.register_blueprint(school_admin_bp)
    app.register_blueprint(assistant_bp)

    # Template Filters & Context Processors
    app.template_filter("markdown")(render_markdown)
    app.context_processor(inject_now)
    app.context_processor(inject_version)
    app.context_processor(inject_site_settings)
    app.context_processor(i18n_context_processor)

    # jx components share Flask's env. Flask picks autoescape by extension, so
    # `.jx` must join the list before any component compiles — a compiled
    # template keeps the escaping it was compiled with.
    app.jinja_env.autoescape = lambda name: name is None or name.endswith(
        (".html", ".htm", ".xml", ".xhtml", ".svg", ".jx"))
    # `app.debug` is still False here in dev (app.run(debug=…) comes later).
    app.extensions["jx"] = build_catalog(app.jinja_env, auto_reload=settings.is_development)

    @app.route("/health")
    def health():
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"status": "ok"}), 200
        except Exception as e:  # noqa: BLE001 - health check must report ANY DB failure, not just recognized ones
            return jsonify({"status": "error", "detail": str(e)}), 503

    # Audio: a cache in front of ElevenLabs — stored file, else generated if listed (helpers/audio_cache.py)
    from helpers import audio_cache

    @app.route("/audio/<path:filename>")
    def serve_audio(filename):
        return audio_cache.serve(filename)

    # Language switcher route
    from flask import redirect, session
    from flask import request as flask_request
    @app.route("/set-language", methods=["POST"])
    def set_language():
        lang = flask_request.form.get("lang", "en").strip().lower()
        # Validate: 2-7 char language code
        if lang and 2 <= len(lang) <= 7 and lang.isalpha():
            session["ui_lang"] = lang
        next_url = safe_local_path(flask_request.form.get("next")) or same_site_referrer_path() or "/"
        return redirect(next_url)

    # Cache-Control headers
    PUBLIC_CACHEABLE_ENDPOINTS = {
        "base.home", "base.about", "base.schools",
        "base.articles_list", "base.article_detail",
    }

    @app.after_request
    def set_cache_headers(response):
        endpoint = request.endpoint or ""
        if endpoint in PUBLIC_CACHEABLE_ENDPOINTS and request.method == "GET" and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
            # A fragment response (ui.pagination's swap fetch, X-Fragment: 1) and
            # the full page live at the same URL — without Vary, a shared/CDN
            # cache primed by one would serve it back for the other.
            response.headers["Vary"] = "X-Fragment"
        elif response.status_code == 200 and request.method == "GET":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Request Instrumentation
    from helpers.analytics import (
        capture_exception,
        clear_request_context,
        finish_request_context,
        init_logging,
        log_warning,
        start_request_context,
    )
    init_logging()
    # Flask's default handler duplicates every record already emitted via the
    # root handler from init_logging(); drop it so each log line appears once.
    from flask.logging import default_handler
    app.logger.removeHandler(default_handler)

    @app.before_request
    def instrument_request():
        start_request_context()

    @app.before_request
    def refuse_cross_site_writes():
        if is_cross_site_write():
            abort(403)

    @app.after_request
    def instrument_response(response):
        return finish_request_context(response)

    @app.teardown_request
    def instrument_teardown(exception):
        clear_request_context(exception)

    @app.errorhandler(OperationalError)
    @app.errorhandler(InterfaceError)
    def handle_db_unavailable(e):
        """503 + Retry-After for a DB connection failure — more specific than
        `handle_exception` below, so Flask routes SQLAlchemy connection
        errors here instead. Why the connect is set up to fail fast rather
        than hang for the full wake: ADR 0010."""
        # DB unreachable — in prod this is almost always Neon serverless compute
        # waking from scale-to-zero (the first request after idle). Rather than a
        # 500, serve a friendly auto-refreshing "starting up" page. The failed
        # connect already kicked the wake, so a refresh or two lands on the real
        # page. More specific than the generic Exception handler below, so Flask
        # routes connection errors here.
        try:
            db.session.rollback()
        except Exception as rollback_error:  # noqa: BLE001 - rolling back a session already broken by a DB outage can fail its own unpredictable ways; this handler must never itself raise
            app.logger.debug("Rollback in handle_db_unavailable failed: %s", rollback_error)
        app.logger.warning(f"DB unavailable (cold start / waking) on {request.method} {request.path}: {e}")

        # JSON for API / AJAX callers so they can retry; HTML page for browsers.
        if request.path.startswith('/api/') or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            resp = jsonify({'error': 'starting_up', 'message': 'Server is starting, please retry shortly.'})
        else:
            resp = make_response(render_template("starting_up.html"))
        resp.status_code = 503
        resp.headers["Retry-After"] = "3"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Catch-all for anything `handle_db_unavailable` didn't (a bare 4xx/5xx,
        or a DB error too generic to be `OperationalError`/`InterfaceError`,
        e.g. `PendingRollbackError`). Logs/captures it, then returns JSON for
        API/AJAX callers or renders `pages/error.jx` for a browser — see the
        inline comment before the `render_template` call below for why that
        render is itself wrapped in a rollback-and-retry."""
        from helpers.current_user import current_user
        # Rollback any dead transaction before touching the session or lazy-loading user attrs
        try:
            db.session.rollback()
        except Exception as rollback_error:  # noqa: BLE001 - rolling back a session already broken by an unhandled exception can fail its own unpredictable ways; this handler must never itself raise
            app.logger.debug("Rollback in handle_exception failed: %s", rollback_error)
        try:
            user_id = str(current_user.id) if current_user.is_authenticated else None
        except Exception:  # noqa: BLE001 - current_user can fail loading in unpredictable ways (e.g. a still-broken session); this is only used for exception reporting, must never itself raise
            user_id = None
        try:
            status_code = int(getattr(e, "code", 500) or 500)
        except (TypeError, ValueError):
            status_code = 500

        if status_code >= 500:
            app.logger.error(f"Unhandled Exception on {request.method} {request.path}: {e}")
        elif status_code >= 400:
            app.logger.warning(f"HTTP {status_code} on {request.method} {request.path}")

        if isinstance(e, HTTPException) and status_code < 500:
            log_warning(
                "HTTP exception handled",
                status_code=status_code,
                exception_type=type(e).__name__,
                exception_message=str(e),
            )
        else:
            capture_exception(user_id, e, {"status_code": status_code, "handled": True, "path": request.path})

        # Return JSON for API routes OR if the client explicitly requested JSON (Fetch/AJAX)
        if request.path.startswith('/api/') or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'error': 'An unexpected error occurred.' if status_code >= 500 else str(e),
                'message': str(e) if status_code < 500 else 'An internal server error occurred.',
                'path': request.path
            }), status_code

        error_messages = {
            404: "The page you are looking for does not exist.",
            403: "You do not have permission to access this page.",
            401: "You must be logged in to access this page.",
        }
        error_message = error_messages.get(status_code, "Something went wrong.")

        # pages/error.jx renders the header, which touches current_user again (fresh
        # Flask-Login load_user() DB call, since the guarded access above never cached
        # a user if it raised). If the session was left in a broken state (e.g.
        # PendingRollbackError after the rollback above raced a still-waking DB), that
        # second touch throws again — this time uncaught (we're already inside the
        # errorhandler, so Flask won't route it through handlers again), producing a
        # raw unstyled 500 instead of this page. Rollback once more right before
        # rendering, and fall back to a dependency-free inline page if it still fails.
        try:
            db.session.rollback()
        except Exception as rollback_error:  # noqa: BLE001 - rolling back a session already broken by an unhandled exception can fail its own unpredictable ways; this handler must never itself raise
            app.logger.debug("Second rollback in handle_exception failed: %s", rollback_error)
        try:
            return render_template("@pages/error.jx", error_code=status_code, error_message=error_message), status_code
        except Exception:
            app.logger.exception(f"error page render failed on {request.method} {request.path}")
            return (
                (f"<!doctype html><html><head><title>{status_code} Error</title></head>"
                f"<body style=\"font-family:sans-serif;text-align:center;padding:4rem 1rem;\">"
                f"<h1>{status_code}</h1><p>{error_message}</p>"
                f"<p><a href=\"/\">Go to Home</a></p></body></html>"),
                status_code,
            )

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register CLI Commands
    register_commands(app)

    return app

app = create_app()

if __name__ == "__main__":
    development = app.config["SETTINGS"].is_development
    print(f" * APP_ENV: {app.config['SETTINGS'].env}")
    # Dev serves the same built static/css/tailwind.css as prod, so keep it
    # rebuilding while templates change. Only the reloader's parent starts the
    # watcher — the child it re-spawns on every code change sets WERKZEUG_RUN_MAIN.
    # Tailwind v3's --watch exits the moment its stdin closes, so it gets a pipe
    # held open by this process: the watcher lives exactly as long as the server.
    # Keep the Popen referenced — collecting it closes the pipe and stops the watch.
    if development and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        import subprocess
        import sys

        watcher = Path(__file__).resolve().parent / "scripts" / "tailwind.py"
        tailwind_watcher = subprocess.Popen(
            [sys.executable, str(watcher), "--watch"], stdin=subprocess.PIPE
        )
    app.run(debug=development)

# Request lifecycle — startup, errors, caching

What happens between a container starting and a page being served, and the
constraints that follow from running on scale-to-zero infrastructure.

## Dev vs production

`create_app()` reads `settings.py` once. `APP_ENV` names the environment,
`development` or `production` (required; unset or any other value stops
startup). Production → Postgres from `DATABASE_URL` and the GCS bucket named by
`GCS_BUCKET_NAME` (both required, or startup stops), JSON logs. Development →
SQLite at `instance/site.db`, the local bucket at `instance/bucket/` (or
`LOCAL_BUCKET_DIR`), `db.create_all()` and dev seeding (`helpers/seed/`: an
empty bucket is filled from `seed/files/`, the bucket's `content/` questions,
worksheets and announcements are imported, and `seed/seed.toml` creates the
schools, users, articles and site text when the database has no school and no
user). No account is created by default in any environment. Tests point the
app at in-memory SQLite through `TEST_DATABASE_URL`, which also skips seeding,
and swap in a throwaway bucket.

## Boot in production

Cloud Run scales to zero and Neon suspends its compute when idle, so the
first request after a quiet spell meets both a cold container and a sleeping
database. Cloud Run also throttles CPU outside requests, so anything a
container starts in the background crawls. Boot therefore only serves
(ADR 0015): `entrypoint.sh` execs gunicorn (`--preload`, 1 worker × 8
threads), and the schema is already current because the deploy ran
`flask release` before this revision took traffic.

**Nothing in `create_app()` may touch the database in production**:
`--preload` imports the app before gunicorn opens its port, so a connect at
import holds the first request for a Neon wake.
`tests/integration/test_release.py` counts the connects.

Keep the import light too: the import is most of a cold start, and on a
cold Cloud Run host every module file is a slow read. Load a heavy library on
first use: `lazy import x` at the top of the module (PEP 810), or an import
inside the function that needs it. The GCS client, Stripe, Authlib (Google
sign-in), Markdown and Flask-Migrate with Alembic (`flask db`, via
`MigrateCommands` in `commands.py`) all load this way, and the same test keeps
them out of the boot.

## A sleeping database

The production engine uses `connect_timeout=3`, `pool_pre_ping` and
`pool_recycle=280`. A connect that times out raises, and
`handle_db_unavailable` turns any `OperationalError`/`InterfaceError` into a
503 with `Retry-After: 3` — the "starting up" page for a browser, JSON
`{"error": "starting_up"}` for API/AJAX callers (ADR 0010). The failed connect
has already woken Neon, so a refresh lands on the real page.
`starting_up.html` stays standalone — no header, no `current_user`, no shared
CSS — because rendering anything that queries would loop.

## Errors

`handle_exception` catches the rest: logs it (5xx also goes to PostHog),
rolls back, and returns JSON `{error, message}` when the path is under `/api/`
or the request is JSON/AJAX, otherwise `pages/error.jx` — with a bare HTML
fallback if even that fails to render. So `abort(403)` in an AJAX route
becomes a toast-able JSON error with no extra code.

## Caching

Every 200 GET gets `Cache-Control: no-store` unless its endpoint is in
`PUBLIC_CACHEABLE_ENDPOINTS` in `main.py` (public pages, 60s plus
`Vary: X-Fragment`). The assistant's streamed POST sets `no-store` itself.

## Logging

In production, the root handler writes JSON lines with a `severity` so Cloud
Logging can filter on it; a plain stderr line lands as severity `DEFAULT` and
is invisible to `severity>=ERROR` alerts.

## App-level routes

`/health` (database ping, the container health check), `/audio/<file>`
(question audio: stored, or generated on first request if its text is on the
spoken list — [../learning/content.md](../learning/content.md)), `/set-language` (POST, stores
`ui_lang`). A language without a translations file is machine-translated
from English on first use and cached per process.

# Testing

## Running

```bash
uv run -m pytest                 # unit + web, narrowed to what your diff touches
uv run -m pytest --all-tests     # unit + web, no narrowing
uv run -m pytest --suite=all     # + integration (CLI, PDFs, lint over the repo)
uv run -m pytest tests/web/test_api.py -k quiz   # one area
uv run -m pytest -n 6            # parallel; worth it for full runs only
```

Always `uv run -m pytest`, never `uv run pytest` — the latter drops the repo
from `sys.path` and every import fails. Match the run to the change: a small
change runs the tests that cover it, a broad one runs the full suite.

## Where a test goes

| Layer | For | Marker |
|---|---|---|
| `tests/unit/` | no request: helpers, models, the AI scope and tools, scripts | `unit` |
| `tests/web/` | through the Flask test `client`: routes, pages, JSON contracts | `web` |
| `tests/integration/` | CLI commands, filesystem, PDF generation, migrations, repo-wide lint | `integration` |

**Every test module sets a module-level `pytestmark`.** Suites select by
marker, so an unmarked test is silently skipped by *every* suite. A suite that
selects nothing raises instead of passing on zero tests.

## The automatic narrowing

A default run maps the diff (plus untracked files) to the functions it
touches, follows their callers two levels, and runs only tests that mention
those names, their module, or the URL of a touched route. It falls back to
the full fast suite whenever narrowing would be a guess — test support files,
`conftest.py`, `pyproject.toml`, the lock or the selector itself changed, the
change reaches nothing or most things, a path or `-k` is on the command line.
The `changed:` header line says which.

It can't see dynamic calls (`getattr`), URLs built at runtime, or templates
named by variables. So: **write URLs in tests as plain string literals, and
reach the code under test by name.** Engine: `scripts/change_selection.py`.

A local run also rebuilds `static/css/tailwind.css` when its sources are
newer — expect that file to change.

`tests/unit/test_no_live_leftovers.py` fails while a live variant session is
open in `templates/`. That is intended: accept or discard it first
(`uv run scripts/live.py status`). It also fails on any stray `data-live-*`
attribute or variants-file comment in `templates/` or `static/`, the debris of a
botched accept or hand edit; delete the line it names.

## Fixtures and helpers

The `app` is built once per session on shared in-memory SQLite (it refuses to
run against a file database). `db_session` empties every table at the
*start* of each test, so a failed test's data stays inspectable.

- `client` — test client **over an empty database** (it depends on
  `db_session` on purpose, so no test sees another's rows).
- `school`, `learner`, `teacher`, `volunteer`, `admin`, `school_admin`,
  `pair` — one persisted row each; `authenticated_<role>` — the same, signed
  in on `client`; `login_as(client, user)` for anything else.
- `tests/support/factories.py` — `make_<model>(session, **overrides)` for
  every model. The first row of a kind in a test gets the literal default
  (`"learner"`, `teacher@example.com`), later ones a `-2`, `-3` suffix.
- `tests/support/assertions.py` — `assert_denied(response)` accepts any of
  the app's refusal shapes (401/403/404/redirect); use it instead of pinning one.
- `rate_limits_on` — limiting is off in tests unless a test asks for it.
- `external_events` — captured PostHog events.
- Doubles: `use_fake_provider` (`tests/support/ai.py`) for the assistant,
  `FakeBucket` (`tests/support/storage.py`) for files.

Only `db`, `auth` and `jx` support modules load as plugins; import the rest.

## House style

- One behaviour per test, named for it:
  `test_deleting_a_volunteer_releases_their_learners`.
- Assert on status, redirect target, JSON keys or persisted rows — no HTML
  snapshots.
- Import application modules inside the test body, so a broken import fails
  one test, not collection.
- AJAX-form routes (those branching on `wants_json()`) need the header
  `X-Requested-With: XMLHttpRequest` to take their JSON branch.
- Never mutate `app.config` except through `monkeypatch.setitem` — the app is
  shared by every test.
- A real `google.cloud.storage.Client` or a real PDF costs seconds: fake the
  module, or mark the test `slow`.
- A defect a test uncovers gets `@pytest.mark.xfail(strict=True, reason=…)`,
  never a skip or a softened assertion — strict flips to a failure the day
  it's fixed.
- Dev-only tools (`/dev/*`, `scripts/`) are tested for what would hurt if it
  broke unnoticed (being reachable in production, auth bypass), not for
  convenience behaviour.

## Authorization matrix

`tests/web/test_authorization.py` walks every URL in the app against a
hand-written role policy and proves anonymous users and wrong roles are
refused — [../backend/access-control.md](../backend/access-control.md).

## Pytest is half of "done"

A green suite proves the contracts; it doesn't prove the page works. The
CLAUDE.md "done means it works in the real app" checklist still applies.

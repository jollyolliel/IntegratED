# Test suite

Organized by contract boundary:

- `tests/unit/` — deterministic helper, model, AI-scope and AI-tool behavior.
- `tests/web/` — Flask request, authorization, and JSON contracts.
- `tests/integration/` — CLI, PDF, backup, database and multi-step workflows.
- `tests/support/` — fixtures and doubles, loaded through `pytest_plugins`.

`docs/development/testing.md` is the full reference: fixtures, factory
conventions, house style, and the changed-code selection.

## Commands

```text
pytest                             # fast unit + web, narrowed to the current diff
pytest --all-tests                 # same suite, no narrowing
pytest --suite=unit                # one layer; also web, integration, slow, external
pytest --suite=unit,integration    # comma-separated marker selection
pytest --suite=all                 # everything, including integration boundaries
pytest --suite=all --durations=20  # find the slow ones
pytest -n 6                        # parallel; worth it for a full run only
```

`-n` is not in `addopts` on purpose: each worker imports the app and builds its
own schema, about 3s that a narrow `-k` selection would pay for nothing.

## Changed-code selection

A plain `pytest` does not run every fast test. It asks git what differs from
`HEAD` — staged, unstaged and untracked — and runs only the tests that change
can reach, typically 5-50 of them in 4-8s instead of ~23s. The header line says
what it decided:

```text
suite: fast
changed: 7 of 669 tests in 1 file(s) [routes/api.py: api_mark_lesson_completion]; --all-tests runs everything
```

How a changed line reaches a test:

1. `git diff HEAD --unified=0` gives changed line ranges per file.
2. Each range is resolved against the file's AST to the function, method or
   class containing it. A line outside every symbol — an import, a constant —
   counts as a change to the whole module.
3. Callers are followed two hops out, so an edit to a helper reaches the view
   that calls it.
4. Each reached symbol contributes signals: its name, its module, the URL rules
   of its `@route` decorators, and the templates it renders. A changed template
   maps back through the views that render it.
5. Every test is indexed the same way — the names it references, the URL strings
   it writes, its markers — and a test is selected when its own body or its
   module-level code matches a signal. Test files that match nothing are never
   imported, which is where the time goes.

An edited test file always runs its own edited tests.

### When it runs everything anyway

By design, not by accident: a fast run that skips the regression you just wrote
would be worse than a slow one. The `changed:` line names the cause.

| Cause | Fix |
|---|---|
| `git could not report what changed` | not a repo, no git, or no commits — nothing to do |
| `nothing changed since HEAD` | expected on a clean tree, and what CI always sees |
| `<path> changed` | `pyproject.toml`, `uv.lock`, `tests/conftest.py`, `tests/support/`, `.coveragerc` or `scripts/change_selection.py` — each one changes how everything runs. Commit or revert it |
| `no mapped file changed` | the edit is outside `routes/`, `helpers/`, `templates/`, `models.py`, `commands.py`, `extensions.py`, `main.py` |
| `the change reaches no test` | genuinely untested code — worth knowing |
| `N of M tests reached, over the 60% limit` | broad edit; narrowing would not pay |
| a path, `-k`, `-m`, `--lf` or `--all-tests` on the command line | you asked for a specific set; selection stays out of the way |

`PYTEST_ALL_TESTS=1` turns it off for a shell session.

### Working with it

- Write request URLs as plain string literals. `client.get("/api/garden")` is
  matched to the route; `client.get(f"/api/{name}")` is not.
- The mapping is static, so `getattr`-style dispatch is invisible to it. Code
  reached only that way runs when its module is edited, not its function.
- Run `pytest --all-tests` before you push, and after any change you would
  describe as "wide". CI always runs the full suite regardless.
- The engine is `scripts/change_selection.py`; its own tests are in
  `unit/test_change_selection.py`. Widening what it maps means editing
  `WATCHED_SOURCE_DIRS` there, with a test.

Every test file carries a module-level `pytestmark`. An unmarked test is
deselected by every suite, including `--suite=all`, and never runs.

Coverage is a CI concern only — `.github/workflows/tests.yml` adds
`--cov --cov-fail-under=78` to the `--suite=all` run. Instrumenting every module
roughly quintuples the wall time, which is a bad trade on a developer's machine.

## What the suite does not touch

No network, no real Postgres, no GCS, no PDF rendering outside the `slow`
marker, and no browser. Posthog, OpenTelemetry and flask-compress are replaced
in `sys.modules` before `main` is imported; the assistant's LLM provider and the
worksheet storage each have an in-memory double in `tests/support/`.

The database is a shared-cache in-memory SQLite schema created once per process;
rows are cleared between database-backed tests rather than the schema being
rebuilt. Tests that create or destroy schema state use `isolated_database`,
which restores the shared schema afterwards.

## Known application defects

Each is pinned by a test so it cannot regress further and cannot be forgotten.
No application code was changed to accommodate them.

| Defect | Pinned by |
|---|---|
| `POST /api/map/question` returns a 500 `"Configuration error"` when no `MapQuestion` rows are authored, so a fresh install shows a 500 to the first learner | `web/test_api.py::test_an_unconfigured_placement_test_answers_with_a_configuration_error` |
| `/admin/impersonate/stop` carries no `@login_required` and no `@admin_required`. It only pops a session key and redirects, so the effect is harmless — but the gate is missing | `web/test_authorization.py::test_impersonate_stop_is_a_harmless_no_op_when_signed_out` |
| The AI assistant sees only local-table columns, so `name` — which lives on the `users` base table — is not queryable on `Learner` or `Volunteer` | `unit/test_ai_scope.py::test_base_class_columns_are_not_filterable_on_a_subclass` |

# Development — start here

How work gets done in this repo: running it, testing, Python conventions,
translations, and the automatic checks that will stop you.

| You are… | Read |
|---|---|
| Writing or running tests | [testing.md](testing.md) |
| Writing Python — types, imports, docstrings, lint | [python-conventions.md](python-conventions.md) |
| Adding, changing or removing any user-visible text | [translations.md](translations.md) |

## Running it

- Copy `.env.example` to `.env`; `APP_ENV=development` is required.
- `uv run main.py` — dev server on `127.0.0.1:5000` with a Tailwind watcher;
  SQLite at `instance/site.db` and a local bucket at `instance/bucket/`, both
  filled on first run from `seed/`. Restart it after adding a new `.jx` file.
- **`seed/` and `instance/` hold throwaway development data.** The questions,
  worksheets, announcements, schools and users in them are samples; delete
  `instance/` and they come back.
- `seed/seed.toml` is where dev schools, users (with their fake plaintext
  passwords), articles, team members and site text are configured;
  `seed/files/` mirrors the bucket (`content/` for questions, worksheets and
  announcements, `worksheets/` for PDFs) and is copied into the dev bucket
  while it holds no file at all. Dev then imports from the bucket's `content/`.
  `uv run flask seed` re-applies it (insert-only);
  it only runs with `APP_ENV=development`, and nothing outside `helpers/seed/`
  reads `seed/`. Audio is generated into the bucket's `audio/` only with
  `TTS_ENABLED=true`. Delete `instance/site.db` and `instance/bucket/` to
  start over.
- `uv sync` installs from `uv.lock`; `uv add <pkg>` adds a dependency.
- `/dev/login-as?type=<learner|volunteer|teacher|school_admin|administrator>&next=/path`
  signs you in as that role; `/dev/components` is the component gallery.
  `next` is the full path with the role prefix (`next=/learner/map`, not
  `/map`) — see [access-control](../backend/access-control.md#dev-sign-in).
  "Sign in with Google" opens `/dev/google-sign-in`, which signs in or
  registers as any email you type, so `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
  can stay empty in `.env`; set them and the page also offers
  *Sign in with real Google*.
- `flask db upgrade` / `flask db migrate -m "…"` / `flask db current` for the
  schema; `grep -n "@click.command" commands.py` for the other CLI commands.

## The checks that run on their own

| When | What | Where |
|---|---|---|
| Before an edit or shell command touching `translations/*.json` | blocks hand edits — only the translation scripts may write them | `scripts/guard_translations.py` |
| End of every turn | on the files you changed: docstring length and "justification" wording in Python; dated lines in `docs/` and `.claude/rules/`; CSS class doc comments; the design lint; brace balance in CSS | `scripts/check_changes.py` |
| CI | ruff, ty, the full suite, the Postgres migration replay | [../operations/ci-and-releases.md](../operations/ci-and-releases.md) |

Hook output on stderr is blocking feedback: fix it in the same turn.

Other scripts in `scripts/`: `flood.py` (bulk dev data for load testing; the
generator is `helpers/flood.py`, which preview seeding also uses),
`list_analytics_events.py` (existing event names),
`tailwind.py` (CSS build), and the translation tools.

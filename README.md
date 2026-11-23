# IntegratED

A **youth-to-youth (Y2Y) learning platform** run from ACS Athens. Secondary-school
students volunteer as tutors for young refugees from The Home Project. Most of the
learners cannot yet read in any language, so the app has to teach, and be usable,
without relying on text.

Around each learner–volunteer **pair**, a school's teachers run the programme: they
build the roster, match pairs, log attendance, hand out worksheets and get help from an
AI assistant. School admins and a global administrator run schools, people, donations
and site content. The public site tells the programme's story and takes donations.

| Role | Signs in with | Does |
|---|---|---|
| Learner | username + password, via an invite code | survey, placement test, learning path, minigames, worksheets, XP and avatar |
| Volunteer | Google, via an invite code | sees their learners, sessions and worksheets; survey for matching |
| Teacher | Google (school domain) | roster, matching, attendance, worksheets, AI assistant |
| School admin | username + password | one school's people, settings, donations, attendance |
| Administrator | username + password | every school and user, CMS, database console |

## Stack

One Flask monolith: Jinja / [jx](https://pypi.org/project/jx/) components with
Tailwind CSS, SQLAlchemy with Alembic migrations, Postgres in production and SQLite
in development. It runs on Google Cloud Run, with files in a Cloud Storage bucket.
Python dependencies are managed with [uv](https://docs.astral.sh/uv/).

## Running it locally

You need Python 3.12+ and uv.

```sh
cp .env.example .env      # APP_ENV=development is required
uv sync                   # install from uv.lock
uv run main.py            # http://127.0.0.1:5000
```

The first run creates a SQLite database at `instance/site.db` and a local bucket at
`instance/bucket/`, both filled with throwaway sample data from `seed/`. Delete
`instance/` to start over. In development:

- `/dev/login-as?type=teacher&next=/teacher/` signs you in as any role
  (`learner`, `volunteer`, `teacher`, `school_admin`, `administrator`)
- "Sign in with Google" opens a local stand-in, so no Google credentials are needed
- `/dev/components` is the component gallery

## Checks

```sh
uv run -m pytest          # tests (use `-m pytest`, not bare `pytest`)
uv run ruff check .       # lint
uv run ty check           # types
```

CI runs all three on every pull request, plus CodeQL code scanning and a migration
replay on Postgres.

## Documentation

Start with [docs/system-design.md](docs/system-design.md) for the whole picture and
[docs/CONTEXT.md](docs/CONTEXT.md) for the vocabulary. Each folder under `docs/` has a
README that points to the one file you need:

| Area | Start at |
|---|---|
| Pages, components, CSS, copy | [docs/ui-design/](docs/ui-design/README.md) |
| Routes, permissions, models, migrations | [docs/backend/](docs/backend/README.md) |
| Placement test, learning path, minigames | [docs/learning/](docs/learning/README.md) |
| Matching, worksheets, AI assistant, attendance | [docs/features/](docs/features/README.md) |
| Deploys, CI, secrets, the production database | [docs/operations/](docs/operations/README.md) |
| Tests, conventions, translations | [docs/development/](docs/development/README.md) |
| Why things were decided | [docs/adr/](docs/adr/) |

## Contributing

Open an issue first for anything beyond a small fix. Pull requests target `master`
and need green tests and code scanning. User-facing text goes through translation
keys (see [docs/development/translations.md](docs/development/translations.md)).

## Security

Please report vulnerabilities privately, never in a public issue. See
[SECURITY.md](SECURITY.md).

## License

[PolyForm Noncommercial 1.0.0](LICENSE): free to use, change and share for
noncommercial purposes.

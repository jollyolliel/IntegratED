# Production database

Neon PostgreSQL 17, reached through `DATABASE_URL` (a pooled connection
string; the app rewrites `postgres://` to the `psycopg2` driver). Dev is
SQLite — the differences between the two are the main source of
production-only failures.

## Neon sleeps

Neon suspends compute when idle and wakes on the next connection, taking a
few seconds. The app fails that first connect fast and shows a self-refreshing
"starting up" page ([../backend/request-lifecycle.md](../backend/request-lifecycle.md),
ADR 0010). That covers a sleeping database; a cold *container* is Cloud Run's
own wait. Turning off Neon's scale-to-zero removes the wake at the cost of
idle compute.

## Migrations in production

- They run once per deploy, before the new revision takes traffic, as the
  first step of `flask release` in the `integrated-release` Cloud Run Job
  (ADR 0015). Any failed step fails the job and stops the deploy; the old
  revision keeps serving. Its logs:
  `gcloud run jobs executions list --job integrated-release --region <GCP_REGION>`.
- The old revision serves while the job runs, so a migration must work with
  the code before it: add a column before code uses it, drop one only in a
  later deploy, once no running code reads it. A column waiting for that drop
  is listed in `AWAITING_DROP` (`tests/support/migrations.py`) so the schema
  checks accept it: `schools.invite_code_expires_at` (since `d4b8f2a6c1e3`),
  to be dropped in a later deploy.
- Write them dialect-agnostic ([../backend/data-model.md](../backend/data-model.md));
  `migrations.yml` replays the chain on Postgres in CI, but it doesn't block
  a deploy.
- SQLite doesn't enforce foreign keys and doesn't enforce `VARCHAR` length;
  Postgres does both.
- A database created by `db.create_all()` and never migrated is adopted with
  `flask db stamp head`, then upgraded normally.

## What `flask release` does

Each deploy brings the database in line with the image and the bucket's
`content/` folder, in this order (`release_command` in `commands.py`):

1. Stage `content/` and validate `questions.json` and
   `worksheets/manifest.json`. A missing or invalid file fails the job here,
   before anything is written.
2. A **forced backup**: the backup below without its 7-day wait, taken before
   the migration or the prune can change anything. If it fails in production
   the job fails here. On SQLite it does nothing.
3. `flask db upgrade`.
4. Insert new announcements from `content/announcements.json`.
5. Import `content/questions.json` with pruning
   ([../learning/content.md](../learning/content.md)). The prune plan is
   printed to the job log before it is applied. Audio is never generated
   here (the web service makes it on first play), so the job needs no
   ElevenLabs key.
6. Sync the worksheet library from `content/worksheets/manifest.json`
   ([../features/worksheets.md](../features/worksheets.md)).

Every step is idempotent: a second run with the same image prints "Nothing to
remove", `0 added, 0 updated` and writes nothing. A failure after step 4
leaves what came before it committed; rerunning the job is safe. The job's task
timeout must cover a forced `pg_dump` (capped at 5 minutes) plus the import.

## Prod-only trigger: gmail teachers join ACS Athens

Prod (not dev, not tests, not any migration) has a `BEFORE INSERT` trigger
`teachers_gmail_to_acs` → function `assign_gmail_teacher_to_acs()`. It sets
`school_id = 1` (ACS Athens) on any new teacher whose email ends
`@gmail.com` and arrives with no school, overriding the app's
unaffiliated-gmail-teacher path. Remove with
`DROP TRIGGER teachers_gmail_to_acs ON teachers;`.

## Backups

`flask backup-db` (`helpers/backup.py`) runs daily at 03:00 Athens time as
the `integrated-backup` Cloud Run Job, triggered by the Cloud Scheduler job
of the same name, and no-ops outside production or without a Postgres URL:

- If the last check (`backups/latest.json` in the bucket) is under 7 days old,
  it stops.
- Otherwise it `pg_dump`s the database and hashes the dump; an unchanged hash
  only refreshes the check time, a changed one uploads a new gzipped
  `backups/db_<timestamp>.sql.gz` and moves the manifest to it.
- Every failure is logged and swallowed; the next day's run retries. The
  forced backup in `flask release` raises instead.

So backups are weekly, or later when nothing changed. The job runs the image
of the last deploy, which updates it.

**Restore**: download the blob, `gunzip`, `psql "$DATABASE_URL" < dump.sql` —
into a scratch database first when testing a restore.

## Handy commands

`grep -n "@click.command" commands.py` lists the app's CLI commands with their
purpose (`flask diagnose-teacher`, `fix-teacher-assignments`,
`sync-sequences`, `uv run scripts/flood.py` for load testing a dev database, `flask seed` to refill the dev bucket and database from `seed/`…).

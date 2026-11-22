# Migrate at deploy, not at boot; a booting container only serves

ADR 0009 ran `flask db upgrade`, the announcement sync and the backup check
in the background of every container boot, behind a request gate. Cloud Run
throttles a container's CPU to almost nothing outside requests, so that
background work only advanced during the few milliseconds each "starting up"
page took to serve: in October 2026 logs a migration that takes seconds took
minutes, and one sync finished 13 minutes after boot while a user refreshed
the loading page and gave up. Each step also re-imported the whole app, and
the import itself queried the database.

The decision is that a booting container only imports the app and serves.
The deploy runs `flask release` (upgrade, then announcement sync) as the
`integrated-release` Cloud Run Job and deploys the new revision only after
it succeeds; the backup check is the daily `integrated-backup` job, which
keeps its own 7-day dedupe. Nothing in `create_app()` may touch the database
in production.

Rejected: keeping boot work and paying for always-allocated CPU (`--no-cpu-throttling`)
— it bills idle time on an app that is idle almost always; and a warm
minimum instance, for the same reason.

Consequences: a failed migration now stops the deploy and leaves the old
revision serving, where before the gate opened onto the old schema anyway.
The old revision serves while the job runs, so a migration must work with
the code before it (add before use, drop after the last reader is gone).

Status: accepted. Supersedes ADR 0009.

# Migrations run in the background; requests wait behind a gate, not gunicorn

The straightforward way to guarantee a container never serves traffic
against an unmigrated schema is to run `flask db upgrade` before starting
gunicorn. That was the original approach, but on Cloud Run with zero warm
instances, the migration plus the database's own cold-start wake could take
on the order of twenty seconds — and for that whole window the container's
port was never bound at all. Cloud Run had nothing to proxy requests to,
so the app appeared completely dead rather than merely slow.

The decision is to start `flask db upgrade` as a background job and launch
gunicorn immediately, so the port binds right away regardless of how long
the migration takes. A request-level hook, registered before every other
hook so it never touches the database itself, checks for a flag file the
background job touches on completion (success or failure) and serves a
lightweight, self-refreshing "starting up" page until that file appears —
turning an invisible container into a visibly-loading one. The trade-off is
that correctness now depends on that gate running first on every request
except the health check, and a failed migration is silent unless the
container logs are checked — the flag file is touched either way so the
loading page can't hang forever, but a broken migration means the app comes
up and immediately starts serving against the old schema instead of staying
down.

Status: superseded by ADR 0015 — Cloud Run's CPU throttling starved the
background work, so migrations moved to a deploy-time job.

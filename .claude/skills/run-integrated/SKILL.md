---
name: run-integrated
description: Run, start or smoke-test the IntegratED Flask app locally, and sign in as any role to check a change in the real app. Use when asked to run the app, verify a feature, or confirm a fix works.
---

The rules for what "verified" means are in `CLAUDE.md` ("Done means it works in the real
app"); this is only the mechanics.

## Start the server

Reuse one that is already up: `curl -s 127.0.0.1:5000/health` answers `{"status": "ok"}`.
Otherwise start it in the background:

```bash
uv run main.py
```

It serves `http://127.0.0.1:5000` with a Tailwind watcher, SQLite at `instance/site.db` and a
local bucket at `instance/bucket/`, both filled from `seed/` on first run. Restart it after
adding a new `.jx` file. A new migration needs `uv run flask db upgrade` first.

## Sign in as a role

`/dev/login-as?type=<learner|volunteer|teacher|school_admin|administrator>&next=/path` signs the
browser in with no password (creating a user of that role if none exists). `next` is the full
path with its role prefix (`/learner/map`, not `/map`). Learner onboarding state:
`&survey=0|1`, `&map_test=0|1|deferred`. Bare `/dev/login-as` lists users as JSON.

Drive pages with Claude in Chrome, never Playwright or a headless browser.

## Smoke script

```bash
uv run .claude/skills/run-integrated/smoke.py            # --base http://127.0.0.1:5001
```

Signs in as each role through `/dev/login-as` and loads its key pages; every line should
read `[OK]`.

# Deployment

## How a change reaches production

Every push to `master` builds and deploys through `.github/workflows/deploy.yml`
— **not gated on the test workflow** — unless the push is skipped
([ci-and-releases.md](ci-and-releases.md)). The job builds the image from
`DOCKERFILE` (uppercase — the only spelling git tracks, and Linux CI is
case-sensitive) with `GIT_SHA` baked in, pushes it tagged with the commit
SHA, runs the `integrated-release` job on that image (`flask release`:
migrate, sync announcements, back up, import content, sync worksheets —
[database.md](database.md); a failure stops the deploy here), runs
`gcloud run deploy integrated --image …:<sha>`, and points the
`integrated-backup` job at the new image. The footer shows that SHA, linked
to the commit; locally it reads `dev` and is hidden.

The deploy changes only the image. The service's environment variables and
secret mounts are configured on the Cloud Run service itself and survive
deploys.

## The image

Two stages:

1. **Tailwind**: a slim Python image builds `static/css/tailwind.css` with the
   standalone Tailwind CLI (`scripts/tailwind.py`). It copies only what
   Tailwind's `content` scans — a new file holding class names must be copied
   here too, or its classes are purged in production only.
2. **App**: `python:3.15-slim` + `postgresql-client-17` (for backups, from the
   PGDG repo to match Neon's version); no compiler or `-dev` headers, since
   every dependency in `uv.lock` ships a prebuilt wheel — a dependency that
   needs one would have to build in its own stage. `uv` is pinned once as the
   `uv` stage, inside the `required-version` range in `pyproject.toml`. Dependencies install with `uv sync --locked --no-dev` into
   `/opt/venv`, outside `/app`. The code is copied with `--chown`, never a
   recursive `chown`, which would store a second copy of it. Runs as non-root
   `appuser`, port 8080.

`.dockerignore` keeps out `.env`, tests, scripts (except `tailwind.py`),
`.claude/`, docs, lint and the whole of `seed/`, with no exceptions:
production reads questions, worksheets, announcements, PDFs and audio from the
bucket. It also excludes `gha-creds-*.json`: CI authenticates to Google
*before* `docker build`, and `COPY . .` would otherwise bake the credential
into the image.

## Dependencies

`pyproject.toml` lists only packages the app imports directly; `uv.lock` pins
everything. Test-only packages live in the `dev` group so `--no-dev` keeps
them out of the image. Editing either table means `uv lock` in the same change
— a stale lock fails `uv sync --locked` in Docker and CI. Never add the bare
`dotenv` package; it shadows `python-dotenv`.

## Startup

`entrypoint.sh` execs gunicorn (1 worker × 8 threads, gthread, `--preload`,
60s timeout) and does nothing else: Cloud Run throttles CPU outside requests,
so work a container starts in the background crawls (ADR 0015,
[../backend/request-lifecycle.md](../backend/request-lifecycle.md)).
Database work runs as Cloud Run Jobs on the same image:

| Job | Runs | Command |
|---|---|---|
| `integrated-release` | every deploy, before the service | `flask release` |
| `integrated-backup` | daily 03:00 Europe/Athens (Cloud Scheduler `integrated-backup`) | `flask backup-db` |

Both take `APP_ENV=production`, `GCS_BUCKET_NAME`, `GOOGLE_CLIENT_ID` and the
`DATABASE_URL`, `SECRET_KEY` and `GOOGLE_CLIENT_SECRET` secrets — not the
PostHog keys, so job runs stay out of analytics. A new setting the CLI needs
goes on the jobs as well as the service.

## Configuration

**Secrets come from Secret Manager via `--set-secrets`, never
`--set-env-vars`**: Cloud Run's audit log records plain env var values in full
on every deploy. Secret names equal the env var names. To rotate, add a new
secret version; running revisions keep the old one until the next deploy.

| Variable | Kind | Notes |
|---|---|---|
| `SECRET_KEY` | secret, required | session signing |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | env / secret, required | Google sign-in |
| `DATABASE_URL` | secret, required in production | Neon pooled URL; never read in dev |
| `GCS_BUCKET_NAME` | env, required in production | content, worksheets, audio, images, backups |
| `LOCAL_BUCKET_DIR` | env, development | the dev bucket's folder; default `instance/bucket/` |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | secret | donations |
| `POSTHOG_API_KEY`, `POSTHOG_HOST`, `POSTHOG_PERSONAL_API_KEY` | secret / env / secret | analytics; the personal key is needed for feature-flag evaluation, without it flag checks warn and no-op |
| `GEMINI_AISTUDIO_API_KEY`, `ASSISTANT_PROVIDER`, `ASSISTANT_MODEL`, `ASSISTANT_MODEL_FALLBACK` | secret / env | AI assistant |
| `ELEVEN_API_KEY` | secret | text-to-speech, generated on a question's first play (the web service needs it) |
| `APP_ENV` | env, required | `development` or `production`; no default, and anything else stops startup. The service and both Cloud Run jobs set `production`; nothing is auto-detected |
| `CONTACT_EMAIL`, `GITHUB_REPO_URL` | env | legal-page contact line and footer link; each is left out when empty |
| `TTS_ENABLED`, `ELEVEN_VOICE_ID`, `ELEVEN_MODEL_ID` | env | audio generation is off unless `TTS_ENABLED=true`; set it on the web service |
| `RATELIMIT_STORAGE_URI` | env | default per-process memory |
| `TEST_DATABASE_URL` | tests | set by the test harness |

The deploy workflow takes its ids from GitHub repository variables, not from
the file: `GCP_PROJECT_ID`, `GCP_REGION`, `CLOUD_RUN_SERVICE`, `ARTIFACT_REPO`,
and `DEPLOY_SERVICE_ACCOUNT`. It only updates the image: the variables in the table
are set on the Cloud Run service and on the `integrated-release` and
`integrated-backup` jobs themselves, so a deploy never overwrites them. Apart from
`ASSISTANT_*` and `RATELIMIT_STORAGE_URI`, every value in the table is read once
at startup by `settings.py`; nothing else reads them from the environment.

Locally all of these come from `.env` (OS variables win). Only the variables
marked required stop startup when missing; an optional key left empty degrades
its one feature instead of breaking boot — keep new integrations that way.

## Logs

In production, logs are JSON lines with a `severity` field; anything printed
plainly lands as `DEFAULT` and escapes error alerts. Read them with
`gcloud run services logs read integrated --region=<GCP_REGION>` or in Cloud
Logging.

# Operations — start here

Read this before touching the Docker image, `entrypoint.sh`, GitHub
workflows, environment variables or secrets, the production database, or
when diagnosing production.

| You are… | Read |
|---|---|
| Changing the image, the startup script, dependencies, env vars or secrets; deploying; reading prod logs | [deployment.md](deployment.md) |
| Changing CI, Dependabot, the release/version or deploy-skip rules | [ci-and-releases.md](ci-and-releases.md) |
| Running migrations in prod, backups and restores, Neon behaviour | [database.md](database.md) |
| PR preview URLs: using them, `preview.yml`, `APP_ENV=preview`, the setup script | [previews.md](previews.md) |

What happens between a container starting and a page being served ("starting
up" page, error handlers): [../backend/request-lifecycle.md](../backend/request-lifecycle.md).

## Production at a glance

| | |
|---|---|
| Host | Google Cloud Run, service `integrated`, region and project from the `GCP_REGION` / `GCP_PROJECT_ID` repo variables; scales to zero |
| Image | `<GCP_REGION>-docker.pkg.dev/<GCP_PROJECT_ID>/<ARTIFACT_REPO>/integrated`, tagged with the commit SHA |
| Database | Neon PostgreSQL 17, scales to zero |
| Files | GCS bucket named by `GCS_BUCKET_NAME`: `worksheets/` (PDFs), `content/` (full `questions.json`, manifest and markdown sheets), `audio/`, `backups/` |
| Secrets | Secret Manager, mounted with `--set-secrets` |
| Other services | Google OAuth, Stripe, PostHog (EU), Gemini (AI Studio), ElevenLabs |

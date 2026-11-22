# Operations — start here

Read this before touching the Docker image, `entrypoint.sh`, GitHub
workflows, environment variables or secrets, the production database, or
when diagnosing production.

| You are… | Read |
|---|---|
| Changing the image, the startup script, dependencies, env vars or secrets; deploying; reading prod logs | [deployment.md](deployment.md) |
| Changing CI, Dependabot, the release/version or deploy-skip rules | [ci-and-releases.md](ci-and-releases.md) |
| Running migrations in prod, backups and restores, Neon behaviour | [database.md](database.md) |

What happens between a container starting and a page being served ("starting
up" page, error handlers): [../backend/request-lifecycle.md](../backend/request-lifecycle.md).

## Production at a glance

| | |
|---|---|
| Host | Google Cloud Run, service `integrated`, region `europe-west1`, project `gen-lang-client-0738887160`; scales to zero |
| Image | `europe-west1-docker.pkg.dev/gen-lang-client-0738887160/integrated-docker/integrated`, tagged with the commit SHA |
| Database | Neon PostgreSQL 17 (project `IntegratED`, aws-eu-central-1), scales to zero |
| Files | GCS bucket named by `GCS_BUCKET_NAME` (`integrated-worksheets`): `worksheets/` (PDFs), `content/` (full `questions.json`, manifest and markdown sheets), `audio/`, `backups/` |
| Secrets | Secret Manager, mounted with `--set-secrets` |
| Other services | Google OAuth, Stripe, PostHog (EU), Gemini (AI Studio), ElevenLabs |

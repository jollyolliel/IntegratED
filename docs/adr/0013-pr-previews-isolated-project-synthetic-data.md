---
status: proposed
---

# PR previews: one Cloud Run service per PR, in a separate GCP project, on synthetic data, behind IAP

Testing a PR today means checking out the branch and running it locally. The
goal is a hosted **preview** per open PR: a URL that signs the reviewer in as
a chosen **persona** (e.g. a learner halfway through the path) and lands on
the page the PR changed. The preview is the real app (backend included), so a
new matching algorithm can be timed, not just looked at.

The preview runs **unreviewed code**. It therefore has to be safe even if that
code is hostile or simply buggy. Every boundary below is enforced *outside*
the PR's own code (IAM, project separation, missing credentials), because
anything enforced only inside the app is something the PR can edit away. The
learners are refugee minors. Their data never leaves prod, not even in
anonymised form.

## Decision

### 1. Where it runs: a separate GCP project, one service per PR

Each PR gets its own Cloud Run service, `pr-<number>`, in a new project
(`integrated-preview`) with its own Artifact Registry repo. A preview service
runs as a dedicated **runtime service account with zero IAM roles**. It has no
Secret Manager access, no GCS bucket and no Neon credential, because none
exists in that project to grant.

Not the prod project. Cloud Run defaults to the Compute Engine default service
account, and in prod that account holds `secretAccessor` on every prod secret
(`deployment-ops.md`). Any code running as it can read `DATABASE_URL`,
`SECRET_KEY` and the Stripe keys from the metadata server. A project boundary
makes that impossible by construction rather than by remembering a
`--service-account` flag.

### 2. Data: SQLite inside the container, built from a seed script at boot

No database credential is ever given to a preview. On boot the container:

1. runs `flask db upgrade` against an empty SQLite file in `/tmp`, which
   exercises the PR's own migration chain;
2. runs a new `flask seed-preview` command. It is deterministic (fixed RNG
   seed) and builds on `helpers/flood.py`, `data/questions.json` and a fixed
   list of **personas**: `learner-new` (placement not taken),
   `learner-midpath`, `learner-matched`, `volunteer`, `teacher`,
   `school-admin`, `admin`. Each persona has a known slug, and all names are
   generated.

The seed is a script, not a committed `.db` snapshot. A snapshot goes stale
the moment a PR changes the schema. A script runs *after* the PR's migrations,
so it always matches the PR's schema, and a PR that changes the schema updates
the seed in the same diff.

The service runs with `--max-instances=1`, so there is exactly one database.
Scale-to-zero or a redeploy resets it to the seed. That is intended: every
preview starts from a known state.

Prod data is never a source: no Neon branch of prod, and no restore of a
`backups/` dump.

### 3. A third app mode: `PREVIEW`, fail-closed

`create_app()` currently has two modes, dev and deployed, and `K_SERVICE`
alone forces deployed mode, which demands `DATABASE_URL` and GCS. Previews add
a third mode, switched on by `INTEGRATED_PREVIEW=1`. It behaves like
production for serving (gunicorn, image, templates) and like dev for
infrastructure:

| Concern | Preview behaviour |
|---|---|
| DB | SQLite in `/tmp` (step 2) |
| `SECRET_KEY` | random per container, generated at boot. Sessions die with the container, as the data does. |
| Worksheet storage | `LocalWorksheetStorage`. `data/worksheets/` is excluded from the image, so the seed writes synthetic markdown worksheets. |
| PostHog | off (no key), so prod analytics never see preview events |
| Stripe | off (no key). Donation pages render, and checkout shows as unavailable rather than calling Stripe. |
| ElevenLabs TTS | off (no key). `generate_audio` already fails soft. |
| Google login | placeholder `GOOGLE_CLIENT_ID`/`SECRET` (they are read with `os.environ[...]`). Non-functional, and personas replace it. |
| Teacher AI assistant | a scripted `fake` provider registered in `helpers/ai/registry.py` (the ADR 0007 seam). No LLM key. |
| `/dev/components` | available (it already 404s only when deployed) |
| Every response | a "PREVIEW · PR #N · fake data" banner, plus `X-Robots-Tag: noindex` |

**Boot guard.** In preview mode the app refuses to start if any prod signal is
present: `DATABASE_URL`, `GCS_BUCKET_NAME`, `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `GOOGLE_CLIENT_SECRET` other than the placeholder,
`K_SERVICE == "integrated"`, or the prod project ID in
`GOOGLE_CLOUD_PROJECT`. This catches the inverse mistake as well: prod
accidentally given `INTEGRATED_PREVIEW=1` crashes on boot rather than exposing
a login bypass. The `/_preview` blueprint is only *imported* in preview mode.
Tests cover both directions: the guard raises, and `/_preview/*` 404s outside
preview mode.

### 4. Access: IAP in front of every preview

Each preview is deployed with `--no-allow-unauthenticated --iap`, which puts
Identity-Aware Proxy directly on the `run.app` URL with no load balancer. Only
Google accounts granted `roles/iap.httpsResourceAccessor` on the preview
project can reach any page. The container's own health check hits
`localhost`, so it never passes through IAP.

The GCP project sits under no Organization. Google-managed IAP OAuth clients
only serve users *inside* an organization, so IAP needs a **custom OAuth
client** (one-time setup). Its secret is stored in IAP's own settings and never
reaches the app or the container.

IAP is what makes a one-click login bypass acceptable. Without it, the URL is
public and anyone who finds it is an admin of the preview.

### 5. Auto sign-in: persona links

`GET /_preview/enter?as=<persona>&next=<path>` logs in as that persona and
redirects:

- `as` must be a seeded persona slug. It is not a user ID, so the link can't
  reach an arbitrary row.
- `next` must be a same-origin path (the usual open-redirect rule). No
  open redirect.
- It is a GET, so it is CSRF-able. That is accepted: it only exists behind
  IAP, and it only switches between fake accounts.

`GET /_preview/` is the hub. It lists every persona with a sign-in button, a
path box, the PR's suggested links, the seed controls (step 7), and the commit
SHA being previewed.

### 6. Picking the page per PR: a `preview` block in the PR description

A PR author writes, in the description:

````md
```preview
learner-midpath /learner/quiz
teacher         /teacher/matching
```
````

The workflow reads the PR body through an env var (never inlined as `${{ }}`;
same rule as `deploy.yml`) and validates each line:

- persona must match `^[a-z0-9-]+$` and be a known slug;
- path must match `^/[A-Za-z0-9/_.\-?=&%]*$`.

Bad lines are dropped and listed. Valid lines become clickable
`/_preview/enter` links in **one sticky PR comment** that is edited on every
push, not reposted. No block in the description means the comment links only
the hub.

### 7. Backend testing: seed sizes plus a baseline preview of `master`

- **Seed sizes.** `small` is the default. `large` (thousands of
  learners/volunteers, sized for matching) is selectable from the hub by POST,
  with fixed caps. The size can't be an arbitrary number, which keeps reseeding
  cheap and memory-bounded.
- **Baseline.** A long-lived `main` service in the preview project is
  redeployed on every push to `master`, using the same image recipe, CPU,
  memory and seed. "Is the new matching faster?" is answered by running the
  same seed size on `pr-N` and on `main`: same hardware, same data, old code vs
  new.
- **Timing.** Preview mode adds a `Server-Timing` header (total and DB time),
  so browser devtools show backend cost per request with no extra UI.

These numbers are **relative only**. SQLite, one small instance and cold
starts make them unlike prod's absolute numbers. Postgres dialect correctness
is already covered by `migrations.yml`, which replays migrations on Postgres
17.

### 8. Pipeline: `preview.yml`, with the boundary in IAM rather than the workflow

A `pull_request` workflow runs the workflow file **from the PR's head**, so a
PR can rewrite it. The workflow is therefore not trusted to protect anything,
and the real limits live in Google Cloud IAM:

- **Narrow the prod deployer first (prerequisite).** Today the prod deploy
  service account trusts *every* workflow run in the repo from any branch
  (WIF binding on `attribute.repository`, no ref condition). Before any
  workflow that runs PR code ships, map `attribute.ref` and restrict that
  binding to `refs/heads/master`. Better still, restrict it to the `production`
  environment claim.
- **A separate preview deployer service account.** Bound to the same pool but
  allowed for PR refs, with roles only in `integrated-preview` (deploy Cloud
  Run, push to its registry, act as the zero-role runtime account). A hijacked
  preview workflow can at most deploy something into the preview project.

The workflow itself:

- Triggers on `pull_request` (`opened`, `synchronize`, `reopened`, `closed`).
  It never uses `pull_request_target`, which runs with the base branch's
  secrets. It skips Dependabot (consistent with Dependabot's smoke-only CI)
  and cross-repo/fork PRs.
- **`build` job:** no `id-token` permission and no GCP auth. It builds the
  same `DOCKERFILE` as prod and hands the image to the next job with
  `docker save` as an artifact. PR code (`COPY . .` and every `RUN`) executes
  only where no credential exists.
- **`deploy` job:** authenticates to the preview deployer, loads, pushes and
  runs `gcloud run deploy pr-<N>` with fixed flags (zero-role runtime account,
  `--iap`, `--max-instances=1`, `--min-instances=0`, small CPU/memory, preview
  env vars only, no `--set-secrets`). It then posts the sticky comment.
- **`teardown` job** on `closed`: deletes the service and the PR's image tags.
  A nightly scheduled sweep deletes any `pr-*` service whose PR is no longer
  open, so a failed teardown can't leave orphans.
- Add `gha-creds-*.json` to `.dockerignore`. `google-github-actions/auth`
  writes its credentials file into the workspace, and `COPY . .` would bake it
  into any image built after auth. This applies to `deploy.yml` too, which
  authenticates before building.
- A budget alert on `integrated-preview` caps runaway cost.

## Considered options

- **Revision tags on the prod service** (`--tag pr-N --no-traffic`). Cheapest
  to set up. Rejected: a tagged revision inherits the service's env, secrets,
  service account and database, so PR code would run against prod.
- **Neon branch of prod.** Real data and full Postgres parity. Rejected: it
  copies refugee minors' records into an environment that runs unreviewed
  code.
- **Neon branch of a synthetic seed branch, in a separate Neon project.**
  Postgres parity without real data. Deferred: it puts a DB credential back
  into the PR code's environment and adds a per-PR branch lifecycle. If parity
  is ever needed, a Postgres 17 *sidecar container* in the same Cloud Run
  service gives it with no external credential at all. That is the preferred
  upgrade path.
- **Signed-token links, no IAP.** Works without the OAuth client setup.
  Rejected: the signing key would live in the PR code's environment, and the
  site would be public internet with a login bypass on it.
- **`gcloud run services proxy` only (no public ingress).** Very secure, but
  there is no click-a-link URL. Kept as the fallback if IAP is unavailable.
- **A third-party preview host (Render, Railway).** Rejected: it moves builds
  to a new vendor while Workload Identity Federation, Artifact Registry and the
  Dockerfile already target GCP.

## Consequences

- Previews are disposable. State resets on idle scale-to-zero and on every
  push, so the comment links always lead back to a known starting point.
- Anything that needs a real third party (Stripe checkout, Google sign-in, real
  TTS, real LLM answers) can't be tested end-to-end in a preview and stays a
  local-dev check.
- `create_app()` gains a third configuration branch. Every future integration
  that reads an env var has to decide its preview behaviour; the boot guard
  catches a missed decision that would reach prod.
- One-time setup outside the repo: the `integrated-preview` project, the IAP
  custom OAuth client, the preview deployer and runtime service accounts, the
  narrowed prod WIF binding, and the budget alert.

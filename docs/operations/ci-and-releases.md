# CI and releases

The workflows in `.github/workflows/` and the labels that steer them.

## What runs when

| Workflow | Trigger | Does |
|---|---|---|
| `tests.yml` | every push / PR to `master` | `ruff check`, `ty check`, then the full test suite with coverage (floor 78%). Dependabot PRs run a smoke job instead (install without dev deps, `import main`) |
| `codeql.yml` | every push / PR to `master`, weekly, manually | CodeQL code scanning for Python, JS and the workflows, configured by `.github/codeql/codeql-config.yml` (see [Security scanning](#security-scanning)) |
| `migrations.yml` | changes to migrations, models or the lock | replays every migration on a real Postgres 17 and diffs against the models — catches SQLite-only migrations |
| `deploy.yml` | push to `master` | builds and deploys ([deployment.md](deployment.md)) unless skipped — **independent of tests** |
| `auto-tag.yml` | after `tests.yml` succeeds on `master` | tags `vX.Y.Z` and creates the GitHub Release |
| `release.yml` | a hand-pushed `v*.*.*` tag | creates a Release |
| `labels.yml` | its own change, or manually | creates the CI labels |
| `claude.yml`, `dependabot-claude-review.yml` | `@claude` comments; Dependabot PRs | Claude in GitHub |

So a red test run blocks the version tag, not the deploy. Run ruff, ty and the
relevant tests before pushing.

## Steering a merge

Pull requests carry **labels**; direct pushes carry **tokens in the commit
message**. Labels win for PRs (a stray token in one squashed commit can't
hijack them).

| Want | PR | Direct push |
|---|---|---|
| Version bump | `release:major` / `release:minor` / `release:patch`; none → **minor** | `#major` / `#minor` / `#patch`; none → **patch** |
| No release | `release:skip` | `#none` |
| No deploy | `deploy:skip` | `#donttriggerdeploy` |

Commit-message wording: the `.claude/skills/create-commit-message` skill.

## Dependabot

One grouped weekly PR per ecosystem (Python via uv, GitHub Actions, the
Docker base images), labelled `release:patch` + `deploy:skip`. Security
updates arrive as their own grouped PR per ecosystem, with the same labels,
as soon as an advisory lands. Dependabot PRs never deploy (skipped by
author, not only by label) and skip the full suite; the full suite runs on the
merge commit instead, so tagging is still gated on it.

`dependabot-claude-review.yml` posts a "does this bump break anything?"
verdict. Its shape is deliberate:

- It runs on `pull_request_target`, because a Dependabot `pull_request` run
  has no secrets and a read-only token. Secrets are therefore in scope, so it
  **never checks out or runs the PR's code** — Claude gets the trusted base
  branch and read-only tools only.
- Claude returns the verdict as structured output and a separate trusted step
  posts it: a multi-line comment body passed as a shell argument is refused by
  Claude Code's permission matcher while the run still exits green. When no
  verdict comes back, the step comments the failure and fails the job.
- It passes `github_token` explicitly, because the action's default OIDC
  token exchange is rejected for `pull_request_target` events; the comment is
  therefore authored by `github-actions[bot]`. `allowed_bots:
  "dependabot[bot]"` lets the bot-triggered run past the action's human-actor
  check.

## Security scanning

`codeql.yml` is CodeQL's *advanced* setup, so GitHub's default setup must stay
off (it rejects uploads from a workflow while default setup is on). The config
runs `security-and-quality` (a superset of the default and
`security-extended` suites), the `local` threat model (CLI arguments,
environment variables and files count as untrusted, which is what reaches
`commands.py` and the content-folder sync), and the GitHub Security Lab
community packs. It skips `scripts/`, `.claude/` and `tests/`: none of them
ships in the image or runs on the server, and ruff and ty still lint them. Five
queries whose every alert here was a false positive are excluded in
`query-filters`, each with the reason and what still covers the risk.
Findings land under the repository's *Security → Code scanning*. How to report
a vulnerability: `SECURITY.md`.

## Workflow hygiene

Every `uses:` is pinned to a full commit SHA with the version in a trailing
comment (`@<sha> # v7.0.1`), so a moved tag cannot change what runs;
Dependabot bumps the SHA and the comment together.

Untrusted text (commit messages, PR labels and titles) is read through
environment variables inside scripts, never interpolated as `${{ }}` into a
shell line.

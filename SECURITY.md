# Security policy

IntegratED holds data about children: young refugee learners and the school
students who tutor them. We take reports about it seriously and would much
rather hear about a problem privately than find it exploited.

## Supported versions

Only the code on `master`, which is what runs in production, is supported.
Fixes go into `master` and ship with the next deploy. Older tags are not
patched.

## Reporting a vulnerability

**Please do not open a public issue, pull request or discussion for a
security problem.**

Report it privately through GitHub instead:

1. Go to the repository's **Security** tab.
2. Choose **Report a vulnerability**. This opens a private advisory that only
   the maintainers can see.

Helpful things to include:

- what an attacker can do, and which role they need (none, learner,
  volunteer, teacher, school admin, administrator)
- the steps, request or URL that shows it
- the commit or date you tested against

You can expect:

- an acknowledgement within **5 days**
- an assessment, and a fix plan if it is valid, within **14 days**
- credit in the advisory once a fix has shipped, unless you would rather stay
  anonymous

## Scope

In scope: this repository's code and its GitHub Actions workflows, including
authentication, the permission checks between roles, the admin database
console, file uploads and the AI assistant's write path.

Out of scope:

- the development-only routes (`/dev/...`), which refuse every request unless
  the app runs with `APP_ENV=development` on a loopback address
- findings that need an already-compromised administrator account or server
- missing security headers or rate limits with no demonstrated impact
- reports produced only by an automated scanner, without a working proof
- denial of service through traffic volume, and social engineering

## Testing safely

Test against a local copy (see the README), never against the production
site. Do not access, change or delete other people's data, and stop and
report as soon as you can see data that is not yours.

## How this repository is protected

- CodeQL code scanning on every push and pull request
  (`.github/workflows/codeql.yml`, configured in `.github/codeql/`)
- Dependabot security and version updates (`.github/dependabot.yml`)
- secret scanning with push protection
- branch rules on `master`

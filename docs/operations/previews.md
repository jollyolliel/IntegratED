# PR previews

Each open PR gets its own URL: a Cloud Run service `pr-<number>` running that
branch on fake data. A `main` service runs `master` as the baseline to compare
against. Why it is shaped this way: [ADR 0013](../adr/0013-pr-previews-isolated-project-synthetic-data.md).
Code: `routes/preview/`, `helpers/preview/`, `.github/workflows/preview.yml`.

## Using one

The workflow keeps one comment on the PR with the links. To link the pages a PR
changes, put this in its description (personas are listed in
`helpers/preview/personas.py`):

````md
```preview
learner-midpath /learner/learn/subjects
teacher         /teacher/people
```
````

The links are read at deploy time, so a description edited afterwards applies
from the next push. Data resets on every push and after the service has been
idle. Forks and Dependabot get no preview. Stripe, Google sign-in, real TTS and
real LLM answers do not work in one; check those on a local dev server.

To time a backend change, load the same seed size (hub → *Reset the data*) on
`pr-N` and on `main` and compare each request's `Server-Timing` header. The
numbers are only comparable with each other.

## The rules that keep it safe

A preview runs unreviewed code, so every limit that matters is outside the
code a PR can edit:

- a separate Google Cloud project, whose runtime service account has no roles;
- IAP in front of every service; the preview deployer has `run.developer`,
  which cannot change who may call a service;
- the **prod** deployer trusts only `deploy.yml` on `master`
  (`attribute.workflow_ref`). Binding it to the repository, or to a branch,
  would hand production to a workflow a PR wrote, or to any other workflow
  that asks for a token on `master`. Renaming `deploy.yml` or its branch
  breaks the deploy until the binding is updated.

`APP_ENV=preview` also refuses to start beside any real credential, so each new
credential setting belongs in `REFUSED_IN_PREVIEW` (`settings.py`), and each new
outside service needs a decision about what it does in a preview. The image is
`DOCKERFILE`'s `preview` stage, which alone gets `seed/files/`, through a named
build context. A PR that changes the schema updates `helpers/preview/seed.py`
too if a persona or the sample data needs the new columns.

Running it locally is the same image:

```sh
docker build -f DOCKERFILE --target preview --build-context previewdata=seed/files -t preview .
docker run --rm -p 8080:8080 -e APP_ENV=preview preview
```

## One-time setup

Until the `PREVIEW_PROJECT_ID` repository variable exists, every job in
`preview.yml` is skipped. `scripts/setup_previews.sh` does the setup in five
steps, in the order its header lists; its last step sets that variable and
refuses to while the prod deployer is still bound to the whole repository.
The OAuth consent screen and client are made by hand in the console: the
script prints how. Its `oauth` step's settings file, and a project-wide
`iap.httpsResourceAccessor` grant covering new services, have not been run
against a real project yet; check both on the first preview.

"""PR previews (ADR 0013): the hosted, throwaway copy of the app each pull request gets.

Layout:
  personas.py  the fake accounts a preview signs reviewers in as
  links.py     the `preview` block in a PR description, and the PR comment
  seed.py      the preview's database and bucket (`flask seed-preview`)

The app side (`/_preview/*`, the banner, timing headers) is routes/preview/. `preview.yml` runs
`links.py` on the Actions runner's own Python, so it and `personas.py` import only the standard
library, and nothing is imported here.
"""

# CLAUDE.md

# IntegratED — Y2Y learning platform

A youth-to-youth learning platform run from ACS Athens: school students
volunteer as tutors for young refugees from The Home Project, most of whom
can't yet read in any language. Teachers run the programme — rosters,
matching, attendance, worksheets, an AI assistant; admins run schools and
content. One Flask monolith on Google Cloud Run with Neon Postgres; SQLite
in dev.

Whole picture: `docs/system-design.md`. Vocabulary: `docs/CONTEXT.md`.

## Docs — open the folder's README before working in its area

| The task touches… | Start at |
|---|---|
| What a user sees — templates, CSS, page JS, copy, a new page or component | `docs/ui-design/README.md` |
| Routes, permissions, models and migrations, mutations, analytics, startup | `docs/backend/README.md` |
| Placement test, learning path, quiz, minigames, XP and avatar, `questions.json` | `docs/learning/README.md` |
| Matching, worksheets, AI assistant, attendance, donations | `docs/features/README.md` |
| Docker, deploys, CI, env vars and secrets, prod database, backups | `docs/operations/README.md` |
| Tests, Python conventions, translations, hooks | `docs/development/README.md` |
| Why something was decided | `docs/adr/` |

Each README is a short router to the one file you need; a small change
usually needs one file, not the folder.

## Hard rules

- Write complete code. No placeholder stubs (`# TODO`, `# supposed to do X`).
  Must leave one — flag it explicitly when done.
- Stay on the asked goal. Spot something else needing a fix — mention it and
  ask before acting.
- **Commit or push only when the user explicitly tells you to** — never on
  your own initiative, and a skill's "commit" step is not that instruction.
  Finish with the work uncommitted and a list of what to try.
- Write tests before the code, so they check intended behaviour rather than
  what got built.
- Prefer the simpler route when it gets the same result.
- Python through `uv`: `uv run -m pytest`, `uv run main.py`, `uv sync`,
  `uv add <pkg>`. Never bare `uv run pytest` — it drops the repo from
  `sys.path` and every import fails.
- Touched `.py` files → `uv run ruff check .` and `uv run ty check`, as CI
  does. Fix what the diff introduced; pre-existing findings elsewhere aren't
  yours unless asked.
- New web feature → PostHog analytics and translation keys. New UI text →
  `{{ t('section.key') }}` plus
  `uv run scripts/add_translation_key.py section.key "English"`; never
  hand-edit `translations/*.json` (a hook blocks it). Text the UI no longer
  uses → `uv run scripts/add_translation_key.py --remove section.key`. Add or
  remove keys only — never translate them or run `translate_missing.py`; other
  languages keep the English placeholder until a person translates them.
- A change that makes a sentence in `docs/` or `.claude/rules/` false → fix
  that sentence in the same response. Adding new doc prose is a judgment call:
  `docs/README.md` says what belongs.
- Hook output on stderr (Stop checks, lint) is blocking feedback. For each
  finding, check whether it points at a file or line you edited this session:
  if so, fix it in the same turn. If it points only at files you did not edit,
  it is someone else's in-progress work — ignore it, and mention it only if it
  blocks you. When unsure whether a finding is yours
  (you edited that file, but not that line), treat it as yours and fix it.
- Batch independent tool calls into one message; serialize only when a call
  needs a prior result.

## Done means it works in the real app, ~99% of the time

Green pytest is not proof. Before finishing:

1. **Review the diff like a hostile reviewer** — empty/None states, wrong role
   or no login, first-time user, RTL, phone width, double-submit, the path the
   happy case skips. Fix what you find.
2. **Run the real thing, targeted at what changed** — only what the diff
   touches. Reuse the dev server if `curl -s 127.0.0.1:5000/health` answers,
   else `uv run main.py` in the background.
   - Route/API/logic → the tests that cover it (the full suite only for
     broad changes) + `curl` the endpoint and check the response/redirect.
   - Anything a user sees or clicks → that page in a real browser, as each
     role that sees it: `/dev/login-as?type=<user_type>&next=/path` (`next` is the full path with
     the role prefix, e.g. `/learner/map`, never `/map`). Set first-run state with
     `&survey=0|1` and `&map_test=0|1|deferred` (learner). Click
     through the flow; check the console for errors.
   - Copy or style tweak → load the one page it's on.
3. **Report what you exercised and how** — "tests pass" alone is not a report.

## Issue tracker

GitHub Issues on `jollyolliel/IntegratED` through the `gh` CLI. Triage labels:
`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.

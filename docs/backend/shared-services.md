# Shared services

The helpers a new feature should reach for instead of rebuilding. Each one's
own docstring has the details; this file says which to use and the rules that
span callers.

## Teacher mutations — `helpers/teacher_ops/`

Every change a teacher makes to their roster — matching, capacity,
attendance, worksheet assignment — is a function here, shared by the teacher
routes, Auto-Match and the AI assistant's apply step. That sharing is the
point: an invariant enforced here holds for all three.

- Takes an explicit `teacher`, never reads the request, never aborts. It
  signals with exceptions the route maps to statuses: `LookupError` → 404,
  `PermissionError` → 403, `ValueError` → 400 with `str(e)` as the message.
- Most operations have a `validate_*` twin that checks without writing (the
  assistant stages with it).
- Ownership is checked inside (`_owned`), and each call **commits** — don't
  wrap several in one transaction expecting a rollback.
- A new teacher action that changes data goes here first, then gets a route
  (and, if the assistant should propose it, a write op —
  [../features/ai-assistant.md](../features/ai-assistant.md)). Rules that only
  apply on one screen stay in that route.

People are deleted only through `helpers/roster_ops.py`
([data-model.md](data-model.md)).

## JSON or HTML — `helpers/utils.py`

- `wants_json()` is true when the request carries
  `X-Requested-With: XMLHttpRequest`. Same-page form routes branch on it:
  JSON `{success, message}` for the AJAX form handler, flash + redirect
  otherwise ([../ui-design/page-behaviour.md](../ui-design/page-behaviour.md)).
- `wants_fragment()` is true for `X-Fragment: 1` — render only the results
  component of a paged page. `clamp_page()` turns any `?page=` into a valid
  page.
- The `/api` routes always speak JSON, and the global error handlers answer
  JSON there too.

## Rendering — `helpers/render.py`

`render_template("@pages/…jx", **ctx)` for every page (Flask's own is banned
by ruff). Context processors (`t`, `ui_dir`, `app_version`, `now`…) reach
every component; a route's own keyword wins over a global of the same name.

## Who is signed in — `helpers/current_user.py`

Import `current_user` from here, never from `flask_login` (ruff enforces it).
Role-typed aliases (`current_teacher`, `current_learner`…) are for modules
where every use sits behind that role's gate.

## Files — `helpers/storage/`

Worksheets, audio, public images, content and backups go through the `Bucket`
from `get_bucket()`: a local folder in dev, the GCS bucket in production, never
`None`. It works on bucket keys (`exists`, `read_bytes`, `write`, `send`,
`delete`); each caller owns its prefix (`WORKSHEET_PREFIX`, `audio_key`,
`image_key`). Never build filesystem paths yourself, and never branch on which
backend is active — ask the object (`prefers_inline_storage`, `is_safe_path`).

App art (illustrations, SVGs, photos, sprites) is not storage: it lives in
`static/img/` and `static/svg/`, public, served by `url_for('static', …)`.
Worksheet uploads and PDFs are behind login; article hero images are public
uploads, served by `base.article_image`.

## Analytics — `helpers/analytics/`

The CLAUDE.md rule "new feature → PostHog analytics" means a
`capture_event(...)` call at each meaningful user action:

```python
from helpers.analytics import capture_event
capture_event(str(user.id), "worksheet_assigned", {"worksheet_id": ws.id, "learner_id": learner.id})
```

- Run `uv run scripts/list_analytics_events.py` first and reuse the naming
  pattern of nearby events (`<thing>_<past-tense verb>`); near-duplicate
  names split one metric in two.
- While someone is signed in the event is attributed to their hashed
  PostHog id whatever the first argument says; user type, school, teacher,
  endpoint and request id are added automatically.
- Keys containing `password`, `token`, `secret`, `authorization`, `api_key`,
  `private_key` or `access_key`, or named exactly `key`, are redacted at every
  level (`announcement_key` arrives). Dicts and lists are kept two levels
  deep, then arrive as a placeholder.
- Events are only sent in production with `POSTHOG_API_KEY` set
  (`Settings.analytics_enabled`); locally and in tests nothing leaves the machine. In-browser tracking is
  `window.analytics.trackEvent(...)` (set up by `components/shell/theme.jx`).

## Text in Python

Python never translates. User-facing wording lives in templates through
`t()`; flash messages and JSON `message`s are short English confirmations. If
Python must produce a translated string, use
`make_translator(get_current_lang())(key)` from `helpers/i18n.py`.

## Speech — `helpers/eleven_labs.py`

ElevenLabs text-to-speech generates question audio the first time `/audio/<file>`
asks for it, only for text on the spoken list (`helpers/audio_cache.py`; the
rules are in [../learning/content.md](../learning/content.md)). The key
is read when called, so a missing key disables audio without breaking boot;
the browser's `speechSynthesis` is the runtime fallback.

## Documents — `helpers/documents.py`, `helpers/md_to_pdf.py`

Markdown worksheets render to HTML for viewing and to PDF through fpdf2 for
printing; the pair stamp on page 1 is drawn with fpdf2 and merged by pypdf
(no templates, no browser).

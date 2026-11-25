# Translations

Every word a user sees goes through the translation system; most learners
don't read English (or yet read at all, so the words are also for tutors and
screen readers). Thirteen interface languages — English plus Greek, Arabic,
Turkish, Spanish, French, Ukrainian, Farsi, Pashto, Somali, Rohingya,
Tigrinya and Swahili. Learners and visitors can pick any of them; staff menus
offer English and Greek. Arabic, Farsi and Pashto render right-to-left.

## Adding text

1. Write `{{ t('section.sub.key') }}` in the template. Keys follow the UI
   area (`learner.garden_grow.title`, `teacher.people.factor_age`); look at
   neighbouring keys in `translations/en.json` before naming one. Values can
   take placeholders: `{{ t('welcome', name=user.name) }}` for
   `"Welcome, {name}!"`.
2. `uv run scripts/add_translation_key.py section.sub.key "English text"`
   (several pairs at once is fine; `--update` changes existing English and
   resets every other language to it).

The script writes `en.json`, puts the English as a placeholder in every other
language, and lists the key in `translations/needs_translation.json` for
translators. **`translations/*.json` are script-only** — a hook blocks hand
edits and shell writes to them.

## Removing text

When a change drops UI text, remove its key too:

```bash
uv run scripts/add_translation_key.py --remove section.sub.key [more.keys ...]
```

It deletes the key from every language file and `needs_translation.json`,
pruning sections left empty. First it searches the code (templates, Python,
JS, JSON) for the key in quotes, or for a quoted prefix it could be built from
(`t('teacher.people.factor_' ~ factor)`), and refuses, listing the files, if it
finds one. `--force` overrides that when the match isn't a real use. A key put
together any other way (`'%s.title' % section`) isn't seen, so check before
removing one with a generic name. `--unused` lists every key in `en.json` that
nothing references.

Adding or removing the key is the whole job. Agents never translate: leave the English
placeholders in place and don't run `translate_missing.py` or
`translation_audit.py` — translation is done separately by a person.

## In page scripts

JavaScript can't call `t()`. Render what the script needs into one object at
the top of its `<script>`, with `tojson` (which escapes quotes and newlines):

```jinja
<script>
  const T = {
    loadError: {{ t('learner.map.load_error') | tojson }},
    progressQuestion: {{ t('learner.quiz.progress_question') | tojson }},  // "Question {current} of {total}"
  };
</script>
```

Called without arguments, `t()` leaves `{placeholders}` in place, so a string
whose values are only known in the browser is rendered raw and filled in JS
(the quiz's three-line `quizFormat(template, values)`), not pre-rendered once
per value in Jinja. Never hardcode English in a script — toast text,
fallback labels and `textContent` defaults escape translation silently.

## Traps

- Never name a loop or `{% set %}` variable `t`: it shadows the translator
  and the next `t('…')` in that block is a 500 — one that only fires when the
  loop has rows.
- Python doesn't translate; see
  [../backend/shared-services.md](../backend/shared-services.md).
- Authored content — articles, team bios, site text from the CMS,
  announcement popups, learning content — is not translated through `t()`.

## The other tools

- `uv run scripts/sync_keys.py` — repairs every language file against
  `en.json` (it writes; `--dry-run` previews, `--audit` lists keys used in
  templates but missing from `en.json`).
- `uv run scripts/translate_missing.py` — machine-translates placeholders.
  Run by a person, never by an agent.
- `uv run scripts/translation_audit.py --report` — offline report of
  hardcoded text in every template (element text, text attributes, jx text
  props), with a suggested key for each; no API key needed.
- `uv run scripts/translation_audit.py` — Gemini-assisted fixes for the same
  findings and for untranslated values (`--fix <file>`, `--fix-all`,
  `--audit-langs`, `--fix-lang <code>`); needs `GEMINI_API_KEY`. Its translating modes
  (`--translate-only`, `--fix-lang`) are for a person, never an agent.
- The non-English files are marked generated in `.gitattributes`, so diffs
  collapse them; on a merge conflict in one, take either side and rerun
  `sync_keys.py`.

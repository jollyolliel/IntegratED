# UI design — start here

Read this before touching anything a user sees: a `.jx` template, a stylesheet,
page JavaScript, copy on a page.

Every page is assembled from **jx components** (`<Button>`, `<Card>`, `<Field>`…)
whose looks live in one registry. Most UI work is choosing the right component
and prop, not writing CSS. The docs below are split so a small change reads one
short file and a redesign reads the rest.

## Which file for which task

| You are… | Read |
|---|---|
| Adding or changing something on an existing page — a button, a field, a card, a table, a message, a new page from existing parts | [building-ui.md](building-ui.md) — enough on its own for most tasks |
| Wiring page behaviour — an AJAX form, a delete confirm, a toast, a paged table, a dropdown, the navbar | [page-behaviour.md](page-behaviour.md) |
| Designing something new — a new component, a new look, a redesign, making a screen feel polished | [visual-language.md](visual-language.md), then [styling-system.md](styling-system.md) |
| Writing CSS, adding a component or a page stylesheet, or fighting a lint finding | [styling-system.md](styling-system.md) |
| Building anything a **learner** sees (dashboard, learning path, games, placement test) | [designing-for-learners.md](designing-for-learners.md) as well |
| Working on public pages — landing, about, schools, donations | [public-pages.md](public-pages.md) |
| Looking for which `static/css/pages/*.css` partial a page uses and its traps | [page-stylesheets.md](page-stylesheets.md) |
| Iterating on a page's UI in the browser (live variants) | [../../tools/live-extension/README.md](../../tools/live-extension/README.md), then [../../.claude/skills/live/SKILL.md](../../.claude/skills/live/SKILL.md) |
| Running a design tool (Impeccable) or wanting the whole visual system as one spec — tokens, components, do's and don'ts | [DESIGN.md](DESIGN.md) — a mirror of the tokens and clay rules in DESIGN.md format; if it disagrees with the code, the code wins and the file is regenerated with `/impeccable document` |

Translations for any new text: [../development/translations.md](../development/translations.md).

## Ground truth to look at instead of reading

- **`/dev/components`** — the live gallery: every shared component in every
  allowed prop value (`?lang=ar` for RTL). Local dev and PR previews only.
- **`helpers/clay_primitives.py`** — the registry: each component's file, its
  allowed prop values and the classes it alone may write.
- **`tailwind.config.js`** — every colour, radius and clay-geometry token.
- **`templates/components/**/*.jx`** — each component's header comment states
  what it is for and how to call it.

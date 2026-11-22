# Building UI from the components

The short path for everyday UI work. If the change only uses existing
components, this file is all you need.

## How a page is put together

- A page is a `.jx` file under `templates/pages/<role>/`, rendered by a route
  with `helpers.render.render_template("@pages/<role>/<name>.jx", **ctx)` —
  never Flask's own `render_template` (ruff bans it).
- The file opens with explicit imports and its arguments:
  ```jinja
  {#import "@components/shell/page.jx" as Page #}
  {#import "@components/shell/main.jx" as Main #}
  {#import "@components/base/button.jx" as Button #}
  {#def learners, pending_announcement=None #}
  ```
  Every name is `@` + its path under `templates/`. A misspelt variable renders
  as empty, not an error — check the page, not just the status code.
- `<Page title=… styles="…">` renders the whole document (theme, header,
  footer). Content goes in `<Main>` (`width="3xl"` caps it,
  `layout="centered"` for a lone form or card). Games use `<GamePage>`, the
  legal pages `<LegalPage>`. Dashboards pass
  `announcement={{ pending_announcement }}` so the "what's new" popup can
  show. Only full-bleed pages (landing, games, map) write their own `<main>`.
- `styles` names page stylesheets from `static/css/pages/` — see
  [page-stylesheets.md](page-stylesheets.md) for which one fits.
- The dev server needs a restart to pick up a **new** `.jx` file.

## Which component for what

| Need | Use |
|---|---|
| Button or button-styled link | `<Button variant=… href=…>` |
| Page title block | `<PageHeader badge=… title=… subtitle=…>` |
| Section heading inside a page | `<SectionTitle icon=…>` or `<SectionBadge>` above an `h2` |
| Panel / container | `<Card tone=…>` |
| Whole card is a link | `<QuickAction href icon title description>` or `<Card href=…>` |
| One number | `<StatTile label value tone icon>` |
| Labelled form control | `<Field label for_id required>` around `<Input>`, `<Textarea>`, `<Choice>` or a `<select>` |
| Data table | `<Table>` + `<Pagination>`, empty case `<EmptyState>` |
| Pill / label | `<Badge tone>`, `<CountPill>`, `<StatusPill status>` |
| Icon | `<Icon name="…">` (heroicons outline names), `<IconBox>` for a tinted tile |
| Progress | `<ProgressBar value tone size>` |
| Read-aloud button | `<AudioButton label=…>` (`size="lg"` for a 96px hero) |
| "Back to …" link | `<BackLink href label>` |

Allowed prop values are in `helpers/clay_primitives.py`; an unknown value
raises in tests and logs + falls back in prod. `/dev/components` shows each
one rendered.

## Buttons — the choices that matter

- `variant` carries meaning, fixed app-wide: `accent` (green) = the screen's
  primary action, `sky` = secondary, `gray` = cancel/back, `soft` = pale-blue back-to-list link on learner pages, `danger` =
  destructive, `amber` = pending/review, `rose` = game-over retry.
- **`accent` is the default**, so a secondary button must say
  `variant="sky"` or `"gray"`. A screen has **one** green primary; two green
  buttons means none of them is the primary.
- `flat` = small chip for table rows and dense action cells; pair flat with
  flat in the same cell. `size="lg"` = hero CTA.
- With `href` it renders an `<a>`; without, `<button type="button">` — a form's
  submit button must say `type="submit"`.
- `icon="…"` / `icon_end="…"` add an icon; arrows and chevrons mirror in RTL
  on their own.

## Rules the lint can't check for you

1. **Every user-visible string is a translation key** — `{{ t('section.key') }}`,
   added with `uv run scripts/add_translation_key.py section.key "English"`.
   Add the key only; don't translate it.
   Strings a script needs go into a small `const T = {…}` built with
   `{{ t('…') | tojson }}` at the top of the `<script>`. Never name a loop or
   `{% set %}` variable `t` — it shadows the translator.
   Full workflow: [../development/translations.md](../development/translations.md).
2. **Use the component, don't rebuild its look.** On a page, `class` on a
   component takes layout and spacing (margin, padding, width, flex/grid) only.
   Colour, border, radius and shadow come from props.
3. **Colours by role, never raw hex**: `text-primary`, `bg-surface-card`,
   `text-ink-muted`, `border-line`. Raw hex/rgb anywhere fails lint.
4. **Logical directions** for RTL (Arabic, Farsi, Pashto): `ms-`/`me-`,
   `ps-`/`pe-`, `start-`/`end-`, `text-start`. Never `ml-`/`mr-`/`left-`.
5. **Icons are `<Icon>`** — no emoji, no text glyphs (`→ ✓ ×`) in buttons,
   links or headings; they don't flip in RTL and render unevenly.
6. **Destructive actions confirm** through the app's modal (`data-confirm`
   on the form, or `window.confirmDelete`) — see
   [page-behaviour.md](page-behaviour.md). Never the browser's `confirm()`.
7. **Transient messages are toasts** — `flash(msg, "success")` from Python,
   `window.showToast(msg, "success")` from JS. No inline alert divs.
8. Never put `{{ x | tojson }}` inside an `on…=""` attribute — its quotes end
   the attribute and the handler silently dies. Pass data via a `<script>`
   block or `data-*` attributes.

If a page genuinely needs to break rule 2, mark that one tag with
`{# design: override — <reason> #}` on its line or the line before.

## Checking it

The end-of-turn hook lints changed templates and CSS. Then look at the page
in the browser: sign in with `/dev/login-as?type=<role>&next=/path` (the full
path with the role prefix, e.g. `/learner/map`), check
phone width and Arabic (language picker in the header), and the console.

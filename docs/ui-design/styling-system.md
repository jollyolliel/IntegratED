# Styling system — where styles live and how they're policed

Read before writing CSS, adding or changing a component, or when a lint
finding blocks you. The design principles themselves are in
[visual-language.md](visual-language.md).

## The layers, top to bottom

| Layer | Where | Holds |
|---|---|---|
| Tokens | `tailwind.config.js` | every colour (roles + palette), radius and clay-geometry value; published as `--color-*` / `--clay-*` / `--radius-*` CSS variables and role utilities (`bg-primary`, `rounded-card`) |
| Component CSS | `static/css/components/*.css`, chained by `static/css/components.css` | the clay classes (`.btn-clay`, `.clay-card*`, `.clay-input`…) |
| Components | `templates/components/{base,*,shell}/*.jx` + the registry `helpers/clay_primitives.py` | which class each prop value renders, and which classes only that component may write |
| Page stylesheets | `static/css/pages/*.css` | CSS shared by a few pages of one feature area — [page-stylesheets.md](page-stylesheets.md) |
| One page | a `<style>` in that page's `head` | CSS no other page will need |

`static/css/input.css` imports Tailwind's base, then the component CSS, then
the utilities — outside any `@layer` — so a utility beats a component class of
equal specificity without `!important`, and page stylesheets (linked after)
beat both. Everything builds into one `static/css/tailwind.css`
(`uv run scripts/tailwind.py`; the dev server and a local pytest run rebuild it;
Docker builds it in its first stage).

**Tailwind only keeps classes it can see** in `templates/`, `static/**/*.js`
and `helpers/clay_primitives.py`. A class assembled from string pieces is
purged in the build — write class names whole. A new file that holds class
strings must join `content` in `tailwind.config.js` *and* be copied into the
Tailwind stage of `DOCKERFILE`, or it works in dev and vanishes in prod.

## Where does this CSS go?

1. An existing component or prop value already gives the look → use it, no CSS.
2. A new variant of an existing component (a colour, a size) → a class in
   that component's CSS file plus a value in its `Prop` in
   `clay_primitives.py`. Brand looks stay central even for one difference.
3. Several pages of one feature need it → the feature's page stylesheet.
4. One page needs it → that page's `<style>`.

Never redeclare a component class (`.clay-card`, `.btn-accent`) in a page
stylesheet or `<style>`: give the variant its own name
(`.donation-step-card`). Inside one page stylesheet, two rules with the same
class name collide on every page that links it — name near-twins apart
(`.rocket-droppable-blank` vs `.droppable-blank`).

## Adding or changing a component

1. The `.jx` file in the right layer folder (ADR 0012): `base/` = building
   blocks, top level = composed from bases, `shell/` = page shells and
   chrome. Open it with a `{#- … -#}` comment saying what it is and how it is
   called — that comment is its documentation.
2. Its `Spec` in `helpers/clay_primitives.py`: allowed prop values, the class
   each value renders (`looks`), classes only it writes, and the restyle lint
   rule that guards it. Components read their looks through `prop()` /
   `look()`, never a dict of their own.
3. New classes in `static/css/components/*.css`, each with a
   `/* .class-name: what it is for */` comment directly above it
   (`scripts/check_css_class_docs.py` fails otherwise). A new CSS file joins
   the `@import` chain in `components.css` and `FILE_ORDER` in that script.
4. Show it in the gallery, `templates/pages/dev/components.jx` — a test fails
   for any component the gallery doesn't render.

A composed component may restyle the base it builds on; that is how it
reaches its look. Pages may not.

## The lint

Two linters run on changed templates and CSS at the end of every turn
(`scripts/check_changes.py`) and over the whole repo in the test suite.

**ast-grep** (`lint/rules/`, configured by `sgconfig.yml`):

| Rule | Fails |
|---|---|
| `no-raw-color-css`, `no-inline-color`, `no-arbitrary-color` | a raw hex/rgb/hsl in CSS, in `style=""`, or in an arbitrary `[…]` utility |
| `no-restyle-button` / `-card` / `-input` | padding, text, radius, border, shadow or background utilities on a clay class |
| `no-scale-press` | `scale()` in an `:active` transform |
| `no-transition-all`, `no-transition-all-class` | `transition: all` / `transition-all` |
| `no-raw-palette-utility` (warning) | a palette shade where a role exists (`text-sky-600` → `text-primary`) |
| `logical-properties` (warning) | `ml-`/`mr-`/`left-`/`text-left`… in a class attribute |

**jx lint** (`scripts/lint_jx.py`): an unknown prop value; restyle utilities
on `<Button>`/`<Card>`/`<Input>`/`<Textarea>` in a page; a class a component
owns written anywhere else (`no-raw-clay-class`); a `<select>` without its
`<button><selectedcontent>` child; `class="a {{ b }}"` on a component tag
(literal text — write `class={{ "a " ~ b }}`).

Escape hatches, each needing a reason in the comment:
- `{# design: override — <reason> #}` on a tag's line or the line before frees
  that tag from the restyle rules (not from `no-raw-clay-class`).
- `/* ast-grep-ignore: no-raw-color-css -- illustration: <what> */` for one
  line of game illustration art.

What the lint can't see: markup built in JavaScript (games, attendance
history write clay classes from scripts), `!`-important utilities, and
physical properties in hand-written CSS. Those follow the same rules by hand.

## Traps

- **RTL in CSS**: use `margin-inline-start`, `inset-inline-end`,
  `text-align: start`. The lint only checks class attributes. Known
  exception: `.clay-table` header cells align with `text-right` because the
  table's own header rule outranks `text-end`.
- **The `hidden` attribute** loses to any class that sets `display` in a page
  stylesheet; such a class needs its own `[hidden] { display: none }` rule.
- **Scrollbars**: `clay-scroll` on a scroll container. Never put
  `scrollbar-width`/`scrollbar-color` on an element that also has
  `::-webkit-scrollbar` rules (Chromium then ignores the custom ones); the
  standard properties live in an `@supports not selector(::-webkit-scrollbar)`
  block. Thumb states set `background-color`, never `background` (the
  shorthand resets the clip and doubles the pill's width). A selector that
  only some browsers support goes in its own rule — one unknown selector drops
  the whole comma list.
- **Overriding a clickable locally**: redefine `:hover` **and** `:active`.
- **Outside the system on purpose**: `templates/starting_up.html` (must render
  with the database asleep — no header, no `current_user`, no shared CSS). The
  lint ignores it.

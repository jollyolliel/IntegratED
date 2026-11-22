# Visual language — clay

The principles behind every component. Read this when designing something
new: a component, a screen layout, a redesign, polish. Changing an existing
page with existing components needs only [building-ui.md](building-ui.md).

## Why clay

The core users are young refugee learners, most of whom can't read in any
language, on whatever phone they have. The UI has to say "this is a friendly
learning app, and *this* is the thing you can press" without words. Clay —
chunky rounded shapes, thick borders, hard offset shadows, a press that
visibly pushes the shape down — makes tappability physical. Everything below
exists to keep that signal honest: if everything looks pressable, nothing
does.

## Two visual languages: clickable vs static

The whole system rests on one distinction.

| | Clickable (button, clickable card, nav button) | Static (card, stat tile, panel, strip) |
|---|---|---|
| Shadow colour | **same** as the border | **one step paler** than the border |
| Hover / press | lifts, then presses into its shadow | none |
| Cursor | pointer | default |

The pale shadow is the *only* at-rest cue that a card won't respond, so it is
load-bearing: a static card with a border-matched shadow is the single most
damaging visual bug here — it looks tappable and does nothing. The paired
tokens are `card-<tone>-border` / `card-<tone>-shadow` (a 200 border over a
100 shadow). A container holding clickable children (a word bank, a dropdown
menu, a tray of answer bottles) is itself static; only the children move.

`<Card>` encodes this: static by default, clickable only with `href` or
`clickable` — and a clickable card has no purple or pink tone.

## Shadow maths is exact

Hover and press shadows are derived from the geometry tokens, never picked by
eye: hover = offset + lift, press = offset − press. With the defaults
(`--clay-offset` 3px, `--clay-lift` 1.5px, `--clay-press` 2px) a button
rests at 3px, hovers at 4.5px while moving up-left 1.5px, and presses to 1px
while moving down-right 2px — so the shape stays glued to its shadow. Half a
pixel off reads as a rendering glitch. `.btn-clay` computes this with
`calc()` on the tokens; any hand-written clickable must do the same.

A press **translates into the shadow**. Never `scale()` — scaling shrinks the
shadow with the box, so it reads as receding, not pushed (lint enforces
this). A shadowless control (gray ghost button, flat chip) has nothing to
press into, so it darkens its background and border instead.

## Elevation and depth

- One `box-shadow` per element. Never stack a blur behind a hard offset, and
  never add a Tailwind `shadow-*` to a clay element.
- Static cards sit at `--clay-static-offset` (4px). Overlays that float above
  the page (announcement popup, Auto-Match modals) use
  `--clay-modal-offset` (6px) — the bigger offset is their elevation; the
  colour still goes pale. The confirm modal deliberately stays a plain rose
  card at 4px.
- Toasts and game hint pills use a soft blur shadow on purpose: they are
  transient, not objects you touch.
- Icon boxes and inputs carry no offset shadow. Inputs show focus with a
  border and ring.

## Shape

Radius tokens: inputs 12px, buttons 14px, cards 20px, pills fully round
(`rounded-input|btn|card`). Borders are 2–2.5px, never 1px — a hairline breaks
the chunky read. Keep the scale: a card inside a card steps its radius down,
not up.

## Colour has fixed meanings

| Colour | Means | |
|---|---|---|
| Green (`accent`) | the primary action | one per screen |
| Sky (`primary`) | identity, secondary actions, links, focus | the app's own colour; the assistant uses it too |
| Gray | tertiary — cancel, back, close | |
| Red (`danger`) | destructive | always confirmed |
| Amber | pending, needs review, warning | |
| Rose | alert, error, "you lost" | |
| Gold | rewards — XP, coins, equipped items | |

Stat tiles and cards take the colour of what their data *means* (unmatched
learners = rose, hours = amber), never a colour picked for variety. Indigo
survives only as the near-black heading ink (`ink-heading`), never as a UI
colour. Every colour is a token from `tailwind.config.js`;
re-pointing a role there re-themes the whole app.

## Motion

- Clay elements transition exactly the properties that change —
  `transform` and `box-shadow` (plus colour/border when those change) —
  over ~150ms ease-out. Never `transition: all` (lint enforces).
- Anything that animates for more than a press honours
  `prefers-reduced-motion` with its own block. Many existing components lack
  one; new work includes it.
- Motion is feedback, not decoration: a press, a correct answer flying to
  where it counts, a progress tick turning green. Games use GSAP for this
  (loaded by `<GamePage>`).

## Type

- Headings `h1`–`h4` are Baloo 2 automatically (`base.css`); `display-font`
  gives Baloo 2 to non-headings such as big numbers and the logo.
- Body is the system font stack.
- Fluid `clamp()` type belongs to the public pages, where it is set large.

## Icons

Heroicons outline through `<Icon>` — stroke 2, coloured by `currentColor`,
`aria-hidden` unless it is the only content (then the control needs an
`aria-label`). Horizontal arrows and chevrons mirror in RTL automatically. No
emoji and no text glyphs: platforms render them differently, they don't
mirror, and screen readers announce them unpredictably.

## What makes a screen feel finished here

- **Every interactive thing obeys the press physics**, every static thing
  stays still. Mixed signals are what make a screen feel cheap.
- **One clear primary** per screen, visually dominant; everything else steps
  down (sky, then gray).
- **Generous, consistent spacing** — the same gaps between sibling cards,
  section badges above major headings, `<PageHeader>` at the top.
- **Empty, loading and error states are designed**, not left blank:
  `<EmptyState>` with a friendly line, a disabled button with the reason
  nearby, a skeleton or spinner only where a fetch is genuinely slow.
- **Illustration over decoration**: the real art in `static/svg/` and
  `static/img/` (public, not login-gated) carries personality better than
  gradients and extra shadows.
- **Same job, same composition.** Before inventing a "next step" block, a stat
  row or an end screen, find the screen that already solves it and reuse its
  composition.

## Hand-rolled clickable checklist

When nothing in the component set fits and you write CSS for a new
clickable: a base offset shadow (else it doesn't read as tappable), `:hover`
**and** `:active` (overriding only one silently kills the other), exact
shadow maths, one shadow, `type="button"` unless it submits, a visible
`:focus-visible`, a reduced-motion block, and RTL-safe properties. Then
consider whether it should become a component — see
[styling-system.md](styling-system.md).

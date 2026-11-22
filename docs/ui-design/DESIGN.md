---
name: IntegratED
description: A youth-to-youth learning programme where every pressable thing is chunky clay, and a child who can't read the words still knows what to tap.
colors:
  primary: "#0284c7"
  primary-dark: "#075985"
  primary-light: "#bae6fd"
  primary-soft: "#e0f2fe"
  primary-tint: "#f0f9ff"
  accent: "#16a34a"
  accent-dark: "#15803d"
  danger: "#dc2626"
  danger-dark: "#991b1b"
  pending: "#fbbf24"
  pending-dark: "#d97706"
  alert: "#e11d48"
  alert-dark: "#be123c"
  gold: "#e5b81a"
  live: "#3b82f6"
  surface: "#ffffff"
  surface-page: "#f5f7ff"
  surface-card: "#f8f9ff"
  ink-heading: "#1e1b4b"
  ink-title: "#082f49"
  ink-navy: "#0c2d48"
  ink-body: "#374151"
  ink-muted: "#6b7280"
  ink-faint: "#9ca3af"
  line: "#e5e7eb"
  card-sky-border: "#bae6fd"
  card-sky-shadow: "#e0f2fe"
  card-green-border: "#a7f3d0"
  card-green-shadow: "#d1fae5"
  card-amber-border: "#fde68a"
  card-amber-shadow: "#fef3c7"
  card-rose-border: "#fecdd3"
  card-rose-shadow: "#ffe4e6"
  card-purple-border: "#e9d5ff"
  card-purple-shadow: "#f3e8ff"
  card-pink-border: "#fbcfe8"
  card-pink-shadow: "#fce7f3"
typography:
  display:
    fontFamily: "'Baloo 2', system-ui, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 800
    lineHeight: 1.1
  headline:
    fontFamily: "'Baloo 2', system-ui, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 800
    lineHeight: 1.2
  title:
    fontFamily: "'Baloo 2', system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  button:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 700
    lineHeight: 1.25
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "0.7rem"
    fontWeight: 700
    letterSpacing: "0.06em"
rounded:
  flat-chip: "8px"
  input: "12px"
  btn: "14px"
  card: "20px"
  pill: "999px"
spacing:
  gutter: "16px"
  card-pad: "24px"
  card-pad-action: "22px"
  stack-gap: "16px"
  section-gap: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.btn}"
    padding: "10px 22px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    typography: "{typography.button}"
    rounded: "{rounded.btn}"
    padding: "10px 22px"
  button-secondary-hover:
    backgroundColor: "{colors.primary-tint}"
    textColor: "{colors.primary}"
  button-tertiary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.btn}"
    padding: "10px 22px"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.btn}"
    padding: "10px 22px"
  button-pending:
    backgroundColor: "{colors.pending}"
    textColor: "#451a03"
    rounded: "{rounded.btn}"
    padding: "10px 22px"
  button-large:
    padding: "16px 32px"
  button-flat-chip:
    backgroundColor: "{colors.primary-tint}"
    textColor: "{colors.primary}"
    rounded: "{rounded.flat-chip}"
    padding: "6px 12px"
  card-static:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-pad}"
  card-clickable:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-pad-action}"
  input:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink-heading}"
    rounded: "{rounded.input}"
    padding: "10px 14px"
  badge:
    backgroundColor: "{colors.primary-tint}"
    textColor: "{colors.primary}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  nav-link-active:
    backgroundColor: "{colors.primary-tint}"
    textColor: "#0369a1"
    rounded: "10px"
    padding: "7px 14px"
  nav-link-inactive:
    textColor: "{colors.ink-muted}"
    rounded: "10px"
    padding: "7px 14px"
---

# Design System: IntegratED

<!-- Where this sits: the normative token values live in tailwind.config.js and the clay
     classes in static/css/components/*.css. This file mirrors them for design tools
     (Impeccable reads it); if the two ever disagree, the code wins and this file is refreshed
     with `/impeccable document`. The reasoning behind each rule is in visual-language.md. -->

## Overview

**Creative North Star: "The Clay Classroom"**

IntegratED is built for a young refugee learner who usually cannot read the words on the screen yet, often on a cheap phone, in one of 13 languages, three of them right-to-left. The interface has to say "this is a friendly place to learn, and *this* is the thing you can press" without words. Clay does that: chunky rounded shapes, thick borders, and hard offset shadows the shape physically presses into. Tappability is a material property, not a hover hint.

The feel is **chunky, honest, friendly**. Chunky, because hairlines and subtle affordances vanish on a small cracked screen. Honest, because the whole system rests on one promise: anything that looks pressable is pressable, and anything that isn't stays perfectly still. Friendly, because the users are children and teenagers, and the staff side shares the same warm material at a calmer density. Colour carries fixed meanings rather than variety, illustration carries personality instead of gradients, and meaning never rides on text alone.

The same world serves every role. Learner screens are the loudest: big targets, one question at a time, read-aloud audio, illustration. Teacher and admin screens use the same clay at operating density: tables, flat chips, stat tiles. Public pages go large and fluid, with richer scroll motion. There is one light theme; no dark mode exists.

**Key Characteristics:**
- Hard, zero-blur offset shadows; the shadow colour tells you whether a thing responds.
- 2–2.5px borders everywhere, never a 1px hairline on a clay surface.
- One green primary action per screen; sky is the app's own identity colour.
- Baloo 2 headings over the system font stack.
- Icons, colour and shape on every meaningful element, so a non-reader can follow.
- Presses translate into the shadow; nothing scales on press.

## Colors

A clear sky-blue identity on cool near-white paper, with a small set of signal colours that each mean exactly one thing.

### Primary
- **Classroom Sky** (`primary`): the app's own colour. Identity, links, secondary buttons, focus borders, the logo mark, active nav, the assistant. Darker **Sky Shadow** (`primary-dark`) is the hard shadow under sky clay; **Sky Wash**, **Sky Mist** and **Sky Tint** (`primary-light`, `primary-soft`, `primary-tint`) are the borders, hover fills and tinted chip backgrounds of the sky family.

### Secondary
- **Go Green** (`accent`): the one primary action on a screen: save, submit, register, start. Also success and "done" ticks in progress strips. **Go Green Shadow** (`accent-dark`) sits under it.

### Tertiary
- **Reward Gold** (`gold`): XP, coins, equipped avatar items, the rocket game. Reserved for rewards only.
- **Pending Amber** (`pending`, shadow `pending-dark`): pending, needs review, warning, and the "mark done" action.
- **Alert Rose** (`alert`, shadow `alert-dark`): alert, error, "you lost", and the game-over retry button. Its pale card pair is also the confirm-modal surface.
- **Stop Red** (`danger`, shadow `danger-dark`): destructive actions only: delete, remove, ban. Always confirmed first.
- **Live Blue** (`live`): the pulsing "happening now" dot on the active learning link. Nothing else.

### Neutral
- **Heading Ink** (`ink-heading`): near-black indigo for body text on the page background and for headings. The only surviving use of indigo.
- **Title Navy** (`ink-title`): the page `h1` in a page header.
- **Deep Navy** (`ink-navy`): text in the AI assistant panel and bold runs in legal prose.
- **Body Gray** (`ink-body`), **Muted Gray** (`ink-muted`), **Faint Gray** (`ink-faint`): secondary text, labels and placeholder, in that order of weight.
- **Rule Gray** (`line`): borders of tertiary buttons and dividers.
- **Paper** (`surface-page`): the page background, cool and faintly blue.
- **Card White** (`surface`): every card and button face.
- **Field Paper** (`surface-card`): input fields and toast backgrounds, one breath off white.
- **Card border/shadow pairs** (`card-<tone>-border` / `card-<tone>-shadow`): static cards in sky, green, amber, rose, purple and pink, each a 200-step border over a 100-step shadow.

### Named Rules
**The Fixed Meaning Rule.** Every colour means one thing, and a card or stat tile takes the colour of what its data *means* (unmatched learners are rose, hours are amber), never a colour picked for variety.

**The One Green Rule.** One green primary action per screen. Everything else steps down: sky, then gray.

**The Role, Not Shade Rule.** Templates and CSS ask for a role (`bg-primary`, `var(--color-card-sky-border)`), never a raw hex or palette shade. Re-pointing a role in `tailwind.config.js` re-themes the app; lint fails a raw colour.

## Typography

**Display Font:** Baloo 2 (with system-ui, sans-serif), weights 700 and 800
**Body Font:** the system stack: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif

**Character:** Baloo 2 is round, heavy and warm, the typographic version of clay, and it renders every heading. The body stays on the device's own font so it loads instantly on a slow phone and covers Arabic, Farsi, Pashto and every other interface script natively.

### Hierarchy
- **Display** (800, Baloo 2, large and fluid with `clamp()` on public pages; `text-3xl` for stat-tile numbers): big numbers, the logo wordmark, public-page hero headings.
- **Headline** (800, 1.5rem rising to 1.875rem at `md`, Baloo 2): the page `h1` in `PageHeader`, in Title Navy.
- **Title** (700, around 1.25rem, Baloo 2): section and card headings, `h2`–`h4`.
- **Body** (400, 1rem, 1.5 line height, system stack): paragraphs and table cells. Staff subtitles step down to 0.875rem at Heading Ink 60% opacity.
- **Button** (700, 0.9rem, system stack): every clay button label.
- **Label** (700, 0.7rem, 0.06em tracking, uppercase): section badges above major headings and flat table-row chips (0.7rem, 0.05em).

### Named Rules
**The Headings Are Clay Rule.** Every `h1`–`h4` is Baloo 2 automatically; a non-heading that needs it (a big number, the logo) uses `display-font`. Don't load another display face.

**The Fluid Type Is Public Rule.** `clamp()` type belongs to the public pages, where it is set large. App screens use fixed steps.

## Layout

App pages sit in a centred container with a 16px gutter (`px-4`), 24px vertical padding rising to 32px at `md`, and a max width chosen per page from a fixed set (`md`, `lg`, `2xl` through `5xl`, `7xl`, or full). Single-purpose forms use the centred layout: one column, centred both ways. Public pages and games are full-bleed and compose their own sections, with wide containers and large illustration.

Every page opens with a `PageHeader`: an uppercase section badge, the `h1`, an optional subtitle, and actions at the inline end, stacking to one column below `md`. Sibling cards share the same gap; stat tiles sit in an even grid. Learner screens show one question at a time with large answer targets, and are designed at phone width first.

Layout uses logical directions throughout (`ms-`/`me-`, `margin-inline-start`, `text-align: start`) so every screen mirrors correctly in Arabic, Farsi and Pashto. Horizontal arrows and chevrons mirror automatically.

**The Same Job, Same Composition Rule.** Before inventing a "next step" block, a stat row or an end screen, find the screen that already solves it and reuse its composition.

**The Data Leads Rule.** Where a screen exists to support a decision, it opens with the data that drives that decision, not with navigation or decoration. This matters most for teachers: a teacher screen leads with the numbers they act on this week (unmatched learners, missed sessions, overdue worksheets, who is falling behind). Each number is shown with its comparison or trend and links to the rows behind it, so seeing a problem and acting on it is one click. Learner screens show progress as work done, never as a deficit. Every design change is instrumented in PostHog and judged by whether it moves the product's four success goals; a look that tests worse is reverted, however good it looks.

## Elevation & Depth

Depth is a hard, zero-blur diagonal offset shadow, never a soft blur. Its colour is load-bearing: a clickable element's shadow **matches** its border, while a static element's shadow is **one step paler** than its border. That pale shadow is the only at-rest cue that a card won't respond to a tap. Elevation is expressed by offset size, not blur or darkness.

### Shadow Vocabulary
- **Clay rest** (`box-shadow: 3px 3px 0 <border colour>`, `--clay-offset`): buttons and clickable cards at rest.
- **Clay hover** (offset + lift = 4.5px, element moves −1.5px up-left): hover on any clickable.
- **Clay press** (offset − press = 1px, element moves +2px down-right): the press, glued to its shadow.
- **Small clay** (2px rest, 1px lift, 1px press; `--clay-offset-sm` family): nav buttons, the logo mark, the read-aloud button.
- **Static card** (`4px 4px 0 <paler shade>`, `--clay-static-offset`): every static card, stat tile and panel.
- **Overlay** (`6px 6px 0 <paler shade>`, `--clay-modal-offset`): floating overlays such as the announcement popup and Auto-Match modals.
- **Transient soft** (`0 4px 16px` Heading Ink at 10%): toasts and game hint pills only, because they are passing messages, not objects you touch.

### Named Rules
**The Honest Shadow Rule.** Clickable: shadow colour = border colour, it lifts and presses. Static: shadow one step paler, no hover, no press, default cursor. A static card with a border-matched shadow is the most damaging bug in this system; it looks tappable and does nothing.

**The Exact Maths Rule.** Hover and press shadows are derived, never picked by eye: hover = offset + lift, press = offset − press, computed with `calc()` on the geometry tokens. Half a pixel off reads as a glitch.

**The One Shadow Rule.** One `box-shadow` per element. Never stack a blur behind a hard offset, never add a Tailwind `shadow-*` to a clay element.

## Shapes

Generous, consistent rounding on a fixed scale: inputs 12px, buttons 14px, cards 20px, pills fully round, and flat table chips 8px. Borders are 2–2.5px (`--clay-border-width-thin` / `--clay-border-width`), thick enough to read as a solid edge on a low-end screen. A card nested inside a card steps its radius down, never up. Icon boxes are rounded squares with a 2px tinted border and no shadow. Empty states use a 2px dashed sky border to read as "a space waiting to be filled".

**The No Hairline Rule.** Clay surfaces never take a 1px border; a hairline breaks the chunky read. The only 1px borders are inside small badges.

## Components

Every look is a jx component (`<Button>`, `<Card>`, `<Input>`…) whose allowed props are in `helpers/clay_primitives.py`; pages choose a component and a prop, and never restyle it. The live gallery at `/dev/components` (`?lang=ar` for RTL) shows every variant.

### Buttons
Tactile and unmistakable: a raised clay tile that visibly pushes in.
- **Shape:** gently rounded (14px), 2.5px border in the shadow colour.
- **Primary:** Go Green face, white bold label, Go Green Shadow border and 3px shadow, padding 10px 22px. One per screen.
- **Secondary:** white face, Classroom Sky label, border and shadow; hover fills with Sky Tint.
- **Tertiary:** a shadowless gray ghost (cancel, back, close): white face, Rule Gray border, Muted Gray 600-weight label. Having nothing to press into, it darkens its border and background instead.
- **Danger / Pending / Retry:** Stop Red, Pending Amber (dark amber label) and Alert Rose variants, same physics.
- **Hover / Press:** lift up-left with the shadow growing to 4.5px, then press down-right into a 1px shadow, over 150ms ease-out on `transform` and `box-shadow` only.
- **Large:** 16px 32px padding, for public-page calls to action.
- **Flat chip:** dense table-row actions. A tinted face (the 50 shade), 2px border, 8px radius, 0.7rem uppercase bold label, no shadow; only the background shifts on hover.
- **Disabled:** 55% opacity, keeps its rest shadow, no motion, `not-allowed` cursor; a disabled link also drops its `href`.

### Chips and Badges
- **Style:** fully round pill, 1px tinted border, 0.75rem bold label, padding 2px 10px, in sky (neutral), green (positive / matched), amber (pending / review) or red (alert, PDF).
- **Section badge:** the sky or amber pill above every major heading, uppercase, 0.7rem, 0.06em tracking.

### Cards / Containers
- **Corner Style:** 20px.
- **Background:** Card White.
- **Static card:** 2px border in a tone's 200 shade over a 4px shadow in its 100 shade, 24px padding, no hover. Tones follow meaning: sky default, green success, amber pending, rose alert or error, purple neutral or legal, pink personal preferences.
- **Clickable card:** 3px shadow matching a 200-shade border, 22px padding; on hover it lifts 2px and border and shadow both deepen to the 300 shade. Clickable cards come in sky, green, amber and rose only, never purple or pink.
- **Stat tile:** a static card with a thicker border, centred, the value in 800-weight Baloo 2 coloured by what it means.
- **Header box:** the boxed `PageHeader` on school and org dashboards, a Sky Tint to Sky Mist diagonal wash with the static sky border and shadow.

### Inputs / Fields
- **Style:** Field Paper background, 2px Sky Wash border, 12px radius, padding 10px 14px, 0.9rem text. No offset shadow.
- **Focus:** the border turns Classroom Sky.
- **Select:** styled from the element itself with the same box; where the browser supports customizable selects, the picker is a static clay panel (pale 4px shadow) with rounded option rows and a masked chevron and check.
- **Disabled:** 55% opacity on a light gray fill.

### Navigation
- **Header links:** 10px rounded pills. Inactive is Muted Gray with a transparent 1.5px border; hover and active fill with Sky Tint, Sky Wash border and dark sky text. Bold weight is reserved in the layout so the label doesn't shift on activation.
- **Header buttons:** small clay (2px shadow): Register in Go Green, Login in sky, icon-only buttons in gray that turn sky on hover and on their own page; Logout is a shadowless ghost.
- **Logo mark:** a 34px Classroom Sky rounded square with a 2px dark-sky small-clay shadow, beside the Baloo 2 wordmark.

### Read-aloud Button
A 44px square Classroom Sky button with a speaker icon and small-clay physics. It appears beside every learner question and plays the recorded sound or falls back to speech synthesis. It is the system's promise that anything to read can be heard.

### Toasts and Confirm Modal
- **Toast:** Field Paper surface, 2.5px tone border, 18px radius, the transient soft shadow, a rounded icon disc in the tone, sliding in from the right with a 400ms ease-out.
- **Confirm modal:** a plain rose static card on a 45% Heading Ink backdrop, with a rose icon disc, a 600-weight message and a full-width button row. It keeps the 4px card shadow on purpose.

## Do's and Don'ts

### Do:
- **Do** match a clickable's shadow to its border and make a static element's shadow one step paler (200 border, 100 shadow).
- **Do** derive hover and press from the geometry tokens: rest 3px, hover 4.5px moving −1.5px, press 1px moving +2px.
- **Do** give every hand-rolled clickable a base offset shadow, both `:hover` and `:active`, a visible `:focus-visible`, `type="button"` unless it submits, and a reduced-motion block.
- **Do** transition only the properties that change (`transform`, `box-shadow`, plus colour or border) over about 150ms ease-out.
- **Do** pair every label on a learner screen with an icon, a colour and a shape, and offer read-aloud audio for anything to read.
- **Do** use Heroicons outline through `<Icon>` (stroke 2, `currentColor`), and an `aria-label` when an icon is the only content.
- **Do** design empty, loading and error states: `<EmptyState>` with a friendly line, a disabled button with its reason nearby.
- **Do** use the real illustration in `static/svg/` and `static/img/` for personality.
- **Do** honour `prefers-reduced-motion` in anything that animates for longer than a press.

### Don't:
- **Don't** give a static card a border-matched shadow, a hover, a press or a pointer cursor.
- **Don't** use `scale()` in a press; it shrinks the shadow with the box and reads as receding, not pushed.
- **Don't** stack shadows, add a blur behind a hard offset, or put a Tailwind `shadow-*` on a clay element.
- **Don't** use `transition: all`.
- **Don't** use a 1px border on a clay surface.
- **Don't** write a raw hex, rgb or palette shade where a role token exists, or restyle a component's padding, radius, border, shadow or background from a page.
- **Don't** use colour for variety, use indigo as a UI colour, or use gold for anything but rewards.
- **Don't** put more than one green primary action on a screen.
- **Don't** use emoji or text glyphs as icons; they render differently per platform, don't mirror in RTL, and are announced unpredictably.
- **Don't** let colour be the only cue for state; a tick in a disc means done, a ring means "you are here".
- **Don't** use physical directions (`ml-`, `left-`, `text-left`) where a logical one exists.
- **Don't** show identifiable refugee learners in imagery; illustration carries the learner's side.

# Variant method: how to plan and write live variants

Adapted from Impeccable 4.5.2 `reference/live.md` §3–7 (Paul Bakaus, Apache 2.0), rewritten for
the knob contract in [format.md](format.md).

## 1. Load the action's reference

The action `impeccable` (freeform) works from Impeccable's SKILL.md design rules plus
`craft-floor.md`. Every other action (`bolder`, `quieter`, `distill`, `polish`, `typeset`,
`colorize`, `layout`, `adapt`, `animate`, `delight`, `overdrive`) reads that action's reference
first. Its required knobs (the "Live-mode signature params" sections) count toward the budget in §5.

The files are under the installed Impeccable plugin:
`~/.claude/plugins/cache/impeccable/impeccable/*/skills/impeccable/reference/<action>.md`
(glob the version folder). Read `craft-floor.md` there before writing any markup.

## 2. Plan the variants: identity first, then mode, then axes

Live runs on an existing surface with an established brand. The job is variation **within the
identity**, not a choice between identities. The worst outcome is N off-brand variants the user
can't accept.

**Phase A: extract the identity (never skip).** Sources, in priority order:
`docs/ui-design/DESIGN.md`, the tokens in `tailwind.config.js` (published as `--color-*`,
`--clay-*` and `--radius-*` variables), the computed styles in the brief, and sibling components on
the same page. Write one sentence recording what is actually on screen: the dominant surface and
accent colours (real token names), the font pairing, the layout topology (stacked, side-by-side,
grid, asymmetric or overlay), the surface treatment (corners, borders, clay shadows, decoration
density) and the voice of the copy. That sentence is the **identity lock**. Every variant must read
as the same brand when the variants sit side by side.

**Phase B: pick a mode.** *Default* keeps the identity and varies how it's expressed, which suits
about 90% of requests. Use *departure* only when the current request asks outright for "redesign
this", "start from scratch" or "something completely different". If unsure, use default: a
mistaken default gives on-brand variants that feel too alike, which a refine fixes; a mistaken
departure gives off-brand variants, which nothing fixes.

**Phase C: plan the variants.**
- *Default:* each variant commits to a different **primary axis** and keeps the identity lock.
  The axes: 1 hierarchy (what takes the eye first), 2 layout topology, 3 typographic system
  (pairing logic, scale ratio, case and weight, using only the loaded faces), 4 colour strategy
  (which existing palette role carries the surface: restrained, committed, full palette or
  drenched; existing tokens only), 5 density, 6 structural decomposition (merge, split,
  progressive disclosure). N variants use N different axes. New fonts, new hues and new aesthetic
  families belong to departure mode only.
- *Departure:* each variant anchors to a different aesthetic direction derived from
  `docs/PRODUCT.md`'s brand personality. Give each direction one concrete sentence that names a
  real-world referent (for example "a museum exhibition label system", never "clean and minimal").
- *Both modes:* choose each variant's knobs (§5) while planning, not afterwards.

**Phase D: the squint test.** *Default:* hold each variant against the identity lock; drift in
palette, type voice or rhetoric means it slipped into departure, so rework it. Then check that each
variant uses a different primary axis. *Departure:* give each variant a concrete family label of
your own; if two labels overlap, rework one. When colour or theme is the axis, no two variants may
share both theme and dominant hue.

## 3. Action-specific spread

When an action is named, the variants differ along that action's dimension:

| Action | Each variant varies… |
|---|---|
| bolder | a different dimension amplified: scale, saturation or structure |
| quieter | a different dimension pulled back: colour, ornament or spacing |
| distill | a different class of excess removed: visual noise, redundant content or nesting |
| polish | a different refinement axis: rhythm, hierarchy or micro-detail |
| typeset | a different pairing **and** a different scale ratio |
| colorize | a different hue family, with chroma and contrast strategy varied too |
| layout | a different structural arrangement, not spacing tweaks |
| adapt | a different target context: mobile-first, tablet, desktop, print or low-data |
| animate | a different motion vocabulary: stagger, clip wipe, scale-and-focus, morph or parallax |
| delight | a different flavour: micro-interaction, typographic surprise, illustrated accent, sound or easter egg |
| overdrive | a different convention broken: scale, structure, motion, input model or state transitions |

## 4. The prompt is a ceiling

The user's prompt bounds the direction. Every variant honours it while exploring a different
reading of it. In default mode the prompt narrows the axes, not the identity: "more confident"
might mean one variant amplifies hierarchy, one commits the accent colour and one tightens
density. When the prompt conflicts with a DESIGN.md invariant, keep the invariant unless the user
explicitly overrides it. Annotations: a comment's position binds it to the child under that point.
Stroke shapes: a closed loop means "this thing", an arrow means direction or movement, a cross
means delete, and a scribble means emphasis or delete depending on context.

## 5. Knobs: budget and authoring

Knobs are coarse tweaks the user makes in the browser with no regeneration. Expose an axis as
soon as the user could plausibly say "a bit tighter" or "a touch more accent". One-off nudges are
not knobs.

Budget, by the element's visual weight (count visual children, not DOM depth):

| Element | Knobs per variant |
|---|---|
| Leaf (button, icon, bare heading) | 0 |
| Small composition (simple card, labelled input, ≤ 5 visual children) | 0–1 |
| Medium (section, nav cluster, 6–15 children) | target 2 |
| Large (hero, full region, 16+ children) | target 2–3, up to 4 |

Hard cap: 4. Under the freeform action, a hero with 0 knobs is almost always a mistake.

Every knob kind sets **one CSS custom property, `--p-<id>`, on the variant's root element**, and
the markup and CSS read that property through `var(--p-<id>, <default>)`. The schema and the
accept-time baking are in [format.md](format.md) under "Knob contract". In short:

- `range`: a slider; the value is a number, plus `unit` if one is set.
- `steps`: a segmented control; each option carries the literal CSS value it sets
  (`{"label": "Airy", "value": "2.5rem"}`).
- `toggle`: on or off, each mapped to a literal CSS value.

A knob may only change what a CSS custom property can reach: sizes, spacing, colours (as token
`var(--color-…)` references), opacity, weights, durations, grid tracks. A knob that would need
different markup is a different variant, not a knob.

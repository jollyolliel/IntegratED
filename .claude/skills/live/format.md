# The variants file and the knob contract

What Claude writes to `.live/<session>.jx` before running `scripts/live.py wrap` or `refine`.
The script owns the wrapper that lands in the template; never write or edit that by hand.

## Variants file

```jinja
{# variant name="Louder heading" #}
{# knobs [{"id": "scale", "kind": "range", "label": "Heading size", "min": 0.85, "max": 1.3, "step": 0.05, "default": 1}] #}
<style>.hero-title{font-size:calc(var(--p-scale,1)*3rem)}</style>
<section class="hero …">
  …one top-level element, full Jinja/jx allowed…
</section>
{# variant name="Calmer, more air" #}
<section class="hero …">…</section>
```

Each variant, in order:

1. `{# variant name="…" #}`: a short name the user sees in the cycler (no `"` inside).
2. Optional `{# knobs […] #}`: a JSON list, see below.
3. Optional `<style>…</style>`, CSS only for what Tailwind utilities and existing component props
   can't express.
4. Exactly **one top-level element**. A single element inside `{% if %}…{% endif %}` counts as one.

Indentation is free: the script re-indents to the template's.

**Copy.** Existing `t()` keys, jx components, `url_for` and loops are all fine; Flask renders them
for real. New copy is literal English; it becomes `t()` keys at accept, so rejected variants never
leave keys behind.

**CSS selectors** start with a class (or an `[attr]`) that is on or inside the variant's element:
`.hero-title`, `.hero .cta`. The script prefixes each rule with `[data-live-variant="N"] ` and
strips it again at accept, so it refuses bare element (`section`), id (`#hero`) and combinator-first
(`> .a`) selectors. `@media`, `@supports` and `@container` rules are scoped inside; `@keyframes` are
not, so give each variant's keyframes a distinct name.

**Limits** the script enforces: 1–8 variants per round (a refine counts the kept one), at most 4
knobs per variant.

## A finished element

`accept <id> --variants <file>` closes a session with an element Claude finished by hand (see
SKILL.md, "Finishing an element"). The file uses the same format with exactly one variant and no
knobs line, no `<style>` and no `var(--p-…)`: the knob values are written in and the CSS already
sits in its own home. The script refuses anything else.

## Knob contract

Every knob sets **one CSS custom property, `--p-<id>`**, on the variant's wrapper. Markup and CSS
read it through `var(--p-<id>,<default>)`; Tailwind arbitrary values work too, written without
spaces: `gap-[var(--p-gap,1.5rem)]`.

```json
[
  {"id": "scale", "kind": "range", "label": "Heading size", "min": 0.85, "max": 1.3, "step": 0.05, "default": 1, "unit": "rem"},
  {"id": "gap", "kind": "steps", "label": "Spacing", "default": "snug",
   "options": [{"key": "airy", "label": "Airy", "value": "2.5rem"}, {"key": "snug", "label": "Snug", "value": "1.5rem"}]},
  {"id": "accent", "kind": "toggle", "label": "Accent fill", "default": false,
   "on": "var(--color-accent)", "off": "transparent"}
]
```

- `id` matches `[a-z][a-z0-9-]*`; every knob needs a `label`.
- `range`: numeric `min`, `max`, `step`, `default`; optional `unit` appended to the value.
- `steps`: `options` of `{key, label, value}`; `default` is one of the keys.
- `toggle`: string `on` and `off`; boolean `default`.
- No `'` anywhere in the JSON: it is written into a single-quoted attribute.

At accept the script bakes each `var(--p-<id>, …)` into the chosen literal (the range number plus
its unit, the step's `value`, or the toggle's `on`/`off`), so a knob may only reach what a custom
property can: sizes, spacing, colours as `var(--color-…)` tokens, opacity, weights, durations, grid
tracks. Using `var(--p-x)` without declaring knob `x` fails at accept.

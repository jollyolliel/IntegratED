# Components in three layers: base, composed, shell

The first component set gave every clay class family its own component, so
52 components shipped, 36 of them "primitives". Several were one look split in
two (`ImpactCard` and `StatTile`, `ActionCard` and `Card`), five pills each
owned a near-identical class, and `<Display tag="h2">` wrapped every heading
just to set a font.

Components now sit in three folders under `templates/components/`. `base/`
holds the building blocks: Icon, Button, Card (static, or clickable through
`href` / `clickable`), Badge, Input, Textarea, Choice, Field (with its
error message), Table and ProgressBar. Composed components at the top level are
built from bases and add utilities to reach their look: a StatTile is a Card
with tighter padding and a thicker border, and SectionBadge, CountPill,
StatusPill and FileTypeBadge are Badges with their own size and case. Clay
component CSS loads before Tailwind's utilities, so an added utility beats its
base's class without `!`, and each composed look matches the class it replaced
to the pixel. `shell/` holds the page shells and the header / footer chrome.

Headings take Baloo 2 from a global `h1–h4` rule in `base.css`, and every
single-choice `<select>` is clay from the element in `forms.css` (its
`<button><selectedcontent>` first child enforced by the jx lint); `display-font`
and `clay-scroll` are free classes any template may write. The old classes
(`impact-card-*`, `section-badge*`, `count-pill*`, `status-*`,
`file-type-*`) stay in the stylesheets only for the `.html` pages spec 04 has
not converted, are a lint error in `.jx`, and are deleted in spec 04.

The design flows downhill but can be left on purpose. The `no-restyle-*` rules
guard pages only. A composed component may restyle its base, and a page may
restyle one tag with a `{# design: override — <reason> #}` comment, which is
reported if it gives no reason.

**Considered options**

- **One component per class family, kept.** Fewer moving parts per component,
  but the duplicates were already drifting, and a page author had to know
  which of five pills to reach for.
- **A `font-display` Tailwind token instead of the free `display-font` class.**
  Neater, but it changes the tokens (ADR 0011) for no gain over a class that
  already exists and that the unconverted `.html` pages still write.
- **Base components with variant props for every composed look** (`<Card
  variant="stat">`). Keeps every look in one file, but grows the bases back
  into the per-family components this replaces.

Status: accepted.

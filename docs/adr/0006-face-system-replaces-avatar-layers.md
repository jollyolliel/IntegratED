# Face System replaces the layered Avatar System

The original character customization system (the "Avatar System") built a
full-body character from eight image layers — background, base, hair, hat,
top, bottom, shoes, accessory — each positioned by a computed transform
derived from the asset's native size, a per-category anchor against the base
character's head, and a hand-tuned per-item override to correct for how
inconsistent the source art was. Getting one new item to sit correctly
required opening a dedicated tuning tool, dragging it into place against the
current head position, and exporting the resulting offset/scale numbers back
into the codebase. For an audience of largely illiterate young learners, the
payoff of that machinery — an anatomically composed, layered body — wasn't
worth its authoring cost, and every new clothing item was a bottleneck
through that tuning step.

The decision was to replace it with the Face System: five flat, transparent
SVGs (species, hair, eyes, mouth, extra) stacked with plain
`position: absolute` in a fixed render order, needing zero transform math and
no tuning tool. A new item just needs an asset in the right category and a
row in the catalogue. The trade-off is expressive range — a full-body
character with clothing and accessories became a face-only avatar — accepted
because simplicity and low authoring cost mattered more than customization
depth for this audience. The Avatar System's code, dev tuning route, and
asset catalogue stay in the repo purely as a reference for the transform math
if a future full-body system is ever attempted, but are not used by any
active feature.

Status: superseded by ADR 0017 — the Face System became a full-body avatar and the Avatar System's code was deleted.

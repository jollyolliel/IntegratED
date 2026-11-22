# The Face System is the full-body avatar; the old Avatar System is deleted

ADR 0006 replaced the layered Avatar System with the Face System: five flat
SVGs stacked in a fixed order, no transform math, no tuning tool. It kept the
Avatar System's code in the repo "purely as a reference". Two things have
since changed. The Face System grew a body: `top`, `bottom` and `shoes`
layers plus an outfit `colour` that tints them, all in one 200×300 box, still
with no transforms. And the reference code was not inert: the equip route still
accepted the old catalogue's ids, and their slot names (`hair`, `top`,
`bottom`, `shoes`) collide with the Face System's. A learner with old data, or
an old id posted to the route, got broken layers or lost clothes, because the
dashboard cleaned stored items on render while the equip response returned
them raw.

The decision is that the Face System is the only avatar. `resolve_face`
(`helpers/gamification/_face.py`) reads what a learner wears, keeping only
Face System items that fit their slot, and both the dashboard and the equip
response use it, so they always agree. The equip route accepts Face System ids
only. `_character.py`, its catalogue and its tests are deleted. Git history
keeps the transform math if a different avatar is ever attempted.

Consequences: a learner's stored old-catalogue items are ignored and replaced
by the Face System defaults for those slots on their next equip. Level-ups now
report the wardrobe items they unlock (`items_unlocked_between`), which the
level-up modal shows.

Supersedes ADR 0006.

Status: accepted.

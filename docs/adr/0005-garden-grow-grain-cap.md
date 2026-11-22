# Garden Grow grains are capped against the correct-answer count

Garden Grow lets a Learner spend an earned water drop on a rainstorm that
grows *every* planted plot at once, and any plot already at max growth pays
out a grain (bonus XP) instead of growing further. Left uncapped, this is an
XP exploit: a Learner who fully grows a small garden can trigger storm after
storm, harvesting the same maxed-out plots repeatedly for grains that were
never re-earned by answering anything.

The decision is to cap grains awarded per completion at
`correct_count * GARDEN_PLOTS` server-side, independent of whatever the
client reports it earned. This still allows the legitimate ceiling a mature
garden can reach — one correct answer's storm can harvest up to
`GARDEN_PLOTS` super blooms at once — while refusing to pay out more grains
than the number of correct answers could plausibly have produced. The same
anti-cheat shape is used for `correct_count` itself elsewhere in the
gamified lessons: never trust a client-reported total; cap it against a
value the server can independently verify.

Status: accepted.

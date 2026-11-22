# Announcement dismissal is a high-water mark, not a foreign key

Tracking which "what's new" popups a user has dismissed looks, at first
glance, like a job for a foreign key or a join table — one row per user per
seen announcement, the usual shape for a many-to-many "has seen" relation.
That shape has a sharp edge here: announcements are periodically pruned, and
a foreign key pointing at a deleted announcement would either cascade-delete
the user's dismissal record or null it out — either way, re-exposing a popup
the user already closed.

The decision is to store a single integer per user: the highest announcement
id they have dismissed, compared with plain `>=`, never joined to the
announcements table at all. Dismissing an announcement sets it to
`max(current, that id)`, so acting on an older popup can never move the mark
backwards and re-expose newer ones the user hasn't seen yet. The trade-off:
this only works because announcement ids are monotonically increasing and
"seen" is all-or-nothing up to a point — there is no way to represent "saw
announcement 5 but not 4," which the schema deliberately doesn't need to
express.

Status: accepted.

# Assistant reads are auto-derived and fail closed; writes are curated by hand

The teacher AI assistant needs to answer open-ended questions over the whole
schema, but must never let one teacher read or change another school's (or
another teacher's) data, and must never let a proposed change bypass an
invariant that only exists in route code — a capacity limit, a forced
absence duration, a match's two-sided `is_matched` bookkeeping. A single
"generic CRUD over the mapper" tool would satisfy the open-endedness for
free, at the cost of every one of those invariants and every access
boundary.

The decision splits the two directions of the assistant's tool traffic
differently, because they carry different risk. Reads are scoped
automatically: which rows of which model a teacher's conversation may see is
derived by walking foreign-key relationships out from that teacher, with an
explicit rule that a model with no discoverable path to a teacher is
unreachable until someone deliberately classifies it — failing closed by
default, not by exception. The worst case of an over-broad read is a useless
or embarrassing answer, so auto-deriving it is an acceptable risk for the
reach it buys. Writes get no such shortcut: every mutation the assistant can
propose is a hand-written, individually reviewed tool that replays through
the same mutation functions the real routes use, so a staged write can never
sidestep validation the UI would have enforced. A write that is technically
legal but wrong for the situation still looks fine in review, so the cost of
a mistake there is real — new write capability is deliberately priced at one
reviewed function per operation, not a blanket grant.

Status: accepted.

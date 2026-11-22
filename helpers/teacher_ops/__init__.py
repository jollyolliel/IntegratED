"""Teacher mutations, shared by the routes and the AI assistant's apply path.

Every function here takes an explicit ``teacher`` (never ``current_user``),
reads no request state, and raises plain exceptions instead of calling
``abort()`` — that is what makes them callable from outside a request-shaped
context. Flask concerns (flash, redirect, ``wants_json()``, analytics) stay in
``routes/teacher/``.

Each op has a ``validate_*`` twin returning the resolved rows and normalized
arguments without touching the DB, so a staged assistant change can be rejected
at staging time rather than at apply time.

Exceptions:
  ``LookupError``     — no such row (route: 404)
  ``PermissionError`` — row belongs to another teacher (route: 403)
  ``Refusal``         — a ``ValueError``: the request is malformed or breaks an
                        invariant (400); routes show it via ``refusal_message(e)``,
                        which hides the text of any other exception.

Layout:
  _shared.py      _owned ownership check, date/bool coercion, MAX_VOLUNTEER_CAPACITY
  _worksheets.py  assign_worksheet, set_assignment_completion, complete_assignments, and the
                  tracker's queries (learner_assignments, assignment_summary, pair_rows)
  _attendance.py  update_user_attendance, log_attendance_batch/pair
  _matching.py    volunteer capacity, match settings, match/unmatch_pair, assign_unassigned
"""

from helpers.teacher_ops._attendance import (  # noqa: F401
    log_attendance_batch,
    log_attendance_pair,
    update_user_attendance,
    validate_log_attendance_batch,
    validate_log_attendance_pair,
    validate_update_user_attendance,
)
from helpers.teacher_ops._matching import (  # noqa: F401
    AppliedMoves,
    apply_moves,
    assign_unassigned,
    match_pair,
    set_default_capacity,
    set_match_settings,
    set_volunteer_capacity,
    unmatch_pair,
    validate_match_pair,
    validate_set_default_capacity,
    validate_set_match_settings,
    validate_set_volunteer_capacity,
    validate_unmatch_pair,
)
from helpers.teacher_ops._shared import (  # noqa: F401
    MAX_VOLUNTEER_CAPACITY,
    _coerce_bool,
    _coerce_date,
    _owned,
)
from helpers.teacher_ops._worksheets import (  # noqa: F401
    RECENT_COMPLETED_DAYS,
    STALE_AFTER_DAYS,
    AssignmentSummary,
    PairRow,
    assign_worksheet,
    assignment_summary,
    complete_assignments,
    learner_assignments,
    outstanding_count,
    owned_assignments,
    pair_rows,
    set_assignment_completion,
    validate_assign_worksheet,
    validate_set_assignment_completion,
)

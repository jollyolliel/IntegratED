"""Teacher blueprint.

Layout:
  dashboard.py   dashboard, people/roster, default capacity, learner/volunteer detail
  attendance.py  marking, history, CRUD
  worksheets.py  browse/assign/upload/print
  worksheet_assignments.py  the assigned-worksheets tracker, batch print/complete
  matching.py    pair/unmatch/capacity

`teacher_bp` is created here first; each submodule does
`from routes.teacher import teacher_bp` and that succeeds even though this
module is still initializing, because `teacher_bp` is already bound in
`routes.teacher`'s namespace by the time the bottom-of-file imports run.
"""
from flask import Blueprint, abort
from flask_login import login_required

from extensions import limiter
from helpers.current_user import current_teacher as current_user

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")
limiter.limit("120 per minute")(teacher_bp)


@teacher_bp.before_request
@login_required
def limit_to_teachers():
    if current_user.user_type != "teacher":
        abort(403)


# Imported at the bottom so each submodule's `@teacher_bp.route(...)`
# decorators run and register against the already-created `teacher_bp`.
from routes.teacher import (  # noqa: F401
    attendance,
    dashboard,
    matching,
    worksheet_assignments,
    worksheets,
)

# Kept importable at the package root for backward compatibility — tests
# exercise the worksheet-extension allowlist directly via
# `from routes.teacher import _allowed_worksheet_file`.
from routes.teacher.worksheets import _allowed_worksheet_file  # noqa: F401

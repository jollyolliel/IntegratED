from datetime import UTC, datetime

from flask import abort, jsonify, redirect, url_for

from extensions import db
from helpers.analytics import capture_event
from helpers.current_user import current_learner as current_user
from helpers.documents import render_worksheet_html
from helpers.render import render_template
from helpers.utils import wants_json
from models import WorksheetAssignment
from routes.learner import learner_bp


@learner_bp.route("/worksheets/<int:assignment_id>")
def learner_worksheet_view(assignment_id):
    assignment = db.session.get(WorksheetAssignment, assignment_id)
    if not assignment or assignment.learner_id != current_user.id:
        abort(403)
    capture_event(
        str(current_user.id),
        "page_viewed",
        properties={"page": "learner_worksheet_view", "assignment_id": assignment_id},
    )
    return render_template(
        "@pages/learner/worksheet_view.jx",
        assignment=assignment,
        worksheet_html=render_worksheet_html(assignment.worksheet),
    )


@learner_bp.route("/worksheets/<int:assignment_id>/file")
def learner_worksheet_file(assignment_id):
    from helpers.storage import get_bucket
    assignment = db.session.get(WorksheetAssignment, assignment_id)
    if not assignment or assignment.learner_id != current_user.id:
        abort(403)
    ws = assignment.worksheet
    if ws.file_type != "pdf":
        abort(404)
    if not ws.filepath:
        abort(404)
    storage = get_bucket()
    if not storage.exists(ws.filepath):
        abort(404)
    return storage.send(ws.filepath, "application/pdf")


@learner_bp.route("/worksheets/<int:assignment_id>/complete", methods=["POST"])
def learner_complete_worksheet(assignment_id):
    assignment = db.session.get(WorksheetAssignment, assignment_id)
    if not assignment or assignment.learner_id != current_user.id:
        abort(403)
    assignment.completed = True
    assignment.completed_at = datetime.now(UTC)
    db.session.commit()
    capture_event(
        str(current_user.id),
        "worksheet_completed",
        properties={"assignment_id": assignment_id, "worksheet_id": assignment.worksheet_id},
    )
    if wants_json():
        return jsonify(success=True)
    return redirect(url_for("learner.learner_worksheet_view", assignment_id=assignment_id))

import os

from flask import (
    abort,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from extensions import db
from helpers import teacher_ops
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from helpers.documents import generate_assignments_pdf, render_worksheet_html
from helpers.learning import (
    build_teacher_pair_summaries,
    get_pair_learning_snapshot,
    get_recommended_worksheets,
    get_teacher_pair_or_404,
)
from helpers.render import render_template
from helpers.utils import (
    get_pair_display_name,
    safe_local_path,
    utcnow_naive,
    wants_fragment,
    wants_json,
)
from helpers.worksheet_library import (
    MAX_TAG_LENGTH,
    MAX_TAGS,
    WORKSHEET_LEVELS,
    library_batch,
    library_fragment,
    library_levels,
    library_subjects,
    normalize_tags,
    requested_level,
    requested_page,
    track_library_view,
)
from models import Subject, Topic, Worksheet, WorksheetAssignment
from routes.teacher import teacher_bp

_ALLOWED_WORKSHEET_EXTENSIONS = {"md", "pdf"}
# The worksheet page lists this many of its newest assignments to the teacher's learners.
ALREADY_ASSIGNED_PREVIEW_SIZE = 5


def _allowed_worksheet_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in _ALLOWED_WORKSHEET_EXTENSIONS


def _upload_curriculum() -> dict[str, list[str]]:
    """Subject name -> topic titles, topics in learning-path order (level, then id): the values
    the upload form's dropdowns offer. Placement-only subjects are no place to file a worksheet."""
    rows = db.session.execute(
        db.select(Subject.name, Topic.title)
        .outerjoin(Topic, Topic.subject_id == Subject.id)
        .where(Subject.map_test_only.is_(False))
        .order_by(Subject.name, Topic.level, Topic.id)
    )
    curriculum: dict[str, list[str]] = {}
    for subject_name, topic_title in rows:
        titles = curriculum.setdefault(subject_name, [])
        if topic_title is not None:
            titles.append(topic_title)
    return curriculum


@teacher_bp.route("/worksheets")
def teacher_worksheets():
    """Browse the worksheet library, load-more at `WORKSHEETS_LIBRARY_PAGE_SIZE`
    and filtered server-side by `?subject=`, `?level=` and `?q=` (title/subject/
    topic/tag substring). A `?learner=<id>` deep-link from a pair's page adds a
    "recommended for" banner and, absent an explicit subject, filters the
    library to that pair's recommended subject too.

    `wants_fragment()` (the load-more/search fetch) returns just the next
    batch of cards, with `X-Has-More`/`X-Total-Count` headers driving the
    client's "Load more" button and stat tile — never the full page."""
    teacher = current_user
    selected_subject = request.args.get("subject", "").strip()
    q = request.args.get("q", "").strip()
    selected_level = requested_level()
    matched_pairs = build_teacher_pair_summaries(teacher, recommendation_limit=3)

    recommended_for = None
    recommended_ids = []
    learner_id = request.args.get("learner", type=int)
    if learner_id:
        learner, volunteer = get_teacher_pair_or_404(teacher, learner_id)
        snapshot = get_pair_learning_snapshot(learner)
        recommended_ids = [w.id for w in get_recommended_worksheets(
            snapshot["subject"], snapshot["topic"], limit=6, level=snapshot["level"])]
        recommended_for = {
            "learner": learner,
            "volunteer": volunteer,
            "subject": snapshot["subject"],
            "topic": snapshot["topic"],
        }
        if not selected_subject:
            selected_subject = snapshot["subject"]

    batch = library_batch(selected_subject, q, requested_page(), level=selected_level)
    track_library_view(teacher.id, "teacher_worksheets", q, batch, level=selected_level,
                       selected_subject=selected_subject or "all")

    if wants_fragment():
        return library_fragment(
            "@page_components/teacher/worksheet_cards.jx", batch,
            matched_pairs=matched_pairs, recommended_ids=recommended_ids,
        )
    return render_template(
        "@pages/teacher/worksheets.jx",
        worksheets=batch.worksheets,
        subjects=library_subjects(),
        levels=library_levels(),
        selected_level=selected_level,
        upload_curriculum=_upload_curriculum(),
        upload_levels=list(WORKSHEET_LEVELS),
        tag_max_length=MAX_TAG_LENGTH,
        selected_subject=selected_subject,
        q=q,
        matched_pairs=matched_pairs,
        outstanding_count=teacher_ops.outstanding_count(teacher),
        recommended_for=recommended_for,
        recommended_ids=recommended_ids,
        endpoint="teacher.teacher_worksheets",
        has_more=batch.has_more,
        total_worksheets=batch.total,
    )

@teacher_bp.route("/worksheets/assign", methods=["GET", "POST"])
def teacher_bulk_assign_worksheets():
    teacher = current_user
    matched_pairs = build_teacher_pair_summaries(teacher, recommendation_limit=4)
    all_worksheets = db.session.scalars(
        db.select(Worksheet).order_by(Worksheet.subject.asc(), Worksheet.title.asc())
    ).all()

    if request.method == "POST":
        created_assignments = []
        double_sided = "on" in request.form.getlist("double_sided")
        for pair in matched_pairs:
            worksheet_ids = request.form.getlist(f"worksheet_for_{pair['learner'].id}", type=int)
            for worksheet_id in worksheet_ids:
                assignment = teacher_ops.assign_worksheet(teacher, pair["learner"].id, worksheet_id)["assignment"]
                created_assignments.append(assignment)

        if created_assignments:
            capture_event(
                str(teacher.id),
                "worksheet_assigned",
                properties={"assignment_count": len(created_assignments), "mode": "bulk"},
            )
            return generate_assignments_pdf(created_assignments, f"worksheet-packet-{utcnow_naive().strftime('%Y%m%d-%H%M%S')}.pdf", double_sided)

    return render_template("@pages/teacher/worksheet_assigner.jx", matched_pairs=matched_pairs, all_worksheets=all_worksheets)

@teacher_bp.route("/worksheets/<int:worksheet_id>")
def teacher_worksheet_preview(worksheet_id):
    teacher = current_user
    worksheet = db.get_or_404(Worksheet, worksheet_id)
    capture_event(
        str(teacher.id),
        "page_viewed",
        properties={"page": "teacher_worksheet_preview", "worksheet_id": worksheet_id},
    )
    learner_id = request.args.get("learner_id", type=int)
    preselected_pair = None
    if learner_id:
        l, v = get_teacher_pair_or_404(teacher, learner_id)
        preselected_pair = {"learner": l, "volunteer": v}

    # Who already has this sheet, so a teacher sees a repeat before making one. The learner
    # is the gate (a colleague's assignment to one of their learners counts).
    already_assigned = db.session.scalars(
        teacher_ops.learner_assignments(teacher)
        .where(WorksheetAssignment.worksheet_id == worksheet.id)
        .order_by(WorksheetAssignment.assigned_at.desc(), WorksheetAssignment.id.desc())
        .limit(ALREADY_ASSIGNED_PREVIEW_SIZE)
    ).all()

    return render_template(
        "@pages/teacher/worksheet_preview.jx",
        worksheet=worksheet,
        worksheet_html=render_worksheet_html(worksheet),
        matched_pairs=build_teacher_pair_summaries(teacher, recommendation_limit=2),
        preselected_pair=preselected_pair,
        already_assigned=already_assigned,
    )

@teacher_bp.route("/worksheets/<int:worksheet_id>/assign", methods=["POST"])
def teacher_assign_single_worksheet(worksheet_id):
    """Create one `WorksheetAssignment` for a pair. Never returns a PDF itself:
    `then=print` (the "Assign & print" button) sends the browser on to that
    assignment's PDF (`teacher_print_assignments`); otherwise the teacher stays on the worksheet. The
    JSON answer carries `print_url` either way, for the page's script."""
    teacher = current_user
    worksheet = db.get_or_404(Worksheet, worksheet_id)
    learner_id = request.form.get("learner_id", type=int)
    then_print = request.form.get("then") == "print"

    if not learner_id: abort(400)
    # This route only ever assigns to a matched pair — the 404 on an unmatched
    # learner is the gate, not an accident. teacher_ops is deliberately looser
    # (an unmatched learner still gets worksheets) so the assistant can use it.
    learner, _volunteer = get_teacher_pair_or_404(teacher, learner_id)

    assignment = teacher_ops.assign_worksheet(teacher, learner.id, worksheet.id)["assignment"]
    capture_event(
        str(teacher.id),
        "worksheet_assigned",
        properties={
            "assignment_count": 1,
            "worksheet_id": worksheet.id,
            "learner_id": learner.id,
            "then_print": then_print,
        },
    )

    print_url = url_for("teacher.teacher_print_assignments", ids=assignment.id)
    message = f'"{worksheet.title}" assigned to {get_pair_display_name(learner, _volunteer)}.'
    if wants_json():
        # Plain text: the toast sets it as textContent, and a flash is escaped by the header's template.
        return jsonify(success=True, message=message, assignment_id=assignment.id, print_url=print_url)
    if then_print:
        return redirect(print_url)
    flash(message, "success")
    return redirect(url_for("teacher.teacher_worksheet_preview", worksheet_id=worksheet.id, learner_id=learner.id))

@teacher_bp.route("/worksheet-assignments/<int:assignment_id>/complete", methods=["POST"])
@teacher_bp.route("/worksheet-assignments/<int:assignment_id>/reopen", methods=["POST"],
                  endpoint="teacher_reopen_assignment")
def teacher_complete_assignment(assignment_id):
    """Teacher-side completion toggle for a worksheet on the learner page or the
    tracker; a same-site `next` says where a plain (no-JS) post returns to.

    The learner has their own route (`learner.learner_complete_worksheet`); this
    is the teacher marking off a sheet handed back on paper."""
    teacher = current_user
    completed = not request.path.endswith("/reopen")
    try:
        result = teacher_ops.set_assignment_completion(teacher, assignment_id, completed)
    except LookupError:
        abort(404)
    except PermissionError:
        abort(403)

    assignment = result["assignment"]
    capture_event(
        str(teacher.id),
        "worksheet_completion_set",
        properties={
            "assignment_id": assignment.id,
            "learner_id": assignment.learner_id,
            "completed": completed,
        },
    )

    message = "Worksheet marked complete." if completed else "Worksheet reopened."
    if wants_json():
        return jsonify(success=True, message=message, completed=completed)
    return redirect(
        safe_local_path(request.form.get("next"))
        or url_for("teacher.teacher_learner_detail", learner_id=assignment.learner_id)
    )

@teacher_bp.route("/worksheets/<int:worksheet_id>/file")
def teacher_worksheet_file(worksheet_id):
    from helpers.storage import get_bucket
    worksheet = db.get_or_404(Worksheet, worksheet_id)
    if worksheet.file_type != "pdf":
        abort(404)
    if not worksheet.filepath:
        abort(404)
    storage = get_bucket()
    if not storage.exists(worksheet.filepath):
        abort(404)
    return storage.send(worksheet.filepath, "application/pdf")

@teacher_bp.route("/worksheets/upload", methods=["POST"])
def teacher_upload_worksheet():
    from helpers.storage import get_bucket
    teacher = current_user
    file = request.files.get("file")
    title = request.form.get("title", "").strip()
    subject = request.form.get("subject", "").strip()
    topic = request.form.get("topic", "").strip()
    raw_level = request.form.get("level", "").strip()
    level = int(raw_level) if raw_level.isdigit() else None
    tags = [tag for tag in normalize_tags(request.form.get("tags", "").split(",")) if len(tag) <= MAX_TAG_LENGTH]

    if not file or not file.filename:
        abort(400)
    if not title or not subject:
        abort(400)
    if raw_level and level not in WORKSHEET_LEVELS:
        abort(400)
    if not _allowed_worksheet_file(file.filename):
        abort(400)
    # Subject/topic come from dropdowns of the real curriculum; a hand-crafted
    # POST naming anything else would orphan the worksheet from recommendations.
    curriculum = _upload_curriculum()
    if subject not in curriculum or (topic and topic not in curriculum[subject]):
        abort(400)

    storage = get_bucket()

    ext = file.filename.rsplit(".", 1)[1].lower()
    base = secure_filename(os.path.splitext(file.filename)[0])
    unique_filename = f"{base}_{int(utcnow_naive().timestamp())}.{ext}"

    if storage.prefers_inline_storage(ext):
        # Store markdown content in DB — no blob needed
        content_text = file.read().decode("utf-8")
        ws = Worksheet(
            title=title,
            subject=subject,
            topic=topic or None,
            level=level,
            tags=tags[:MAX_TAGS],
            file_type="md",
            content=content_text,
        )
    else:
        filepath = storage.save_upload(file, unique_filename)
        ws = Worksheet(
            title=title,
            subject=subject,
            topic=topic or None,
            level=level,
            tags=tags[:MAX_TAGS],
            filepath=filepath,
            file_type=ext,
        )

    db.session.add(ws)
    db.session.commit()
    capture_event(
        str(teacher.id),
        "worksheet_uploaded",
        properties={"worksheet_id": ws.id, "file_type": ext, "subject": subject, "level": level,
                    "tag_count": len(ws.tags or [])},
    )
    return redirect(url_for("teacher.teacher_worksheets"))

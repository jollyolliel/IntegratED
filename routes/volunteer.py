from flask import (
    Blueprint,
    abort,
    redirect,
    request,
    url_for,
)
from flask_login import login_required

from extensions import db, limiter
from helpers.analytics import capture_event
from helpers.announcements import get_pending_announcement
from helpers.auth_utils import match_required
from helpers.current_user import current_volunteer as current_user
from helpers.documents import render_worksheet_html
from helpers.learning import get_pair_learning_snapshot
from helpers.render import render_template
from helpers.utils import wants_fragment
from helpers.worksheet_library import (
    library_batch,
    library_fragment,
    library_levels,
    library_subjects,
    requested_level,
    requested_page,
    track_library_view,
)
from models import Lesson, Subject, Topic, Worksheet, WorksheetAssignment

volunteer_bp = Blueprint("volunteer", __name__, url_prefix="/volunteer")
limiter.limit("120 per minute")(volunteer_bp)

# Partner page's read-only assigned-worksheets card previews this many,
# newest first — no full paged archive exists for this list yet.
_ASSIGNMENTS_PREVIEW_SIZE = 7

@volunteer_bp.before_request
@login_required
def limit_to_volunteers():
    if current_user.user_type != "volunteer":
        abort(403)

@volunteer_bp.route("/")
@match_required(completed_survey=True, redirect_to="volunteer.volunteer_survey")
def volunteer_dashboard():
    volunteer = current_user
    capture_event(str(current_user.id), "dashboard_viewed", properties={"role": "volunteer"})
    matched_learners = list(volunteer.learner_matches)

    partners = []
    if matched_learners:
        total_topics = db.session.scalar(
            db.select(db.func.count())
            .select_from(Topic)
            .join(Subject, Topic.subject_id == Subject.id)
            .where(Subject.map_test_only == False)
        )
        for learner in matched_learners:
            snapshot = get_pair_learning_snapshot(learner)
            partners.append({
                "learner": learner,
                "current_subject": snapshot["subject"],
                "completed_count": len(learner.completed_topic_ids or []),
                "total_topics": total_topics,
                "progress_percentage": snapshot["progress"],
            })

    context = {
        "volunteer": volunteer,
        "partners": partners,
        # First partner drives the single-value stat tiles at the top.
        "matched_learner": matched_learners[0] if matched_learners else None,
        "pending_announcement": get_pending_announcement(volunteer),
    }

    return render_template("@pages/volunteer/dashboard.jx", **context)

@volunteer_bp.route("/my-partner")
@match_required(completed_survey=True, redirect_to="volunteer.volunteer_survey")
def volunteer_my_partner():
    volunteer = current_user
    partners = list(volunteer.learner_matches)
    # ?learner=<id> picks which partner to show when the volunteer holds several.
    selected_id = request.args.get("learner", type=int)
    learner = next((l for l in partners if l.id == selected_id), None) if selected_id else None
    if learner is None:
        learner = partners[0] if partners else None
    capture_event(
        str(current_user.id),
        "page_viewed",
        properties={"page": "volunteer_my_partner", "partner_count": len(partners)},
    )

    if not learner:
        return render_template("@pages/volunteer/my_partner.jx", learner=None, partners=[])

    # Fetch all subjects with their topics
    subjects = db.session.scalars(db.select(Subject)).all()

    completed_lesson_ids = list(learner.completed_lesson_ids or [])
    assignment_stmt = db.select(WorksheetAssignment).filter_by(learner_id=learner.id)
    assignment_total = db.session.scalar(
        db.select(db.func.count()).select_from(assignment_stmt.subquery())
    )
    assigned_worksheets = db.session.scalars(
        assignment_stmt.order_by(WorksheetAssignment.assigned_at.desc())
        .limit(_ASSIGNMENTS_PREVIEW_SIZE)
    ).all()
    context = {
        "learner": learner,
        "partners": partners,
        "completed_topics": list(learner.completed_topic_ids or []),
        "completed_lessons": completed_lesson_ids,
        "subjects": subjects,
        "completed_lesson_objs": db.session.scalars(
            db.select(Lesson).where(Lesson.id.in_(completed_lesson_ids))
        ).all() if completed_lesson_ids else [],
        "assigned_worksheets": assigned_worksheets,
        "assignment_total": assignment_total,
    }
    
    return render_template("@pages/volunteer/my_partner.jx", **context)

@volunteer_bp.route("/profile")
@match_required(completed_survey=True, redirect_to="volunteer.volunteer_survey")
def volunteer_profile():
    capture_event(str(current_user.id), "page_viewed", properties={"page": "volunteer_profile"})
    return render_template("@pages/volunteer/profile.jx", volunteer=current_user)

@volunteer_bp.route("/resources")
@match_required(completed_survey=True, redirect_to="volunteer.volunteer_survey")
def volunteer_resources():
    """Browse the worksheet library, load-more at `WORKSHEETS_LIBRARY_PAGE_SIZE`
    and filtered server-side by `?subject=`, `?level=` and `?q=`. `wants_fragment()` (the
    load-more/search fetch) returns just the next batch of cards."""
    selected_subject = request.args.get("subject", "").strip()
    q = request.args.get("q", "").strip()
    selected_level = requested_level()
    batch = library_batch(selected_subject, q, requested_page(), level=selected_level)
    track_library_view(current_user.id, "volunteer_resources", q, batch, level=selected_level)

    if wants_fragment():
        return library_fragment("@page_components/volunteer/worksheet_cards.jx", batch)
    return render_template(
        "@pages/volunteer/resources.jx",
        worksheets=batch.worksheets,
        subjects=library_subjects(),
        levels=library_levels(),
        selected_level=selected_level,
        selected_subject=selected_subject,
        q=q,
        endpoint="volunteer.volunteer_resources",
        has_more=batch.has_more,
        total_worksheets=batch.total,
    )

@volunteer_bp.route("/worksheets/<int:worksheet_id>")
@match_required(completed_survey=True, redirect_to="volunteer.volunteer_survey")
def volunteer_worksheet_preview(worksheet_id):
    worksheet = db.session.get(Worksheet, worksheet_id)
    if not worksheet: abort(404)
    capture_event(
        str(current_user.id),
        "page_viewed",
        properties={"page": "volunteer_worksheet_preview", "worksheet_id": worksheet_id},
    )
    return render_template(
        "@pages/volunteer/worksheet_preview.jx",
        worksheet=worksheet,
        worksheet_html=render_worksheet_html(worksheet),
    )

@volunteer_bp.route("/worksheets/<int:worksheet_id>/file")
@match_required(completed_survey=True, redirect_to="volunteer.volunteer_survey")
def volunteer_worksheet_file(worksheet_id):
    from helpers.storage import get_bucket
    worksheet = db.session.get(Worksheet, worksheet_id)
    if not worksheet or worksheet.file_type != "pdf":
        abort(404)
    if not worksheet.filepath:
        abort(404)
    storage = get_bucket()
    if not storage.exists(worksheet.filepath):
        abort(404)
    return storage.send(worksheet.filepath, "application/pdf")

@volunteer_bp.route("/survey", methods=["GET", "POST"])
@match_required(redirect_to="volunteer.volunteer_dashboard")
def volunteer_survey():
    if request.method == "POST":
        languages = [l for l in request.form.getlist("languages") if l != "None"]
        languages_data = [{"language": l, "level": request.form.get(f"language_level_{l}")} for l in languages]

        clean_data = {
            "name": request.form.get("name") if not current_user.completed_survey else current_user.name,
            "age": request.form.get("age"),
            "personality": request.form.get("personality"),
            "traits": request.form.getlist("traits"),
            "hobbies": request.form.getlist("hobbies"),
            "languages": languages_data,
            "match_activities": request.form.getlist("match_activities"),
            "tech_interest": request.form.getlist("tech_interest"),
        }
        current_user.name = clean_data["name"]
        current_user.completed_survey = True
        current_user.survey_data = clean_data
        db.session.commit()
        capture_event(str(current_user.id), "volunteer_survey_completed", properties={})
        return redirect(url_for("volunteer.volunteer_dashboard"))

    survey_data = current_user.survey_data or {}
    usr_languages = {l['language']: l['level'] for l in survey_data.get('languages', [])}
    survey = {
        "age": survey_data.get("age", ""),
        "personality": survey_data.get("personality"),
        "traits": survey_data.get("traits", []),
        "hobbies": survey_data.get("hobbies", []),
        "tech_interest": survey_data.get("tech_interest", []),
        "match_activities": survey_data.get("match_activities", []),
        "motivation": survey_data.get("motivation", []),
    }
    return render_template(
        "@pages/volunteer/survey.jx",
        has_completed=current_user.completed_survey,
        languages=usr_languages,
        survey=survey,
    )

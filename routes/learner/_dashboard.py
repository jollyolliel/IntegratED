from flask import redirect, request, url_for

from extensions import db
from helpers.analytics import capture_event
from helpers.announcements import get_pending_announcement
from helpers.auth_utils import match_required
from helpers.current_user import current_learner as current_user
from helpers.gamification import (
    FACE_CATEGORIES,
    FACE_ITEMS,
    FACE_LAYER_ORDER,
    FACE_UNLOCK_LEVEL,
    LEVEL_NAMES,
    items_unlocked_between,
    level_progress,
    resolve_face,
)
from helpers.learning import (
    learner_journey,
)
from helpers.render import render_template
from models import WorksheetAssignment
from routes.learner import learner_bp


@learner_bp.route("/")
def learner_dashboard():
    capture_event(str(current_user.id), "dashboard_viewed", properties={"role": "learner"})
    journey = learner_journey(current_user)
    assigned_worksheets = db.session.scalars(
        db.select(WorksheetAssignment)
        .filter_by(learner_id=current_user.id, completed=False)
        .order_by(WorksheetAssignment.assigned_at.desc())
    ).all()
    face_equipped = resolve_face(current_user.equipped_items)
    level = level_progress(current_user.xp or 0)
    current_level = level["level"]
    return render_template(
        "@pages/learner/dashboard.jx",
        snapshot=journey["snapshot"],
        topic_progress=journey["topic_progress"],
        recommended_start=journey["first_step"],
        assigned_worksheets=assigned_worksheets,
        face_equipped=face_equipped,
        face_items=FACE_ITEMS,
        face_categories=FACE_CATEGORIES,
        face_layer_order=FACE_LAYER_ORDER,
        face_unlock_level=FACE_UNLOCK_LEVEL,
        current_level=current_level,
        current_level_name=level["name"],
        level_names=LEVEL_NAMES,
        level=level,
        next_unlock_count=len(items_unlocked_between(current_level, current_level + 1)),
        pending_announcement=get_pending_announcement(current_user),
    )


@learner_bp.route("/survey", methods=["GET", "POST"])
@match_required(redirect_to="learner.learner_map_intro")
def learner_survey():
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
        completed_before = bool(current_user.completed_survey)
        current_user.name = clean_data["name"]
        current_user.completed_survey = True
        current_user.survey_data = clean_data

        db.session.commit()
        capture_event(
            str(current_user.id),
            "learner_survey_completed",
            properties={"school": current_user.school.name if current_user.school else None},
        )
        return redirect(url_for("learner.learner_map_intro")) if not completed_before else redirect(url_for("learner.learner_dashboard"))

    survey_data = current_user.survey_data or {}
    usr_languages = {l['language']: l['level'] for l in survey_data.get('languages', [])}
    survey = {
        "age": survey_data.get("age", ""),
        "personality": survey_data.get("personality"),
        "traits": survey_data.get("traits", []),
        "hobbies": survey_data.get("hobbies", []),
        "tech_interest": survey_data.get("tech_interest", []),
        "match_activities": survey_data.get("match_activities", []),
    }
    return render_template(
        "@pages/learner/survey.jx",
        has_completed=current_user.completed_survey,
        languages=usr_languages,
        survey=survey,
    )


@learner_bp.route("/map-intro")
def learner_map_intro():
    # Deferred ("I'll do this later") learners have completed_map_test=True purely
    # as a gate — they must still be able to come back and take it.
    if current_user.completed_map_test and not current_user.map_test_deferred:
        return redirect(url_for("learner.learner_dashboard"))
    if not current_user.completed_survey:
        return redirect(url_for("learner.learner_survey"))
    capture_event(str(current_user.id), "page_viewed", properties={"page": "learner_map_intro"})
    return render_template("@pages/learner/map-intro.jx")


@learner_bp.route("/map")
def learner_map():
    if current_user.completed_map_test and not current_user.map_test_deferred:
        return redirect(url_for("learner.learner_dashboard"))
    if not current_user.completed_survey:
        return redirect(url_for("learner.learner_survey"))
    capture_event(str(current_user.id), "page_viewed", properties={"page": "learner_map"})
    return render_template("@pages/learner/map.jx")

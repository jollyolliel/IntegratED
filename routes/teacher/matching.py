from flask import abort, flash, jsonify, redirect, request, url_for

from helpers import teacher_ops
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from helpers.matching import FACTORS
from helpers.refusal import refusal_message
from helpers.utils import wants_json
from routes.teacher import teacher_bp


@teacher_bp.route("/pairs/<int:learner_id>/unmatch", methods=["POST"])
def teacher_unmatch_pair(learner_id):
    teacher = current_user
    try:
        result = teacher_ops.unmatch_pair(teacher, learner_id)
    except PermissionError:
        abort(403)
    except (LookupError, ValueError):
        # "no such learner" and "not matched with anyone" are both 404 here —
        # there is no pair at this URL either way.
        abort(404)

    volunteer = result["volunteer"]
    volunteer_id = volunteer.id

    capture_event(
        str(teacher.id),
        "pair_unmatched",
        properties={
            "learner_id": learner_id,
            "volunteer_id": volunteer_id,
            "volunteer_learner_count": len(volunteer.learner_matches),
        },
    )
    if wants_json():
        return jsonify(
            success=True,
            message="Pair unmatched.",
            learner_id=learner_id,
            volunteer_id=volunteer_id,
            volunteer_learner_count=len(volunteer.learner_matches),
            volunteer_open_slots=volunteer.open_slots,
        )
    return redirect(url_for("teacher.teacher_people"))


@teacher_bp.route("/pairs/match", methods=["POST"])
def teacher_manual_match():
    """400s when the volunteer is already at `match_capacity` — capacity is
    the teacher's decision, never silently overridden here."""
    teacher = current_user
    learner_id = request.form.get("learner_id", type=int)
    volunteer_id = request.form.get("volunteer_id", type=int)

    if not learner_id or not volunteer_id:
        abort(400)

    try:
        result = teacher_ops.match_pair(teacher, learner_id, volunteer_id)
    except (LookupError, PermissionError):
        abort(403)
    except ValueError as exc:
        # Capacity is the teacher's decision — refuse rather than silently
        # evicting a learner the volunteer already has.
        message = refusal_message(exc)
        if wants_json():
            return jsonify(success=False, message=message), 400
        abort(400, description=message)

    _learner, volunteer = result["learner"], result["volunteer"]

    if result["already"]:
        if wants_json():
            return jsonify(
                success=True,
                message="Learner is already matched with this volunteer.",
                learner_id=learner_id,
                volunteer_id=volunteer_id,
                volunteer_learner_count=len(volunteer.learner_matches),
                volunteer_open_slots=volunteer.open_slots,
            )
        return redirect(url_for("teacher.teacher_learner_detail", learner_id=learner_id))

    capture_event(
        str(teacher.id),
        "pair_manually_matched",
        properties={
            "learner_id": learner_id,
            "volunteer_id": volunteer_id,
            "volunteer_learner_count": len(volunteer.learner_matches),
            "volunteer_capacity": volunteer.capacity,
        },
    )
    if wants_json():
        return jsonify(
            success=True,
            message="Learner matched with volunteer.",
            learner_id=learner_id,
            volunteer_id=volunteer_id,
            volunteer_learner_count=len(volunteer.learner_matches),
            volunteer_open_slots=volunteer.open_slots,
        )
    return redirect(url_for("teacher.teacher_learner_detail", learner_id=learner_id))


@teacher_bp.route("/match-settings", methods=["POST"])
def teacher_set_match_settings():
    """Teacher sets how much each factor counts and how hard the matcher keeps
    spreading learners across volunteers. Changes nothing on the roster — it
    decides what the next Auto-Match optimises, and what every score shown on
    the person pages means from the next render on."""
    teacher = current_user

    # A missing field is a factor the form never drew, which reads as "leave
    # it at the default" — not as a zero.
    if request.form.get("reset"):
        weights, spread = {}, None
    else:
        weights = {
            factor: request.form[f"weight_{factor}"]
            for factor in FACTORS
            if f"weight_{factor}" in request.form
        }
        spread = request.form.get("spread")

    try:
        levels = teacher_ops.set_match_settings(teacher, weights, spread)["levels"]
    except ValueError as exc:
        message = refusal_message(exc)
        if wants_json():
            return jsonify(success=False, message=message), 400
        flash(message, "error")
        return redirect(url_for("teacher.teacher_people"))

    capture_event(
        str(teacher.id),
        "match_settings_set",
        properties={"spread": levels["spread"], **{f"weight_{k}": v for k, v in levels["weights"].items()}},
    )

    message = "Matching priorities saved. They apply the next time you run Auto-Match."
    if wants_json():
        return jsonify(success=True, message=message, levels=levels)
    flash(message, "success")
    return redirect(url_for("teacher.teacher_people"))


@teacher_bp.route("/volunteers/<int:volunteer_id>/capacity", methods=["POST"])
def teacher_set_volunteer_capacity(volunteer_id):
    """Teacher sets how many learners a volunteer may hold at once, in
    range 1..`MAX_VOLUNTEER_CAPACITY`. Rejected (400) below the number of
    learners already matched to them — capacity can't drop under what's
    already committed."""
    teacher = current_user
    try:
        result = teacher_ops.set_volunteer_capacity(
            teacher, volunteer_id, request.form.get("capacity", type=int)
        )
    except (LookupError, PermissionError):
        abort(403)
    except ValueError as exc:
        message = refusal_message(exc)
        if wants_json():
            return jsonify(success=False, message=message), 400
        abort(400, description=message)

    volunteer = result["volunteer"]
    capacity = result["capacity"]
    current_count = result["learner_count"]

    capture_event(
        str(teacher.id),
        "volunteer_capacity_set",
        properties={
            "volunteer_id": volunteer_id,
            "capacity": capacity,
            "learner_count": current_count,
        },
    )
    if wants_json():
        return jsonify(
            success=True,
            message=f"Learner limit set to {capacity}.",
            volunteer_id=volunteer_id,
            volunteer_name=volunteer.name or volunteer.email.split("@")[0],
            capacity=capacity,
            volunteer_learner_count=current_count,
            volunteer_open_slots=volunteer.open_slots,
        )
    return redirect(url_for("teacher.teacher_people"))

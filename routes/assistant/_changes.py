from flask import abort, jsonify, request
from werkzeug.exceptions import Forbidden, NotFound

from helpers.ai import staging
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from helpers.refusal import refusal_message
from routes.assistant import assistant_bp


def _changes_payload(teacher):
    return [staging.change_payload(c) for c in staging.pending_changes(teacher)]


@assistant_bp.route("/changes")
def assistant_changes():
    return jsonify(changes=_changes_payload(current_user))


def _change_action(change_id, action):
    """Run `action` on one of the teacher's changes.

    Returns:
        tuple: `(change, None)` when it ran, `(None, response)` when it was refused — the
        response is a ready 400 with the refusal's message.
    """
    try:
        return action(current_user, change_id), None
    except PermissionError:
        raise Forbidden() from None
    except LookupError:
        raise NotFound() from None
    except ValueError as exc:
        return None, (jsonify(success=False, message=refusal_message(exc),
                              changes=_changes_payload(current_user)), 400)


@assistant_bp.route("/changes/<int:change_id>/apply", methods=["POST"])
def assistant_apply_change(change_id):
    result, refused = _change_action(change_id, staging.apply_change)
    if refused is not None:
        return refused

    event = "assistant_change_stale" if result.status == "stale" else "assistant_change_applied"
    capture_event(str(current_user.id), event,
                  properties={"tool": result.tool_name, "entity": result.entity})

    if result.status == "stale":
        return jsonify(
            success=False,
            status="stale",
            message="That record changed after I proposed this, so I left it alone.",
            changes=_changes_payload(current_user),
        ), 409

    return jsonify(success=True, status=result.status, message=result.summary,
                   changes=_changes_payload(current_user))


@assistant_bp.route("/changes/<int:change_id>/reject", methods=["POST"])
def assistant_reject_change(change_id):
    result, refused = _change_action(change_id, staging.reject_change)
    if refused is not None:
        return refused
    capture_event(str(current_user.id), "assistant_change_rejected",
                  properties={"tool": result.tool_name, "entity": result.entity})
    return jsonify(success=True, message="Skipped.",
                   changes=_changes_payload(current_user))


@assistant_bp.route("/changes/<int:change_id>/update", methods=["POST"])
def assistant_update_change(change_id):
    payload = request.get_json(silent=True) or {}
    values = payload.get("values")
    if not isinstance(values, dict) or not values:
        return jsonify(success=False, message="Nothing to change."), 400
    try:
        staging.update_change(current_user, change_id, values)
    except PermissionError:
        abort(403)
    except LookupError:
        abort(404)
    except (ValueError, TypeError) as exc:
        return jsonify(success=False, message=refusal_message(exc)), 400
    return jsonify(success=True, message="Updated.",
                   changes=_changes_payload(current_user))


@assistant_bp.route("/changes/apply-all", methods=["POST"])
def assistant_apply_all():
    results = staging.apply_all(current_user)
    applied = sum(1 for r in results if r["status"] == "applied")
    for result in results:
        capture_event(
            str(current_user.id),
            "assistant_change_stale" if result["status"] == "stale" else "assistant_change_applied",
            properties={"change_id": result["id"], "status": result["status"]},
        )
    return jsonify(
        success=True,
        applied=applied,
        results=results,
        changes=_changes_payload(current_user),
    )

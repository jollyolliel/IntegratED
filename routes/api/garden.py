import re

from flask import jsonify, request
from sqlalchemy.orm.attributes import flag_modified

from extensions import db
from helpers.analytics import capture_event
from helpers.current_user import current_learner as current_user
from helpers.gamification import (
    FACE_REQUIRED_SLOTS,
    FACE_UNLOCK_LEVEL,
    compute_level,
    get_face_item_type,
    resolve_face,
)
from helpers.learning import GARDEN_PLOTS
from models import Learner
from routes.api import learner_api


@learner_api.route("/garden", methods=["GET", "POST"])
def api_garden():
    """Persistent Garden Grow state on the learner. GET returns it, POST
    replaces it after validating the shape (8 stages 0-3, 8 colors)."""

    if request.method == "GET":
        return jsonify({"garden": current_user.garden_state or {}})

    data = request.get_json(silent=True)
    g = data.get("garden") if isinstance(data, dict) else None
    if not isinstance(g, dict):
        return jsonify({"error": "Invalid garden shape"}), 400
    stages = g.get("stages")
    colors = g.get("colors")
    if not isinstance(stages, list) or not isinstance(colors, list) \
            or len(stages) != GARDEN_PLOTS or len(colors) != GARDEN_PLOTS:
        return jsonify({"error": "Invalid garden shape"}), 400
    try:
        clean_stages = [min(3, max(0, int(s))) for s in stages]
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid garden stages"}), 400
    clean_colors = [
        c if isinstance(c, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else None
        for c in colors
    ]

    learner = db.session.scalar(
        db.select(Learner).filter_by(id=current_user.id).with_for_update()
    )
    if learner is None:
        return jsonify({"error": "Learner not found"}), 404
    learner.garden_state = {"stages": clean_stages, "colors": clean_colors}
    db.session.commit()
    return jsonify({"status": "success", "garden": learner.garden_state})


@learner_api.route("/equip-item", methods=["POST"])
def api_equip_item():
    """Toggle one Face System item on the learner. A FACE_REQUIRED_SLOTS slot (species, the outfit,
    its colour) can never be unequipped — picking the worn item again just re-equips it. Answers
    with the whole face as `resolve_face` reads it, the same face the dashboard draws."""
    data = request.get_json() or {}
    item_id = str(data.get("item_id") or "").strip()
    if not item_id:
        return jsonify({"error": "item_id required"}), 400

    item_type = get_face_item_type(item_id)
    if item_type is None:
        return jsonify({"error": "Unknown item"}), 404

    learner = current_user
    required_level = FACE_UNLOCK_LEVEL.get(item_id, 1)
    if compute_level(learner.xp or 0) < required_level:
        return jsonify({"error": f"Requires Level {required_level}"}), 403

    face = resolve_face(learner.equipped_items)
    if item_type in FACE_REQUIRED_SLOTS or face.get(item_type) != item_id:
        face[item_type], action = item_id, "equipped"
    else:
        face[item_type], action = None, "unequipped"
    learner.equipped_items = face
    flag_modified(learner, "equipped_items")
    db.session.commit()

    capture_event(str(current_user.id), "item_" + action, {
        "item_id": item_id,
        "item_type": item_type,
    })

    return jsonify({"status": "ok", "equipped": face, "action": action})

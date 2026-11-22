from flask import jsonify
from flask_login import login_required

from extensions import db
from helpers.analytics import capture_event
from helpers.current_user import current_user
from models import FeatureAnnouncement
from routes.api import api_bp


@api_bp.route("/announcements/<int:announcement_id>/dismiss", methods=["POST"])
@login_required
def dismiss_announcement(announcement_id):
    """Mark the popup the user just acted on as seen.

    Called on close, backdrop click, secondary button and CTA click — never on
    mere render, so an announcement keeps reappearing until the user acts on it.
    Stores a high-water mark, so this also catches the user up past any older
    unseen announcement (by design — only the newest ever shows).
    """
    announcement = db.session.get(FeatureAnnouncement, announcement_id)
    if announcement is None:
        return jsonify({"error": "Unknown announcement."}), 404

    # Monotonic: dismissing an older announcement must never re-expose newer ones.
    previous = current_user.last_seen_announcement_id or 0
    current_user.last_seen_announcement_id = max(previous, announcement.id)
    db.session.commit()

    capture_event(
        str(current_user.id),
        "announcement_dismissed",
        properties={
            "announcement_uid": announcement.uid,
            "role": current_user.user_type,
        },
    )
    return jsonify({"status": "ok", "last_seen_announcement_id": current_user.last_seen_announcement_id})

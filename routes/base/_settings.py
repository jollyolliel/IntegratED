from flask import flash, redirect, request, url_for
from flask_login import login_required, logout_user

from extensions import db
from helpers import roster_ops
from helpers.analytics import capture_event
from helpers.auth_utils import (
    clean_credential,
    has_whitespace,
    password_matches,
    username_taken,
)
from helpers.current_user import current_user
from helpers.render import render_template
from models import User
from routes.base import base_bp


@base_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Account settings — one form, three actions dispatched by
    `request.form["action"]`: update_profile, change_password, delete_account.

    Password changes are unavailable for Volunteer/Teacher (Google-only
    accounts). Self-deletion goes through `roster_ops.delete_user`, the same
    cascade every other delete uses: one transaction, and an administrator's
    articles pass to the longest-serving other administrator. Deleting the last
    administrator is refused before anything changes.
    """
    from routes.auth import is_password_strong

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_profile":
            name = request.form.get("name", "").strip()
            current_user.name = name or None

            if current_user.user_type in ("learner", "administrator", "school_admin"):
                new_username = clean_credential(request.form.get("username"))
                if has_whitespace(new_username):
                    flash("Username cannot contain spaces.", "error")
                    return redirect(url_for("base.settings"))
                if new_username and new_username != getattr(current_user, "username", None):
                    if username_taken(new_username, exclude_id=current_user.id):
                        flash("Username already taken.", "error")
                        return redirect(url_for("base.settings"))
                    current_user.username = new_username

            db.session.commit()
            capture_event(str(current_user.id), "settings_profile_updated", properties={"role": current_user.user_type})
            flash("Profile updated successfully.", "success")
            return redirect(url_for("base.settings"))

        elif action == "change_password":
            if current_user.user_type not in ("learner", "administrator", "school_admin"):
                flash("Password changes not available for Google-authenticated accounts.", "error")
                return redirect(url_for("base.settings"))

            current_pw = request.form.get("current_password", "")
            new_pw = clean_credential(request.form.get("new_password"))
            confirm_pw = clean_credential(request.form.get("confirm_password"))

            if not password_matches(current_user, current_pw):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("base.settings"))

            if new_pw != confirm_pw:
                flash("New passwords do not match.", "error")
                return redirect(url_for("base.settings"))

            if has_whitespace(new_pw):
                flash("Password cannot contain spaces.", "error")
                return redirect(url_for("base.settings"))

            if not is_password_strong(new_pw):
                flash("Password must be at least 8 characters with uppercase and lowercase.", "error")
                return redirect(url_for("base.settings"))

            current_user.set_password(new_pw)
            db.session.commit()
            capture_event(str(current_user.id), "settings_password_changed", properties={"role": current_user.user_type})
            flash("Password changed successfully.", "success")
            return redirect(url_for("base.settings"))

        elif action == "delete_account":
            confirm_text = request.form.get("confirm_delete", "")
            if confirm_text != "DELETE":
                flash("Type DELETE exactly to confirm deletion.", "error")
                return redirect(url_for("base.settings"))

            user_id = str(current_user.id)
            user_type = current_user.user_type
            user_obj = db.get_or_404(User, current_user.id)
            try:
                roster_ops.delete_user(user_obj)
            except roster_ops.LastAdministratorError as error:
                flash(str(error), "error")
                return redirect(url_for("base.settings"))

            capture_event(user_id, "settings_account_deleted", properties={"role": user_type})
            logout_user()
            flash("Your account has been deleted.", "info")
            return redirect(url_for("base.home"))

    capture_event(str(current_user.id) if current_user.is_authenticated else None, "page_viewed", properties={"page": "settings"})
    return render_template("@pages/settings.jx")

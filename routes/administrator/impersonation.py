from flask import flash, redirect, session, url_for
from flask_login import login_required, login_user

from extensions import db
from helpers.auth_utils import dashboard_url
from helpers.current_user import current_administrator as current_user
from models import Administrator, User
from routes.administrator import admin_required, administrator_bp


@administrator_bp.route("/impersonate/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def impersonate(user_id):
    """Log in as another non-admin user without their password, for
    support/debugging. `session["impersonating_admin_id"]` records who's
    really behind the wheel; `impersonate_stop` reads it to log back in."""
    target = db.get_or_404(User, user_id)
    if target.user_type == "administrator":
        flash("Cannot impersonate another administrator.", "error")
        return redirect(url_for("administrator.users"))

    session["impersonating_admin_id"] = current_user.id
    login_user(target)
    flash(
        f"Now impersonating {target.name or str(target.id)} ({target.user_type}). "
        "Click 'Stop Impersonating' in the banner to return.",
        "warning",
    )

    return redirect(dashboard_url(target))

@administrator_bp.route("/impersonate/stop")
def impersonate_stop():
    """Exit impersonation and return to the admin session. No
    `@login_required`/`@admin_required` deliberately — safety comes from
    `session.pop` instead, gated on `impersonating_admin_id`."""
    admin_id = session.pop("impersonating_admin_id", None)
    if admin_id:
        admin = db.session.get(Administrator, admin_id)
        if admin:
            login_user(admin)
            flash("Returned to admin session.", "success")
            return redirect(url_for("administrator.dashboard"))
    return redirect(url_for("base.home"))

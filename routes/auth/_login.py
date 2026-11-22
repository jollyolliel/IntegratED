from flask import flash, redirect, request, session, url_for
from flask_login import logout_user

from extensions import limiter
from helpers.analytics import capture_event
from helpers.auth_utils import (
    clean_credential,
    dashboard_url,
    find_by_username,
    password_matches,
    sign_in,
)
from helpers.current_user import current_user
from helpers.render import render_template
from routes.auth import auth_bp


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    """Password login for Learner, Administrator and SchoolAdmin. Teachers and
    volunteers are Google OAuth-only (see authorize()) and hold no username, so
    `find_by_username` never returns one.
    `find_by_username` tries each role in turn since usernames aren't unique
    across tables; stricter 10/min limit (vs. the blueprint's 20/min) is a brute-force
    guard on the password check itself. Whitespace around either credential is
    ignored (`clean_credential`, issue #176).
    """
    if request.method == "POST":
        username = clean_credential(request.form.get("username"))
        password = request.form.get("password") or ""

        db_user = find_by_username(username)

        if db_user is None or not password_matches(db_user, password):
            flash(
                "Wrong username or password. Teachers and volunteers: use Sign in with Google.",
                "error",
            )
            capture_event(
                None,
                "auth_login_failed",
                properties={"reason": "invalid_credentials", "method": "password"},
            )
            return redirect(url_for("auth.login"))

        sign_in(db_user)
        capture_event(
            str(db_user.id),
            "auth_login_succeeded",
            properties={
                "method": "password",
                "role": db_user.user_type,
                "whitespace_trimmed": password != clean_credential(password),
            },
        )

        return redirect(dashboard_url(db_user))

    return render_template("@pages/login.jx")


@auth_bp.route("/logout")
def logout():
    """Clears session keys the login/impersonation flows can set, on top of
    flask-login's own logout_user()."""
    user_id = str(current_user.id) if current_user.is_authenticated else None
    if user_id:
        capture_event(user_id, "auth_logout", properties={"role": current_user.user_type})

    session.pop("user_email", None)
    session.pop("user_type", None)
    session.pop("impersonating_admin_id", None)
    logout_user()
    return redirect(url_for("base.home"))

from datetime import UTC, datetime

from flask import flash, jsonify, redirect, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError

from extensions import db, limiter
from helpers.analytics import capture_event, capture_exception
from helpers.auth_utils import (
    clean_credential,
    has_whitespace,
    sign_in,
    username_taken,
    validate_invite_code,
)
from helpers.render import render_template
from models import Learner
from routes.auth import auth_bp


def is_password_strong(password):
    password = str(password)
    if len(password) < 8: return False
    if not any(c.isupper() for c in password): return False
    return any(c.islower() for c in password)


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def register():
    """Password-based Learner signup — the only role created here; Volunteer
    and Teacher signup both go through Google OAuth (see authorize()).
    Requires a valid invite code, re-validated here even though
    the registration wizard already ran the same check via
    /validate-invite — that endpoint is a pre-check only and doesn't reserve
    or consume the code, so it must be checked again at the point of actual
    account creation.
    """
    if request.method == "POST":
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        username = clean_credential(data.get("username"))
        password = clean_credential(data.get("password"))
        invite_code = data.get("invite_code", "")

        if not username or not password:
            return jsonify({"status": "error", "message": "Username and password are required"}), 400

        if has_whitespace(username) or has_whitespace(password):
            capture_event(
                None,
                "auth_signup_failed",
                properties={"reason": "whitespace_in_credentials", "method": "password"},
            )
            return jsonify({"status": "error", "message": "Username and password cannot contain spaces"}), 400

        school = validate_invite_code(invite_code)
        if not school:
            capture_event(
                None,
                "auth_signup_failed",
                properties={"reason": "invalid_invite_code", "method": "password"},
            )
            return jsonify({"status": "error", "message": "Invalid invite code"}), 400

        try:
            exists = username_taken(username)
        except SQLAlchemyError as e:
            capture_exception(None, e, {"context": "register_query"})
            return jsonify({"status": "error", "message": "Database error during registration check"}), 500

        if exists:
            capture_event(
                None,
                "auth_signup_failed",
                properties={"reason": "user_already_exists", "method": "password"},
            )
            return jsonify({"status": "error", "message": "User already exists"}), 400

        if not is_password_strong(password):
            capture_event(
                None,
                "auth_signup_failed",
                properties={"reason": "password_weak", "method": "password"},
            )
            return jsonify({"status": "error", "message": "Password must be at least 8 characters with at least 1 uppercase and 1 lowercase letter."}), 400

        try:
            new_user = Learner(username=username, school_id=school.id)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            capture_exception(None, e, {"context": "register_commit"})
            return jsonify({"status": "error", "message": "Database error during user creation"}), 500

        sign_in(new_user)

        capture_event(
            str(new_user.id),
            "auth_signup_succeeded",
            properties={
                "method": "password",
                "role": "learner",
                "$set": {
                    "username": username,
                    "user_type": "learner",
                    "signup_date": datetime.now(UTC).isoformat()
                }
            },
        )
        return redirect(url_for("learner.learner_survey"))
    elif request.method == "GET":
        return render_template("@pages/register.jx")
    else:
        return jsonify({"status": "error", "message": "Method not allowed"}), 405


@auth_bp.route("/validate-invite", methods=["POST"])
@limiter.limit("10 per minute")
def validate_invite():
    """Lightweight invite-code check used by the registration wizard before
    role selection. Returns the school name."""
    data = request.get_json(silent=True) or {}
    code = (data.get("invite_code") or "").upper().strip()
    if not code:
        return jsonify({"valid": False, "message": "Invite code required"}), 400

    school = validate_invite_code(code)
    if not school:
        capture_event(
            None,
            "auth_invite_check_failed",
            properties={"reason": "invalid_invite_code"},
        )
        return jsonify({"valid": False, "message": "Invalid invite code"}), 200

    return jsonify({"valid": True, "school": school.name, "code": code}), 200


@auth_bp.route("/start-volunteer-register", methods=["POST"])
def start_volunteer_register():
    """Validate the invite code, then stash it in the session for
    `authorize()` to read back after the OAuth redirect."""
    code = request.form.get("invite_code", "").upper().strip()
    if not validate_invite_code(code):
        flash("Invalid invite code.", "error")
        return redirect(url_for("auth.register") + "?role=volunteer")
    session["pending_invite_code"] = code
    return redirect(url_for("auth.login_google"))

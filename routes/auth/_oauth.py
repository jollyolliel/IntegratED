"""Google sign-in for teachers and volunteers.

`/authorize` is Google's callback. On a local development server the Google button opens
`/dev/google-sign-in` instead: a form that takes the email Google would have returned and feeds it
to the same account logic, so domain matching, invite codes and the gmail.com case can be tried as
any address without Google credentials (with credentials it also links to real Google via
`/login/google?real=1`). That page 404s outside development and to any
non-loopback client (`is_local_dev_request`), like /dev/login-as. No PostHog events of its own and
no translation keys: it is a developer tool.
"""

import secrets
from collections.abc import Mapping
from typing import Any

from flask import abort, current_app, flash, redirect, request, session, url_for
from flask.typing import ResponseReturnValue

from extensions import db, oauth
from helpers.analytics import capture_event, capture_exception
from helpers.auth_utils import (
    dashboard_url,
    get_or_create_invite_code,
    is_local_dev_request,
    sign_in,
    validate_invite_code,
)
from helpers.render import render_template
from models import School, Teacher, Volunteer
from routes.auth import auth_bp
from settings import get_settings


def _google() -> Any:
    """The Google OAuth client `create_app` registered (Authlib's clients are untyped)."""
    return oauth.create_client("google")


@auth_bp.route("/login/google")
def login_google():
    """Kick off Google OAuth (the client `create_app` registers on `oauth`), or open the
    dev stand-in on a local development server. `?real=1` (the dev page's "Sign in with real
    Google" button) skips the stand-in when Google credentials are configured."""
    if is_local_dev_request():
        if not request.args.get("real"):
            return redirect(url_for("auth.dev_google_sign_in"))
        if not _google_configured():
            flash("No Google credentials are set (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env).", "error")
            return redirect(url_for("auth.dev_google_sign_in"))
    redirect_uri = url_for("auth.authorize", _external=True)
    return _google().authorize_redirect(redirect_uri)


@auth_bp.route("/authorize")
def authorize():
    """Google OAuth callback: hand Google's `userinfo` to `_sign_in_with_google_account`."""
    if not _google_configured():
        abort(404)
    try:
        token = _google().authorize_access_token()
        return _sign_in_with_google_account(token.get("userinfo", {}))
    except Exception as e:
        current_app.logger.exception("OAuth Authorization Error")
        return _sign_in_failed(e)


@auth_bp.route("/dev/google-sign-in", methods=["GET", "POST"])
def dev_google_sign_in():
    """Dev-only stand-in for Google: sign in or register as whichever email is typed, through
    the same path as `/authorize`. The session (with any `pending_invite_code`) is the browser's
    own, so the volunteer registration wizard works end to end."""
    if not is_local_dev_request():
        abort(404)
    if request.method == "GET":
        return render_template("@pages/dev/google_sign_in.jx", google_configured=_google_configured())
    preset = request.form.get("preset")
    if preset in _DEV_PRESETS:
        email, name = _new_dev_account(preset)
        if not email:
            flash(f"No school has a {_DEV_PRESETS[preset]} domain to register a {preset} under.", "error")
            return redirect(url_for("auth.dev_google_sign_in"))
    else:
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip() or email.split("@")[0]
    user_info = {"email": email, "name": name, "picture": "", "sub": f"dev-{email}"} if email else {}
    try:
        return _sign_in_with_google_account(user_info)
    except Exception as e:
        current_app.logger.exception("OAuth Authorization Error")
        return _sign_in_failed(e)
    finally:
        if preset in _DEV_PRESETS:
            session.pop("pending_invite_code", None)  # a preset's code is for this click only


def _google_configured() -> bool:
    """Whether Google credentials are set (always in production; optional in development)."""
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


#: The dev page's one-click presets and the School column each one registers under.
_DEV_PRESETS = {"teacher": "teacher_domain", "volunteer": "volunteer_domain"}


def _new_dev_account(preset: str) -> tuple[str, str]:
    """A fresh, valid email and name for the `teacher` or `volunteer` preset; `("", "")` if no
    school can take one. A volunteer also needs the school's invite code in the session, which
    `/start-volunteer-register` stashes for the real flow."""
    column = getattr(School, _DEV_PRESETS[preset])
    school = db.session.scalar(db.select(School).where(column.is_not(None), column != "").order_by(School.id))
    if school is None and preset == "teacher":
        domain = "gmail.com"  # an unaffiliated teacher, as for any personal address
    elif school is None:
        return "", ""
    else:
        domain = getattr(school, _DEV_PRESETS[preset])
        if preset == "volunteer":
            session["pending_invite_code"] = get_or_create_invite_code(school)
    tag = secrets.token_hex(3)
    return f"dev-{preset}-{tag}@{domain}", f"Dev {preset.title()} {tag}"


def _sign_in_failed(error: Exception) -> ResponseReturnValue:
    """Report an unexpected sign-in error (the caller logs it) and send the browser back to login."""
    capture_exception(None, error, {"context": "google_authorize"})
    flash("An error occurred during login. Please contact support.", "error")
    return redirect(url_for("auth.login"))


def _sign_in_with_google_account(user_info: Mapping[str, str]) -> ResponseReturnValue:
    """Log in an existing Volunteer/Teacher by the email Google vouched for,
    or create one, with role decided by email domain — never by anything the
    client asserts.

    - `gmail.com` is a hard-coded escape hatch: creates an unaffiliated
      Teacher (no school_id), since a personal Gmail address can't be
      matched to any school's domain.
    - Otherwise the domain must match a School's `volunteer_domain` or
      `teacher_domain`. A `volunteer_domain` match additionally requires a
      valid invite code in `session["pending_invite_code"]` (stashed by
      start_volunteer_register before the OAuth redirect) — OAuth alone is
      not sufficient to become a Volunteer, since that role also seeds
      `teacher_id`/`match_capacity` from the invite's owning teacher. A
      `teacher_domain` match needs no invite code; teachers self-register by
      domain alone.
    - An existing Volunteer/Teacher row (matched by email) always logs in
      as-is regardless of any pending invite code — the code only matters
      for account *creation*, never for login.
    """
    user_email = user_info.get("email")
    if not user_email:
        flash("Google authorization missing email. Please try again.", "error")
        return redirect(url_for("auth.login"))

    user_name = user_info.get("name", "Unknown User")
    user_picture = user_info.get("picture", "")

    user = db.session.scalar(db.select(Volunteer).filter_by(email=user_email)) or \
           db.session.scalar(db.select(Teacher).filter_by(email=user_email))

    if not user:
        domain = user_email.split("@")[-1]

        # Gmail special case: unaffiliated teacher
        if domain == "gmail.com":
            user = Teacher(
                google_sub=user_info.get("sub", ""),
                name=user_name,
                email=user_email,
                user_picture=user_picture,
                school_id=None
            )
            db.session.add(user)
            db.session.commit()
            sign_in(user)
            capture_event(
                str(user.id),
                "auth_signup_succeeded",
                properties={
                    "method": "google",
                    "role": "teacher",
                    "school": None,
                    "$set": {"email": user_email, "name": user_name, "user_type": "teacher"}
                },
            )
            return redirect(url_for("teacher.teacher_dashboard"))

        # DB-driven domain lookup
        school = db.session.scalar(
            db.select(School).where(
                (School.volunteer_domain == domain) | (School.teacher_domain == domain)
            )
        )

        if not school:
            capture_event(
                None,
                "auth_signup_failed",
                properties={"method": "google", "reason": "unauthorized_domain", "domain": domain},
            )
            flash(
                f"{user_email} isn't a school account we recognise. Use your school Google "
                "account, or ask your teacher for help.",
                "error",
            )
            return redirect(url_for("auth.login"))

        if school.volunteer_domain == domain:
            pending_code = session.pop("pending_invite_code", None)
            code_school = validate_invite_code(pending_code) if pending_code else None
            if not code_school or code_school.id != school.id:
                capture_event(
                    None,
                    "auth_signup_failed",
                    properties={
                        "method": "google",
                        "reason": "invalid_invite_code" if pending_code else "missing_invite_code",
                        "domain": domain,
                    },
                )
                if pending_code:
                    flash("Invalid invite code. Please try again.", "error")
                else:
                    flash(
                        "Welcome! To join as a volunteer, first enter the invite code "
                        "your teacher gave you.",
                        "info",
                    )
                return redirect(url_for("auth.register") + "?role=volunteer")
            teacher = db.session.scalar(db.select(Teacher).filter_by(school_id=school.id))
            user = Volunteer(
                google_sub=user_info.get("sub", ""),
                name=user_name,
                email=user_email,
                user_picture=user_picture,
                school_id=school.id,
                teacher_id=teacher.id if teacher else None,
                # The teacher's standing default, not a hard-coded 1 — a
                # teacher who runs 3-learner volunteers sets it once.
                match_capacity=teacher.default_match_capacity if teacher else 1,
            )
            db.session.add(user)
            db.session.commit()
            sign_in(user)
            capture_event(
                str(user.id),
                "auth_signup_succeeded",
                properties={
                    "method": "google",
                    "role": "volunteer",
                    "school": school.name,
                    "$set": {"email": user_email, "name": user_name, "user_type": "volunteer"}
                },
            )
            return redirect(url_for("volunteer.volunteer_survey"))
        else:
            user = Teacher(
                google_sub=user_info.get("sub", ""),
                name=user_name,
                email=user_email,
                user_picture=user_picture,
                school_id=school.id
            )
            db.session.add(user)
            db.session.commit()
            sign_in(user)
            capture_event(
                str(user.id),
                "auth_signup_succeeded",
                properties={
                    "method": "google",
                    "role": "teacher",
                    "school": school.name,
                    "$set": {"email": user_email, "name": user_name, "user_type": "teacher"}
                },
            )
            return redirect(url_for("teacher.teacher_dashboard"))
    else:
        sign_in(user)
        capture_event(
            str(user.id),
            "auth_login_succeeded",
            properties={
                "method": "google",
                "role": user.user_type,
                "$set": {"name": user_name, "user_picture": user_picture}
            },
        )
        return redirect(dashboard_url(user))

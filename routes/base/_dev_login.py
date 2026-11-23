"""Dev-only `/dev/login-as`: sign this browser in as any user, no password, so a browser-driven
check (Claude in Chrome) can switch role with one navigation instead of copying cookies.

  /dev/login-as                     JSON of up to 10 users per role, each with its login URL
  /dev/login-as?id=<user id>        sign in as that user
  /dev/login-as?type=<user_type>    sign in as the oldest user of that role, creating one if none
  /dev/login-as?type=...&new=1      always create a fresh user of that role
  &next=/learner/map                land there instead of the role's dashboard; the full path,
                                    blueprint prefix included (/map alone is a 404)
  &survey=0|1                       set completed_survey (learner, volunteer)
  &map_test=0|1|deferred            not taken / completed / "do it later" (learner); 0 and
                                    deferred also clear subject_levels
Applied to an existing user too, so `?type=learner&map_test=0` resets the oldest learner.

404 outside development and to any non-loopback client, so a dev server bound to 0.0.0.0 on a shared
network does not hand out logins. No PostHog events and no translation keys: it is a developer tool."""

from __future__ import annotations

import secrets

from flask import abort, jsonify, redirect, request
from sqlalchemy import select

from extensions import db
from helpers.auth_utils import dashboard_url, is_local_dev_request, sign_in
from helpers.utils import safe_local_path
from models import Administrator, Learner, School, SchoolAdmin, Teacher, User, Volunteer
from routes.base import base_bp

DEV_PASSWORD = "password"

MODELS: dict[str, type[User]] = {
    "learner": Learner,
    "volunteer": Volunteer,
    "teacher": Teacher,
    "school_admin": SchoolAdmin,
    "administrator": Administrator,
}


def _new_school() -> School:
    school = School(name=f"Dev School {secrets.token_hex(3)}")
    db.session.add(school)
    db.session.flush()
    return school


def _dev_school() -> School:
    """The oldest school, or a new one on an empty database."""
    return db.session.scalars(select(School).order_by(School.id)).first() or _new_school()


def _school_teacher(school: School) -> Teacher | None:
    return db.session.scalars(
        select(Teacher).where(Teacher.school_id == school.id).order_by(Teacher.id)
    ).first()


def _create(user_type: str) -> User:
    """A ready-to-use user of `user_type`: onboarding done, attached to the dev school (and its
    first teacher, for learners/volunteers). Password-based roles get `DEV_PASSWORD`."""
    tag = secrets.token_hex(3)
    name = f"Dev {user_type.replace('_', ' ').title()} {tag}"
    user: User
    if user_type == "learner":
        school = _dev_school()
        teacher = _school_teacher(school)
        learner = Learner(
            username=f"dev-learner-{tag}", name=name, school_id=school.id,
            teacher_id=teacher.id if teacher else None,
            completed_survey=True, completed_map_test=True,
        )
        learner.set_password(DEV_PASSWORD)
        user = learner
    elif user_type in ("volunteer", "teacher"):
        school = _dev_school()
        email = f"dev-{user_type}-{tag}@example.com"
        if user_type == "volunteer":
            teacher = _school_teacher(school)
            user = Volunteer(
                email=email, google_sub=f"dev-{tag}", name=name, school_id=school.id,
                teacher_id=teacher.id if teacher else None, completed_survey=True,
            )
        else:
            user = Teacher(email=email, google_sub=f"dev-{tag}", name=name, school_id=school.id)
    elif user_type == "school_admin":
        # One admin per school (`School.school_admin` is uselist=False).
        school = db.session.scalars(
            select(School).where(~School.school_admin.has()).order_by(School.id)
        ).first() or _new_school()
        school_admin = SchoolAdmin(username=f"dev-schooladmin-{tag}", name=name, school_id=school.id)
        school_admin.set_password(DEV_PASSWORD)
        user = school_admin
    else:
        admin = Administrator(username=f"dev-admin-{tag}", name=name)
        admin.set_password(DEV_PASSWORD)
        user = admin
    db.session.add(user)
    db.session.commit()
    return user


def _resolve_user() -> User:
    if user_id := request.args.get("id", type=int):
        return db.get_or_404(User, user_id)
    user_type = request.args.get("type", "")
    if user_type not in MODELS:
        abort(400, f"type must be one of: {', '.join(MODELS)}")
    if not request.args.get("new"):
        model = MODELS[user_type]
        existing = db.session.scalars(select(model).order_by(model.id)).first()
        if existing is not None:
            return existing
    return _create(user_type)


def _user_index():
    """Up to 10 users per role, so a caller can pick a specific one by id."""
    index = {}
    for user_type, model in MODELS.items():
        rows = db.session.scalars(select(model).order_by(model.id).limit(10)).all()
        index[user_type] = [
            {
                "id": user.id,
                "name": user.name,
                "login": getattr(user, "username", None) or getattr(user, "email", None),
                "school_id": getattr(user, "school_id", None),
                "login_url": f"/dev/login-as?id={user.id}",
            }
            for user in rows
        ]
    return index


def _flag(name: str, allowed: tuple[str, ...]) -> str | None:
    """A state query param's value, None when absent; 400 on anything not in `allowed`."""
    value = request.args.get(name)
    if value is not None and value not in allowed:
        abort(400, f"{name} must be one of: {', '.join(allowed)}")
    return value


def _apply_state(user: User) -> None:
    """Set onboarding state from `survey` / `map_test` params; absent params change nothing.
    `survey` applies to learners and volunteers, `map_test` to learners."""
    survey = _flag("survey", ("0", "1"))
    map_test = _flag("map_test", ("0", "1", "deferred"))
    if survey is not None and isinstance(user, (Learner, Volunteer)):
        user.completed_survey = survey == "1"
    if map_test is not None and isinstance(user, Learner):
        user.completed_map_test = map_test != "0"
        user.map_test_deferred = map_test == "deferred"
        if map_test != "1":
            user.subject_levels = {}
    db.session.commit()


@base_bp.route("/dev/login-as")
def dev_login_as():
    if not is_local_dev_request():
        abort(404)
    if "id" not in request.args and "type" not in request.args:
        return jsonify(_user_index())

    user = _resolve_user()
    _apply_state(user)
    sign_in(user)

    return redirect(safe_local_path(request.args.get("next")) or dashboard_url(user))

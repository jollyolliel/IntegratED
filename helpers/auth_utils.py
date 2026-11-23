from __future__ import annotations

import secrets
import string
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

from flask import abort, redirect, url_for

from helpers.current_user import current_user

if TYPE_CHECKING:
    from models import School, User

__all__ = [
    "clean_credential", "dashboard_url", "find_by_email", "find_by_username", "get_or_create_invite_code",
    "has_whitespace", "limit_to_type", "match_required", "password_matches", "regenerate_invite_code", "sign_in", "username_taken",
    "validate_invite_code",
]

_DASHBOARDS = {
    "learner": "learner.learner_dashboard",
    "volunteer": "volunteer.volunteer_dashboard",
    "teacher": "teacher.teacher_dashboard",
    "school_admin": "school_admin.dashboard",
    "administrator": "administrator.dashboard",
}


def clean_credential(value: object) -> str:
    """A typed username or password without surrounding whitespace; inner spaces stay.

    Args:
        value (object): The raw form or JSON value; None becomes "".

    Returns:
        str: The value without surrounding whitespace.
    """
    return "" if value is None else str(value).strip()


def has_whitespace(value: str) -> bool:
    """Whether a (trimmed) username or password contains any space, tab, newline or other Unicode space.

    New usernames and passwords may not (e.g. a learner types them in from a card, where a space is invisible).
    Login still accepts an older password that holds one, so only setters call this.

    Args:
        value (str): The credential after `clean_credential`.

    Returns:
        bool: True when any character is whitespace.
    """
    return any(char.isspace() for char in value)


def password_matches(user: User, typed: object) -> bool:
    """Whether `typed` is `user`'s password, trimmed, or exactly as typed for one saved before trimming.

    Args:
        user (User): The account whose password is checked.
        typed (object): The password as entered.

    Returns:
        bool: True when either form matches; never for a blank entry.
    """
    cleaned = clean_credential(typed)
    if not cleaned:
        return False
    if user.check_password(cleaned):
        return True
    return isinstance(typed, str) and typed != cleaned and user.check_password(typed)


def find_by_username(username: str, exclude_id: int | None = None) -> User | None:
    """The account holding `username`, trying roles in /login's order.

    A username is unique within a role's table, not across them, so the first match wins.

    Args:
        username (str): The username to look up; empty finds nothing.
        exclude_id (int | None): An account to ignore — the one being renamed.

    Returns:
        User | None: The first account with that username.
    """
    from extensions import db
    from models import Administrator, Learner, SchoolAdmin

    if not username:
        return None
    for model in (Learner, Administrator, SchoolAdmin):
        stmt = db.select(model).where(model.username == username)
        if exclude_id is not None:
            stmt = stmt.where(model.id != exclude_id)
        found = db.session.scalar(stmt.limit(1))
        if found is not None:
            return found
    return None


def find_by_email(email: str) -> User | None:
    """The teacher or volunteer with `email` (the roles that have one).

    Args:
        email (str): The email to look up; empty finds nothing.

    Returns:
        User | None: The account with that email.
    """
    from extensions import db
    from models import Teacher, Volunteer

    if not email:
        return None
    for model in (Teacher, Volunteer):
        found = db.session.scalar(db.select(model).where(model.email == email).limit(1))
        if found is not None:
            return found
    return None


def username_taken(username: str, exclude_id: int | None = None) -> bool:
    """Whether any role's account holds `username`.

    Args:
        username (str): The username to check.
        exclude_id (int | None): An account to ignore — the one being renamed.

    Returns:
        bool: True when another account already uses it.
    """
    return find_by_username(username, exclude_id) is not None


def sign_in(user: User) -> None:
    """Sign this browser in as `user`, once the user is settled — never before a failure branch.

    A fresh sign-in ends any impersonation, or /admin/impersonate/stop would later sign this
    browser back in as that administrator. Then Flask-Login's session and PostHog's identity.

    Args:
        user (User): The account to sign in as.
    """
    from flask import session
    from flask_login import login_user

    from helpers.analytics import identify_user

    session.pop("impersonating_admin_id", None)
    login_user(user)
    identify_user(user)


LOOPBACK = frozenset({"127.0.0.1", "::1"})


def is_local_dev_request() -> bool:
    """Whether the dev-only sign-ins (/dev/login-as, /dev/google-sign-in) may answer this request.

    Only on a development server and only from this machine, so a dev server bound to 0.0.0.0 on
    a shared network does not hand out logins.

    Returns:
        bool: True for a loopback client of a development server.
    """
    from flask import request

    from settings import get_settings

    return get_settings().is_development and request.remote_addr in LOOPBACK


def dashboard_url(user: User) -> str:
    """Where `user` lands after signing in (or being signed in as): their role's dashboard."""
    return url_for(_DASHBOARDS.get(user.user_type, "base.home"))


def match_required(redirect_to: str | None = None, **requirements: Any) -> Callable:
    """Ensures the user matches specific session/model attributes (e.g., user_type='teacher')
    before accessing a route.

    Args:
        redirect_to (str | None): Endpoint to redirect to on a mismatch; aborts
            403 instead when None.
        **requirements: Attribute name -> required value pairs checked against
            `current_user`.

    Returns:
        Callable: The route decorator.
    """
    def decorator(f: Callable) -> Callable:
        """Wrap `f` with the attribute check."""
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            """Run the attribute check, then call `f` if it passes."""
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))

            for attribute, expected_value in requirements.items():
                user_value = getattr(current_user, attribute, None)
                if user_value != expected_value:
                    if redirect_to:
                        return redirect(url_for(redirect_to))
                    abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def limit_to_type(user_type: str) -> Any:
    """Abstraction for Blueprint.before_request handlers.

    Args:
        user_type (str): The required `current_user.user_type`.

    Returns:
        Any: A redirect/abort response if the check fails, else None (request proceeds).
    """
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if current_user.user_type != user_type:
        abort(403)
    return None


def get_or_create_invite_code(school: School) -> str:
    """Return the school's invite code, creating one only if it has none.

    The code is stored on the school row, so it survives restarts, and it never
    expires or rotates on its own: only `regenerate_invite_code` changes it.

    Args:
        school (School): The school whose invite code to fetch.

    Returns:
        str: The school's current invite code.
    """
    if school.invite_code:
        return school.invite_code
    return regenerate_invite_code(school)


#: Draws before giving up. 36⁶ codes make even one collision rare; this many in a row means the
#: unique index is rejecting something other than a duplicate code.
INVITE_CODE_ATTEMPTS = 10


def regenerate_invite_code(school: School) -> str:
    """Replace the school's invite code with a fresh one and commit; the old code stops working.

    Each draw is tried in a savepoint, so a collision undoes only that draw — never anything
    else the caller has pending, which the final commit saves along with the code.

    Args:
        school (School): The school to give a new invite code.

    Returns:
        str: The new invite code.

    Raises:
        RuntimeError: `INVITE_CODE_ATTEMPTS` draws in a row were all taken.
    """
    from sqlalchemy.exc import IntegrityError

    from extensions import db

    previous = school.invite_code
    for _ in range(INVITE_CODE_ATTEMPTS):
        code = _random_code()
        if code == previous:
            continue
        try:
            with db.session.begin_nested():
                school.invite_code = code
        except IntegrityError:
            continue  # another school holds this code (unique index): draw again
        db.session.commit()
        return code
    raise RuntimeError(f"No free invite code after {INVITE_CODE_ATTEMPTS} draws.")


def _random_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def validate_invite_code(code: str) -> School | None:
    """Return the School whose invite code this is, else None.

    Args:
        code (str): Invite code to validate (case-insensitive).

    Returns:
        School | None: The matching school, or None.
    """
    from extensions import db
    from models import School
    code = (code or "").upper().strip()
    if not code:
        return None
    return db.session.scalar(db.select(School).filter_by(invite_code=code))

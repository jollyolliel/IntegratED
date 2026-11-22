"""Typed re-exports of Flask-Login's `current_user` proxy.

`flask_login.current_user` is an untyped `LocalProxy`, so editors can't offer
attribute autocomplete or catch typos against it. At runtime it's whichever
`User` subclass is logged in (`Learner`/`Volunteer`/`Teacher`/`Administrator`/
`SchoolAdmin`), or `AnonymousUserMixin` when not — but nearly every route that
touches attributes beyond `is_authenticated` sits behind a gate (blueprint
`before_request`, `@admin_required`, or an inline `user_type` check) that
guarantees one specific subclass first. Code paths that must handle the
anonymous case, or that run across more than one role (settings, login,
`helpers/auth_utils.py`'s decorators, analytics capture), still call
`current_user.is_authenticated` / branch on `user_type`, which exist on every
one of these classes, so this typing doesn't change runtime behavior anywhere.

Import whichever name matches the gate already guarding the call site:
`current_user` (base `User`) where the role is generic/unauthenticated,
otherwise the role-specific name — e.g. `from helpers.current_user import
current_learner as current_user` inside a learner-only route file. That keeps
existing `current_user.foo` call sites unchanged while getting them real
attribute autocomplete/checking against the concrete model.

Only import a role-specific name into a file where every `current_user` use
already sits behind that role's gate — an ungated or multi-role file (e.g.
`routes/base/_settings.py`, `routes/auth/_login.py`) must keep the base
`current_user`.
"""
from typing import TYPE_CHECKING, cast

from flask_login import current_user as _current_user

if TYPE_CHECKING:
    from models import Administrator, Learner, SchoolAdmin, Teacher, User, Volunteer

current_user = cast("User", _current_user)
current_learner = cast("Learner", _current_user)
current_volunteer = cast("Volunteer", _current_user)
current_teacher = cast("Teacher", _current_user)
current_administrator = cast("Administrator", _current_user)
current_school_admin = cast("SchoolAdmin", _current_user)

__all__ = [
    "current_administrator",
    "current_learner",
    "current_school_admin",
    "current_teacher",
    "current_user",
    "current_volunteer",
]

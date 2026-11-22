"""Administrator blueprint — org-wide admin panel.

Layout:
  people.py         school/user CRUD, org dashboard, donations view
  db_console.py      raw-SQL query/table browser/export/import tool
  impersonation.py   impersonate / impersonate_stop
  cms.py              site settings, team-member CMS, article CMS
"""

from functools import wraps

from flask import Blueprint, redirect, url_for

from extensions import limiter
from helpers.current_user import current_administrator as current_user

administrator_bp = Blueprint("administrator", __name__)
limiter.limit("120 per minute")(administrator_bp)


def admin_required(f):
    """Gate a view to `user_type == "administrator"`.

    Silently redirects to login rather than 403ing — same non-admin-safe
    pattern as an anonymous visit, so it doesn't reveal that a route exists
    to someone who isn't logged in as an admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        """Wrapped view — see `admin_required`'s docstring for the gate itself."""
        if not current_user.is_authenticated or current_user.user_type != "administrator":
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function


# Submodules register their routes onto `administrator_bp` at import time —
# each does `from routes.administrator import administrator_bp, admin_required`,
# which works because both names already exist in this partially-initialized
# module's namespace by the time these imports run.
from routes.administrator import (  # noqa: F401
    cms,
    db_console,
    impersonation,
    people,
)

# Kept importable at the package root for backward compatibility — some
# callers (e.g. tests exercising the SQL-injection guard directly) do
# `from routes.administrator import _safe_is_select`.
from routes.administrator.db_console import _safe_is_select  # noqa: F401

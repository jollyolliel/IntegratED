"""Auth blueprint — password login, Google OAuth, registration wizard.

Layout:
  _login.py     login, logout
  _oauth.py     Google OAuth (login_google, authorize)
  _register.py  register, is_password_strong, validate_invite, start_volunteer_register

`auth_bp` is created here first; each submodule does `from routes.auth import
auth_bp` and that succeeds even though this module is still initializing,
because `auth_bp` is already bound in `routes.auth`'s namespace by the time
the bottom-of-file imports run.
"""

from flask import Blueprint

from extensions import limiter

auth_bp = Blueprint("auth", __name__)
limiter.limit("20 per minute", methods=["POST"])(auth_bp)

# Imported at the bottom so each submodule's `@auth_bp.route(...)` decorators
# run and register against the already-created `auth_bp`.
from routes.auth import _login, _oauth, _register  # noqa: F401

# Kept importable at the package root for backward compatibility —
# routes/base.py's settings() and tests do `from routes.auth import
# is_password_strong`.
from routes.auth._register import is_password_strong  # noqa: F401

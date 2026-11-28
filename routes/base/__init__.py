"""Base blueprint — public marketing pages, donations/Stripe, account settings.

Layout:
  _public.py     home, schools, about, articles, legal pages, favicon
  _donations.py  donation form, Stripe checkout + webhook, record_donation_from_session
  _settings.py   account settings (profile/password/delete)
  _dev.py        component gallery and brand preview (404 in production)
  _dev_login.py  dev-only /dev/login-as — sign in as any user (404 outside development)
"""

from flask import Blueprint

from extensions import limiter

base_bp = Blueprint("base", __name__)
limiter.limit("120 per minute")(base_bp)

# Imported at the bottom so each submodule's `@base_bp.route(...)` decorators
# run and register against the already-created `base_bp`.
from routes.base import _dev, _dev_login, _donations, _public, _settings  # noqa: F401

# Kept importable at the package root for backward compatibility — tests do
# `from routes.base import record_donation_from_session`.
from routes.base._donations import record_donation_from_session  # noqa: F401

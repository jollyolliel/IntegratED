"""Which environment the app runs in, and every per-deploy parameter and secret it reads.

`APP_ENV` names the environment (`Environment`). It has no default, so a deploy that forgets it
fails at startup instead of booting production as development. Code asks which environment it
is in (`settings.is_production` / `is_development`, both read off `env`), never a separate yes/no
"deployed" flag, so a further environment can be added without every check meaning something new.

Everything is read from the environment once, at startup, and nothing else reads `os.environ`
for these names. None of it lives in the database, because a constant should not cost a query
on every request.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "DEFAULT_ELEVEN_MODEL_ID",
    "DEFAULT_ELEVEN_VOICE_ID",
    "DEFAULT_POSTHOG_HOST",
    "Environment",
    "Settings",
    "SettingsError",
    "get_settings",
]

DEFAULT_ELEVEN_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_ELEVEN_MODEL_ID = "eleven_v3"
DEFAULT_POSTHOG_HOST = "https://eu.i.posthog.com"

_TRUE = {"1", "true", "yes", "on"}


class Environment(StrEnum):
    """Where the app runs. `APP_ENV` must name one of these."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class SettingsError(RuntimeError):
    """The environment is missing or misconfigured; the app must not start."""


def _read(environ: Mapping[str, str], name: str, default: str = "") -> str:
    return environ.get(name, default).strip()


def _require(environ: Mapping[str, str], name: str, why: str) -> str:
    value = _read(environ, name)
    if not value:
        raise SettingsError(f"{name} must be set: {why}.")
    return value


@dataclass(frozen=True)
class Settings:
    """Environment, per-deploy parameters and secrets, read once from env."""

    env: Environment
    secret_key: str
    google_client_id: str
    google_client_secret: str
    database_url: str
    test_database_url: str
    gcs_bucket_name: str
    local_bucket_dir: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    posthog_api_key: str
    posthog_host: str
    posthog_personal_api_key: str
    gemini_api_key: str
    eleven_api_key: str
    eleven_voice_id: str
    eleven_model_id: str
    tts_enabled: bool
    contact_email: str
    github_repo_url: str

    @property
    def is_production(self) -> bool:
        """True when `APP_ENV=production`."""
        return self.env is Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        """True when `APP_ENV=development`."""
        return self.env is Environment.DEVELOPMENT

    @property
    def analytics_enabled(self) -> bool:
        """Whether PostHog events and logs are sent: production with a PostHog key."""
        return self.is_production and bool(self.posthog_api_key)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Read and validate settings.

        Args:
            environ (Mapping[str, str] | None): Variables to read; defaults to `os.environ`.

        Returns:
            Settings: The validated settings.

        Raises:
            SettingsError: `APP_ENV` is unset or unknown, or a variable that environment needs is unset.
        """
        environ = os.environ if environ is None else environ
        raw_env = _read(environ, "APP_ENV").lower()
        try:
            env = Environment(raw_env)
        except ValueError:
            names = ", ".join(e.value for e in Environment)
            raise SettingsError(
                f"APP_ENV must be one of {names} (got {raw_env or 'nothing'}). "
                "Set it in .env for development; production services set APP_ENV=production."
            ) from None
        production = env is Environment.PRODUCTION
        return cls(
            env=env,
            secret_key=_require(environ, "SECRET_KEY", "it signs every session cookie"),
            # Development signs in through /dev/google-sign-in instead (routes/auth/_oauth.py).
            google_client_id=(
                _require(environ, "GOOGLE_CLIENT_ID", "teachers and volunteers sign in with Google")
                if production else _read(environ, "GOOGLE_CLIENT_ID")
            ),
            google_client_secret=(
                _require(environ, "GOOGLE_CLIENT_SECRET", "teachers and volunteers sign in with Google")
                if production else _read(environ, "GOOGLE_CLIENT_SECRET")
            ),
            database_url=(
                _require(environ, "DATABASE_URL", "production runs on Postgres")
                if production else _read(environ, "DATABASE_URL")
            ),
            test_database_url=_read(environ, "TEST_DATABASE_URL"),
            gcs_bucket_name=(
                _require(environ, "GCS_BUCKET_NAME", "production keeps worksheets, audio and content in the bucket")
                if production else _read(environ, "GCS_BUCKET_NAME")
            ),
            local_bucket_dir=_read(environ, "LOCAL_BUCKET_DIR"),
            stripe_secret_key=_read(environ, "STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_read(environ, "STRIPE_WEBHOOK_SECRET"),
            posthog_api_key=_read(environ, "POSTHOG_API_KEY"),
            posthog_host=_read(environ, "POSTHOG_HOST") or DEFAULT_POSTHOG_HOST,
            posthog_personal_api_key=_read(environ, "POSTHOG_PERSONAL_API_KEY"),
            gemini_api_key=_read(environ, "GEMINI_AISTUDIO_API_KEY"),
            eleven_api_key=_read(environ, "ELEVEN_API_KEY"),
            eleven_voice_id=_read(environ, "ELEVEN_VOICE_ID") or DEFAULT_ELEVEN_VOICE_ID,
            eleven_model_id=_read(environ, "ELEVEN_MODEL_ID") or DEFAULT_ELEVEN_MODEL_ID,
            tts_enabled=_read(environ, "TTS_ENABLED").lower() in _TRUE,
            contact_email=_read(environ, "CONTACT_EMAIL"),
            github_repo_url=_read(environ, "GITHUB_REPO_URL"),
        )


def get_settings() -> Settings:
    """The running app's settings, or a fresh read of the environment outside an app context.

    Returns:
        Settings: `app.config["SETTINGS"]` when there is a Flask app, else `Settings.from_env()`.
    """
    from flask import current_app, has_app_context

    if has_app_context():
        configured = current_app.config.get("SETTINGS")
        if configured is not None:
            return configured
    return Settings.from_env()

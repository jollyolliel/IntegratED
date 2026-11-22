"""`APP_ENV` names the environment; the rest of settings is the per-deploy config and secrets, read once."""

import pytest

from settings import Environment, Settings, SettingsError

pytestmark = pytest.mark.unit

#: What every environment needs before anything else is checked.
BASE = {"SECRET_KEY": "s", "GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret"}
PRODUCTION = {**BASE, "APP_ENV": "production", "DATABASE_URL": "postgresql://u@h/db", "GCS_BUCKET_NAME": "bucket"}


def _dev(**extra):
    return Settings.from_env({**BASE, "APP_ENV": "development", **extra})


def test_unset_app_env_fails_naming_the_variable():
    with pytest.raises(SettingsError, match="APP_ENV"):
        Settings.from_env(BASE)


@pytest.mark.parametrize("value", ["deployed", "staging", "prod"])
def test_unknown_app_env_fails_naming_the_variable(value):
    with pytest.raises(SettingsError, match="APP_ENV"):
        Settings.from_env({**BASE, "APP_ENV": value})


def test_each_environment_maps_to_its_enum():
    assert _dev().env is Environment.DEVELOPMENT
    assert _dev().is_development and not _dev().is_production
    production = Settings.from_env(PRODUCTION)
    assert production.env is Environment.PRODUCTION
    assert production.is_production and not production.is_development


def test_app_env_is_trimmed_and_case_insensitive():
    assert Settings.from_env({**PRODUCTION, "APP_ENV": " Production "}).is_production


@pytest.mark.parametrize("legacy", ["K_SERVICE", "RENDER", "DEPLOYED"])
def test_legacy_signals_do_not_make_production(legacy):
    assert _dev(**{legacy: "true"}).is_production is False


def test_every_environment_needs_a_secret_key():
    with pytest.raises(SettingsError, match="SECRET_KEY"):
        Settings.from_env({k: v for k, v in {**BASE, "APP_ENV": "development"}.items() if k != "SECRET_KEY"})


@pytest.mark.parametrize("missing", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"])
def test_production_needs_google_credentials(missing):
    with pytest.raises(SettingsError, match=missing):
        Settings.from_env({k: v for k, v in PRODUCTION.items() if k != missing})


def test_development_starts_without_google_credentials():
    """Locally, /dev/google-sign-in stands in for Google (routes/auth/_oauth.py)."""
    settings = Settings.from_env({"APP_ENV": "development", "SECRET_KEY": "s"})
    assert settings.google_client_id == ""
    assert settings.google_client_secret == ""


@pytest.mark.parametrize("missing", ["DATABASE_URL", "GCS_BUCKET_NAME"])
def test_production_needs_a_database_and_a_bucket(missing):
    with pytest.raises(SettingsError, match=missing):
        Settings.from_env({k: v for k, v in PRODUCTION.items() if k != missing})


def test_development_needs_neither_database_nor_bucket():
    settings = _dev()
    assert settings.database_url == ""
    assert settings.gcs_bucket_name == ""


def test_per_deploy_parameters_have_safe_defaults():
    settings = _dev()
    assert settings.contact_email == ""
    assert settings.github_repo_url == ""
    assert settings.tts_enabled is False
    assert settings.eleven_voice_id
    assert settings.eleven_model_id
    assert settings.posthog_host.startswith("https://")


def test_per_deploy_parameters_and_secrets_come_from_env():
    settings = Settings.from_env({
        **PRODUCTION,
        "CONTACT_EMAIL": " hello@example.test ",
        "GITHUB_REPO_URL": "https://github.com/example/repo",
        "ELEVEN_VOICE_ID": "voice-1",
        "ELEVEN_MODEL_ID": "model-1",
        "TTS_ENABLED": "true",
        "STRIPE_WEBHOOK_SECRET": "whsec",
        "GEMINI_AISTUDIO_API_KEY": "gem",
        "ELEVEN_API_KEY": "eleven",
    })
    assert settings.contact_email == "hello@example.test"
    assert settings.github_repo_url == "https://github.com/example/repo"
    assert settings.eleven_voice_id == "voice-1"
    assert settings.eleven_model_id == "model-1"
    assert settings.tts_enabled is True
    assert settings.stripe_webhook_secret == "whsec"
    assert settings.gemini_api_key == "gem"
    assert settings.eleven_api_key == "eleven"
    assert settings.database_url == "postgresql://u@h/db"
    assert settings.gcs_bucket_name == "bucket"


@pytest.mark.parametrize("raw,expected", [("1", True), ("yes", True), ("TRUE", True), ("0", False), ("", False), ("no", False)])
def test_tts_enabled_parsing(raw, expected):
    assert _dev(TTS_ENABLED=raw).tts_enabled is expected


def test_analytics_run_only_in_production_with_a_posthog_key():
    assert Settings.from_env({**PRODUCTION, "POSTHOG_API_KEY": "phc"}).analytics_enabled is True
    assert Settings.from_env(PRODUCTION).analytics_enabled is False
    assert _dev(POSTHOG_API_KEY="phc").analytics_enabled is False

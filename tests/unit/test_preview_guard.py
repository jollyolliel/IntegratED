"""`APP_ENV=preview` runs unreviewed PR code, so it must refuse to start beside anything from prod."""

import pytest

from settings import Environment, Settings, SettingsError

pytestmark = pytest.mark.unit


def _preview(**extra):
    return Settings.from_env({"APP_ENV": "preview", **extra})


def test_a_bare_preview_starts_with_nothing_configured():
    settings = _preview()
    assert settings.env is Environment.PREVIEW
    assert settings.is_preview
    assert not settings.is_production and not settings.is_development
    assert not settings.analytics_enabled
    assert not settings.tts_enabled


def test_each_preview_boot_makes_its_own_secret_key():
    first, second = _preview().secret_key, _preview().secret_key
    assert len(first) >= 32
    assert first != second


@pytest.mark.parametrize(
    "name",
    [
        "SECRET_KEY",
        "DATABASE_URL",
        "GCS_BUCKET_NAME",
        "GOOGLE_CLIENT_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "POSTHOG_API_KEY",
        "POSTHOG_PERSONAL_API_KEY",
        "GEMINI_AISTUDIO_API_KEY",
        "ELEVEN_API_KEY",
    ],
)
def test_any_real_credential_stops_a_preview(name):
    with pytest.raises(SettingsError, match=name) as error:
        _preview(**{name: "leak-me-not"})
    assert "leak-me-not" not in str(error.value)


@pytest.mark.parametrize("service", ["integrated", "pr-", "pr-12x", "main-prod", "pr-1\n2"])
def test_only_preview_service_names_may_run_a_preview(service):
    with pytest.raises(SettingsError, match="K_SERVICE"):
        _preview(K_SERVICE=service)


@pytest.mark.parametrize("service", ["pr-1", "pr-4821", "main", ""])
def test_preview_service_names_start(service):
    assert _preview(K_SERVICE=service).is_preview


def test_production_given_the_preview_flag_crashes_instead_of_opening_a_login_bypass():
    production_service = {
        "K_SERVICE": "integrated",
        "SECRET_KEY": "s",
        "DATABASE_URL": "postgresql://u@h/db",
        "GCS_BUCKET_NAME": "bucket",
    }
    with pytest.raises(SettingsError):
        _preview(**production_service)


def test_a_preview_reads_what_the_workflow_tells_it():
    settings = _preview(PREVIEW_PR="42", PREVIEW_LINKS="abc=", PREVIEW_DATA_DIR="/tmp/x")
    assert (settings.preview_pr, settings.preview_links, settings.preview_data_dir) == ("42", "abc=", "/tmp/x")


def test_a_preview_keeps_its_data_in_the_temp_folder_by_default():
    assert _preview().preview_data_dir

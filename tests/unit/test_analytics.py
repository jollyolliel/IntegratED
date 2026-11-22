import pytest

from helpers.analytics import redact_properties

pytestmark = pytest.mark.unit


def test_redact_properties_removes_sensitive_values_recursively():
    payload = {"email": "person@example.com", "nested": {"token": "secret", "ok": 3}}

    redacted = redact_properties(payload)

    assert redacted["email"] == "person@example.com"
    assert redacted["nested"] == {"token": "[redacted]", "ok": 3}
    assert payload["nested"]["token"] == "secret"


def test_a_signup_set_dict_reaches_posthog():
    redacted = redact_properties({"$set": {"username": "ada", "user_type": "learner"}})

    assert redacted == {"$set": {"username": "ada", "user_type": "learner"}}


def test_a_key_that_merely_ends_in_key_is_kept():
    redacted = redact_properties({"announcement_key": "garden-v2", "api_key": "sk-1", "key": "x"})

    assert redacted == {"announcement_key": "garden-v2", "api_key": "[redacted]", "key": "[redacted]"}


def test_lists_are_redacted_item_by_item():
    redacted = redact_properties({"rows": [{"password": "pw", "n": 1}, "plain"]})

    assert redacted == {"rows": [{"password": "[redacted]", "n": 1}, "plain"]}


def test_very_deep_nesting_is_collapsed():
    redacted = redact_properties({"a": {"b": {"c": {"d": {"e": 1}}}}})

    assert redacted == {"a": {"b": {"c": "[complex data]"}}}


def test_redact_properties_redacts_sensitive_top_level_keys():
    redacted = redact_properties({"token": "secret", "password": "pw", "count": 3})

    assert redacted == {"token": "[redacted]", "password": "[redacted]", "count": 3}

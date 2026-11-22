"""Small semantic assertions that keep web tests concise and stable."""

from __future__ import annotations

from urllib.parse import urlsplit


def assert_success(response, status=200):
    assert response.status_code == status, response.get_data(as_text=True)[:500]
    return response


def assert_redirects_to(response, target):
    assert response.status_code in {301, 302, 303, 307, 308}
    actual = urlsplit(response.headers["Location"])
    expected = urlsplit(target)
    assert actual.path == expected.path
    if expected.query:
        assert actual.query == expected.query
    return response


def assert_denied(response):
    """The request was refused — 401/403, or bounced to a login/other page.

    The application is not uniform here: some gates abort with 403, others
    redirect to the login screen or to the caller's own dashboard. What every
    test actually needs to know is "this did not render the guarded page", so
    that is what this asserts.
    """

    assert response.status_code in {401, 403, 404, 302, 303, 308}, (
        f"expected a refusal, got {response.status_code}\n"
        f"{response.get_data(as_text=True)[:500]}"
    )
    return response


def assert_json_error(response, status):
    """A JSON error response with the given status and an `error` message."""

    assert response.status_code == status, response.get_data(as_text=True)[:500]
    payload = response.get_json()
    assert isinstance(payload, dict), payload
    assert payload.get("error"), f"expected an error message; payload={payload!r}"
    return payload


def assert_json_keys(response, *keys):
    payload = response.get_json()
    assert isinstance(payload, dict), payload
    missing = set(keys) - payload.keys()
    assert not missing, f"missing JSON keys: {sorted(missing)}; payload={payload!r}"
    return payload

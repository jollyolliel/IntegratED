"""Every registered rule is checked against an explicit role policy.

The policy table below is written by hand on purpose. Deriving it from the
decorators would only prove the decorators equal themselves; stating the intent
separately is what lets this file catch a route that ships without a gate.

`test_every_rule_is_either_public_or_carries_a_role_policy` is the tripwire:
add a blueprint route and this file fails until the policy names who may reach
it.

Note that `routes/api.py` does its role check *inside* the view body
(`if current_user.user_type != "learner": abort(403)`, or in
`routes.api.minigames._complete`) rather than with a decorator, so the gate is real even
though nothing decorates the function.
"""

from __future__ import annotations

import re

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound

from tests.support.auth import login_as

pytestmark = pytest.mark.web

ALL_ROLES = ("learner", "volunteer", "teacher", "administrator", "school_admin")

#: Exact rules whose policy does not follow from their prefix.
EXACT_POLICY = {
    # Teacher-only despite living under /api.
    "/api/run-matching": ("teacher",),
    "/api/matching/preview": ("teacher",),
    # Every role sees announcement popups, so every role may dismiss one.
    "/api/announcements/<int:announcement_id>/dismiss": ALL_ROLES,
    # Any signed-in user edits their own profile.
    "/settings": ALL_ROLES,
}

#: URL-rule prefix -> the roles allowed through. Longest prefix wins.
ROLE_POLICY = {
    "/admin/": ("administrator",),
    "/teacher/": ("teacher",),
    "/learner/": ("learner",),
    "/volunteer/": ("volunteer",),
    "/school/": ("school_admin",),
    "/assistant/": ("teacher",),
    "/api/": ("learner",),
}

#: Public rules matched exactly. "/" cannot go in PUBLIC_PREFIXES below —
#: as a prefix it would swallow every route in the map.
PUBLIC_EXACT = {"/"}

#: Rules reachable without signing in at all.
PUBLIC_PREFIXES = (
    "/login",
    "/register",
    "/authorize",
    "/logout",
    "/validate-invite",
    "/start-volunteer-register",
    "/health",
    "/audio/",
    "/set-language",
    "/favicon.ico",
    "/schools",
    "/donations",
    "/donation-success",
    "/about",
    "/articles",  # legacy URLs, 301 to /news
    "/news",
    "/stripe/webhook",
    "/terms",
    "/privacy",
    "/error",
    "/dev/components",  # dev-only gallery; 404 outside development (tests/web/test_component_gallery.py)
    "/dev/quiz-hint",  # dev-only hint-card preview; 404 outside development (tests/web/test_component_gallery.py)
    "/dev/login-as",  # dev-only, loopback-only sign-in; 404 outside development (tests/web/test_dev_login.py)
    "/dev/google-sign-in",  # dev-only, loopback-only Google stand-in (tests/web/test_dev_google_sign_in.py)
    # Carries no decorator, but the view only pops `impersonating_admin_id`
    # from the session and redirects; with no such key it is a no-op. Covered
    # directly by test_impersonate_stop_is_a_harmless_no_op_when_signed_out.
    "/admin/impersonate/stop",
)

#: Placeholder values per converter, so a rule can be turned into a real URL.
SAMPLE_VALUES = {"int": "1", "float": "1.0", "path": "sample.txt", "string": "sample"}

DENIED_STATUSES = {301, 302, 303, 307, 308, 401, 403}

_PLACEHOLDER = re.compile(r"<(?:(?P<conv>[a-z]+)(?:\([^)]*\))?:)?(?P<name>[^>]+)>")


def _concrete_path(rule_string):
    """Turn `/teacher/learners/<int:learner_id>` into `/teacher/learners/1`."""

    def replace(match):
        return SAMPLE_VALUES.get(match.group("conv") or "string", "sample")

    return _PLACEHOLDER.sub(replace, rule_string)


def _method_for(rule):
    for method in ("GET", "POST"):
        if method in rule.methods:
            return method
    return min(rule.methods - {"HEAD", "OPTIONS"})


def _policy_for(rule_string):
    if rule_string in EXACT_POLICY:
        return EXACT_POLICY[rule_string]
    matches = [prefix for prefix in ROLE_POLICY if rule_string.startswith(prefix)]
    if not matches:
        return None
    return ROLE_POLICY[max(matches, key=len)]


def _is_public(rule_string):
    if rule_string in PUBLIC_EXACT:
        return True
    return any(
        rule_string == prefix or rule_string.startswith(prefix)
        for prefix in PUBLIC_PREFIXES
    )


def _guarded_rules(app):
    """Every rule that should require a session, with its policy."""

    found = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static" or _is_public(rule.rule):
            continue
        policy = _policy_for(rule.rule)
        if policy is None:
            continue
        found.append((rule.rule, _concrete_path(rule.rule), _method_for(rule), policy))
    return sorted(found)


def _request(client, method, path):
    return client.get(path) if method == "GET" else client.post(path)


def _make_user(db_session, role, school):
    from tests.support import factories

    builders = {
        "learner": lambda: factories.make_learner(db_session, school),
        "volunteer": lambda: factories.make_volunteer(db_session, school),
        "teacher": lambda: factories.make_teacher(db_session, school),
        "administrator": lambda: factories.make_admin(db_session),
        "school_admin": lambda: factories.make_school_admin(db_session, school),
    }
    return builders[role]()


# ── the policy covers the whole url_map ──────────────────────────────────────


def test_every_rule_is_either_public_or_carries_a_role_policy(app):
    """No route may exist that this file has no opinion about."""

    unclassified = [
        rule.rule
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
        and not _is_public(rule.rule)
        and _policy_for(rule.rule) is None
    ]

    assert not unclassified, (
        "these rules are neither public nor covered by ROLE_POLICY; "
        f"classify them: {sorted(unclassified)}"
    )


def test_every_rule_resolves_to_a_real_url(app):
    """The placeholder substitution must produce URLs that actually match."""

    adapter = app.url_map.bind("localhost")
    unmatched = []
    for rule, path, method, _policy in _guarded_rules(app):
        try:
            adapter.match(path, method=method)
        except (NotFound, MethodNotAllowed):
            unmatched.append((method, rule, path))

    assert not unmatched, f"generated URLs that match no route: {unmatched}"


def test_the_policy_covers_a_realistic_number_of_rules(app):
    """Guards against a refactor that silently empties the matrix."""

    assert len(_guarded_rules(app)) > 80


# ── anonymous access ─────────────────────────────────────────────────────────


def test_guarded_rules_reject_anonymous_visitors(app, client):
    """Not one guarded route may render for a signed-out visitor."""

    leaked = []
    for rule, path, method, _policy in _guarded_rules(app):
        response = _request(client, method, path)
        if response.status_code not in DENIED_STATUSES:
            leaked.append((method, rule, response.status_code))

    assert not leaked, f"reachable while signed out: {leaked}"


def test_impersonate_stop_is_a_harmless_no_op_when_signed_out(client):
    """It carries no auth decorator, so pin down that it cannot do anything.

    With no `impersonating_admin_id` in the session it must not log anyone in;
    it just bounces to the public home page.
    """

    response = client.get("/admin/impersonate/stop")

    assert response.status_code in {301, 302, 303, 307, 308}
    assert "/admin" not in response.headers["Location"]

    with client.session_transaction() as session:
        assert "_user_id" not in session


# ── wrong-role access ────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ALL_ROLES)
def test_guarded_rules_reject_every_role_the_policy_excludes(
    app, client, db_session, school, role
):
    """A signed-in user may not reach another role's pages.

    A 404 is deliberately *not* accepted: the role checks run in
    `before_request`, in a decorator, or as the first statement of the view, so
    they fire before any row lookup. A 404 would mean the request got past the
    gate and merely failed to find a record.
    """

    login_as(client, _make_user(db_session, role, school))

    leaked = []
    for rule, path, method, policy in _guarded_rules(app):
        if role in policy:
            continue
        response = _request(client, method, path)
        if response.status_code not in DENIED_STATUSES:
            leaked.append((method, rule, response.status_code))

    assert not leaked, f"{role} reached routes it should not: {leaked}"

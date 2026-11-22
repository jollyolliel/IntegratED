import logging
import traceback
import uuid
from copy import deepcopy
from typing import Any

from flask import g, has_request_context, request

from helpers.analytics import (
    ANONYMOUS_ID,
    SESSION_HEADER_NAME,
    analytics_enabled,
    posthog_client,
)
from helpers.analytics._redaction import redact_properties
from helpers.current_user import current_user


def _current_user() -> Any | None:
    """The authenticated Flask-Login user for this request, if any.

    Returns:
        Any | None: `current_user`, or None if anonymous/unavailable.
    """
    try:
        if current_user and current_user.is_authenticated:
            return current_user
    except Exception:  # noqa: BLE001 - current_user is a Flask-Login LocalProxy; accessing it outside a valid request/app context can raise from unpredictable internals, and analytics must never crash the request over it
        return None
    return None


def _base_request_properties() -> dict[str, Any]:
    """Properties merged into every captured event.

    Returns:
        dict[str, Any]: `is_authenticated`, `user_type`, and (inside a
            request context) `request_id`/`endpoint`/`path`/
            `posthog_session_id`, plus `school_id`/`teacher_id` when present.
    """
    user = _current_user()
    properties = {
        "is_authenticated": bool(user),
        "user_type": getattr(user, "user_type", "anonymous") if user else "anonymous",
    }

    if has_request_context():
        properties.update({
            "request_id": getattr(g, "request_id", None),
            "endpoint": request.endpoint,
            "path": request.path,
            "posthog_session_id": getattr(g, "posthog_session_id", None),
        })

    if user:
        if getattr(user, "school_id", None):
            properties["school_id"] = user.school_id
        if getattr(user, "teacher_id", None):
            properties["teacher_id"] = user.teacher_id

    return properties


def _distinct_id(explicit_user_id: Any | None = None) -> str:
    """PostHog distinct id for the current capture.

    Args:
        explicit_user_id (Any | None): Caller-supplied user id, used when
            there's no authenticated request user.

    Returns:
        str: The logged-in user's `posthog_id`, `uid_<explicit_user_id>`, or
            `ANONYMOUS_ID`.
    """
    user = _current_user()
    if user:
        return user.posthog_id
    if explicit_user_id:
        return f"uid_{explicit_user_id}"
    return ANONYMOUS_ID


def start_request_context() -> dict[str, Any]:
    """Stamp `flask.g` with a request id and PostHog session id.

    Returns:
        dict[str, Any]: Always `{}` — properties are read from `g` on capture, not cached here.
    """
    if not has_request_context():
        return {}
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.posthog_session_id = request.headers.get(SESSION_HEADER_NAME) or None
    # No longer caching base properties in 'g' to avoid redundant dict merges
    return {}


def finish_request_context(response: Any = None) -> Any:
    """No-op: automatic 'backend_request_completed' capture was removed.

    Args:
        response (Any): The response to pass through unmodified.

    Returns:
        Any: `response`, unchanged.
    """
    return response


def clear_request_context(exception: BaseException | None = None) -> None:
    """No-op teardown hook — context is cleared by Flask automatically.

    Args:
        exception (BaseException | None): Exception that ended the request, if any.

    Returns:
        None
    """
    # Context automatically cleared by Flask teardown


def _user_display_name(user: Any) -> str:
    """Best available human-readable name for a user.

    Args:
        user (Any): A User (or subclass) instance.

    Returns:
        str: `name`, else `username`, else `email`, else `"user_<id>"`.
    """
    if getattr(user, "name", None):
        return user.name
    if getattr(user, "username", None):
        return user.username
    if getattr(user, "email", None):
        return user.email
    return f"user_{user.id}"


def identify_user(user: Any) -> None:
    """Write PostHog person properties for a user. Call after login/registration.

    Args:
        user (Any): The user to identify.

    Returns:
        None
    """
    if not analytics_enabled() or not user:
        return
    try:
        person_props = {
            "$user_type": user.user_type,
            "user_type": user.user_type,
            "name": _user_display_name(user),
        }
        if getattr(user, "email", None):
            person_props["email"] = user.email
        if getattr(user, "username", None):
            person_props["username"] = user.username
        if getattr(user, "school_id", None):
            person_props["school_id"] = user.school_id

        person_props["$name"] = person_props.get("name", f"user_{user.id}")
        # posthog-python v3+ removed Posthog.identify(); set() writes person properties
        posthog_client().set(
            distinct_id=user.posthog_id,
            properties=person_props,
        )
    except Exception as exc:  # noqa: BLE001 - optional external SDK call; one PostHog failure must not crash login/registration
        logging.getLogger(__name__).error("PostHog identify error: %s", exc)


def capture_event(user_id: Any | None, event_name: str, properties: dict[str, Any] | None = None) -> None:
    """Send a PostHog event, merged with base request properties and redacted.

    Args:
        user_id (Any | None): `user.posthog_id`, or None for anonymous.
        event_name (str): PostHog event name.
        properties (dict[str, Any] | None): Extra event properties.

    Returns:
        None
    """
    if not analytics_enabled():
        return

    # Offload to PostHog's background thread
    try:
        # Merge basic properties only when capturing
        merged = _base_request_properties()
        if properties:
            merged.update(properties)

        posthog_client().capture(
            distinct_id=_distinct_id(user_id),
            event=event_name,
            properties=redact_properties(merged),
        )
    except Exception as exc:  # noqa: BLE001 - optional external SDK call; one PostHog failure must not crash the request that triggered it
        logging.getLogger(__name__).error("PostHog capture error: %s", exc)


def capture_exception(user_id: Any | None, exception: BaseException, properties: dict[str, Any] | None = None, tb: Any | None = None) -> None:
    """Send a `$exception` event with a full formatted stack trace.

    Args:
        user_id (Any | None): `user.posthog_id`, or None for anonymous.
        exception (BaseException): The exception being reported.
        properties (dict[str, Any] | None): Extra event properties.
        tb (Any | None): `(exc_type, exc_value, exc_traceback)` tuple to
            format; falls back to `exception.__traceback__` when omitted.

    Returns:
        None
    """
    # Exceptions are high-priority, we capture them with full stack trace
    props = deepcopy(properties or {})

    if tb:
        formatted_tb = "".join(traceback.format_exception(*tb))
    elif hasattr(exception, "__traceback__"):
        formatted_tb = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )
    else:
        formatted_tb = "No traceback available"

    props.update({
        "exception_type": type(exception).__name__,
        "exception_message": str(exception),
        "$exception_type": type(exception).__name__,
        "$exception_message": str(exception),
        "$exception_stack_trace": formatted_tb,
    })
    capture_event(user_id, "$exception", props)

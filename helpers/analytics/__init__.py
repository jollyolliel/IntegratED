"""PostHog + OpenTelemetry event tracking.

Layout:
  _redaction.py  property truncation/redaction before anything leaves the process
  _capture.py    request context, distinct-id resolution, capture_event/capture_exception, identify_user
  _logging.py    console + OpenTelemetry logging setup, global exception hooks

Every event name and its properties is a `capture_event(...)` call, so a
table of them would just be a second copy that drifts — run
`scripts/list_analytics_events.py` to see what already exists before naming
a new one.
"""

import functools

from posthog import Posthog

from settings import get_settings

SESSION_HEADER_NAME = "X-PostHog-Session-ID"
ANONYMOUS_ID = "anonymous"
MAX_PROPERTY_LENGTH = 512
SENSITIVE_KEYS = {
    "password", "password_hash", "token", "authorization", "secret", "key"
}


@functools.cache
def posthog_client() -> Posthog:
    """The process's one PostHog client, built from settings on first use.

    personal_api_key (a PostHog "Personal API Key" scoped to feature_flag:read)
    is required for local feature-flag evaluation — without it the client logs
    "[FEATURE FLAGS] You have to specify a secret_key" on every flag check. The
    client handles its own background threading for flushing.

    Returns:
        Posthog: The shared client.
    """
    settings = get_settings()
    return Posthog(
        project_api_key=settings.posthog_api_key,
        host=settings.posthog_host,
        personal_api_key=settings.posthog_personal_api_key or None,
    )


def analytics_enabled() -> bool:
    """Whether analytics calls should actually send anything.

    Returns:
        bool: True only in production with `POSTHOG_API_KEY` set.
    """
    return get_settings().analytics_enabled


from helpers.analytics._capture import (  # noqa: F401
    capture_event,
    capture_exception,
    clear_request_context,
    finish_request_context,
    identify_user,
    start_request_context,
)
from helpers.analytics._logging import (  # noqa: F401
    flush_analytics,
    init_logging,
    log_error,
    log_info,
    log_warning,
)
from helpers.analytics._redaction import redact_properties  # noqa: F401

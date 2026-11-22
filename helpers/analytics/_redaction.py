from typing import Any

from helpers.analytics import MAX_PROPERTY_LENGTH, SENSITIVE_KEYS


def _truncate_string(value: Any) -> Any:
    """Truncate an over-long string property.

    Args:
        value (Any): Property value; non-strings pass through unchanged.

    Returns:
        Any: `value`, or its first `MAX_PROPERTY_LENGTH` chars + "..." if longer.
    """
    if not isinstance(value, str):
        return value
    if len(value) <= MAX_PROPERTY_LENGTH:
        return value
    return f"{value[:MAX_PROPERTY_LENGTH]}..."


# Substrings that mark a key secret wherever they appear. Plain "key" is matched only
# whole (SENSITIVE_KEYS) or in these compounds, so `announcement_key` still arrives.
_SENSITIVE_PARTS = ("password", "token", "secret", "authorization", "api_key", "apikey", "private_key", "access_key")
# Dict/list levels kept below the top; anything deeper becomes "[complex data]".
_MAX_DEPTH = 2


def _is_sensitive(key: Any) -> bool:
    """Whether a property name marks a value that must never leave the process."""
    lowered = str(key).lower()
    return lowered in SENSITIVE_KEYS or any(part in lowered for part in _SENSITIVE_PARTS)


def _redact_value(value: Any, depth: int) -> Any:
    """Redact one value: recurse into dicts and lists down to `_MAX_DEPTH`, truncate strings."""
    if isinstance(value, dict):
        if depth >= _MAX_DEPTH:
            return "[complex data]"
        return {k: "[redacted]" if _is_sensitive(k) else _redact_value(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if depth >= _MAX_DEPTH:
            return "[complex data]"
        return [_redact_value(item, depth + 1) for item in value]
    return _truncate_string(value)


def redact_properties(properties: Any) -> Any:
    """Redact event properties before they leave the process.

    Args:
        properties (Any): Event properties dict (or a scalar, or None).

    Returns:
        Any: `{}` for None, the truncated scalar for a non-dict, or a copy of the
            dict with sensitive keys replaced by "[redacted]" at every level,
            strings truncated, and anything nested deeper than `_MAX_DEPTH`
            collapsed to "[complex data]".
    """
    if properties is None:
        return {}
    if not isinstance(properties, dict):
        return _truncate_string(properties)
    return {key: "[redacted]" if _is_sensitive(key) else _redact_value(value, 0) for key, value in properties.items()}

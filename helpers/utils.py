import os
import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

import markdown
from flask import request

from models import Learner, Volunteer

__all__ = [
    "clamp_page",
    "day_bounds",
    "get_pair_display_name",
    "inject_now",
    "inject_version",
    "is_cross_site_write",
    "normalize_subject_bucket",
    "render_markdown",
    "safe_local_path",
    "same_site_referrer_path",
    "tokenize_text",
    "utcnow_naive",
    "wants_fragment",
    "wants_json",
]

# A same-page quick-action route (regenerate code, delete row, set password, ...) branches on
# wants_json() at the very end: `jsonify(success=bool, message=str, ...)` when true,
# `redirect(...)` + `flash(...)` otherwise. Keep both branches: the same route is hit from an
# AJAX form (stays on the page, reads the JSON) and from a plain form (navigates, reads the flash).
def wants_json() -> bool:
    """Whether the request came from the header's `form.js-ajax-form` fetch handler."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

def safe_local_path(value: str | None) -> str | None:
    """`value` if it is a same-site path (a safe `next=` redirect target), else None.

    Refuses backslashes and control characters as well as `//host`: browsers read `/\\host` as
    `//host`, and drop tab and newline from a URL before parsing it, so `/<TAB>/host` is too.
    """
    if not value or not value.startswith("/") or "\\" in value:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    # Rebuilt behind a constant "/" so the result is a path by construction, not just by the checks above.
    return "/" + value[1:]

def same_site_referrer_path() -> str | None:
    """The path + query of the request's Referer when it is this site, else None."""
    referrer = urlsplit(request.referrer or "")
    if referrer.netloc != request.host:
        return None
    path = referrer.path + (f"?{referrer.query}" if referrer.query else "")
    return safe_local_path(path)

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

def is_cross_site_write() -> bool:
    """Whether this is a write a browser sent from another site — the CSRF guard beside SameSite=Lax.

    Returns:
        bool: True when the request should be refused with a 403.
    """
    if request.method not in _UNSAFE_METHODS:
        return False
    # `Origin: null` is a sandboxed or data: page. No Origin and no Referer is a
    # non-browser client (the Stripe webhook), which carries no session to abuse.
    origin = request.headers.get("Origin")
    if origin == "null":
        return True
    source = origin or request.referrer
    if not source:
        return False
    return urlsplit(source).netloc != request.host

def wants_fragment() -> bool:
    """True when a pagination/results swap fetch wants a partial, not the full page.

    Returns:
        bool: Whether the current request wants a fragment response.
    """
    return request.headers.get("X-Fragment") == "1"

def utcnow_naive() -> datetime:
    """Naive UTC timestamp, matching the naive TIMESTAMP columns DB comparisons need. Replaces deprecated datetime.utcnow().

    Returns:
        datetime: Current UTC time with no tzinfo attached.
    """
    return datetime.now(UTC).replace(tzinfo=None)

def day_bounds(day: date | datetime) -> tuple[datetime, datetime]:
    """(start, end) naive datetimes spanning one calendar day, for filtering a DateTime column by date (never `== date` — misses non-midnight rows).

    Args:
        day (date | datetime): Any date or datetime on the target calendar day.

    Returns:
        tuple[datetime, datetime]: Midnight of that day, and midnight of the next.
    """
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)

def clamp_page(total: int, page_size: int, arg: str = "page") -> tuple[int, int]:
    """(page, page_count), both >= 1 — `?{arg}=` clamped so it never 500s."""
    page_count = max(1, -(-total // page_size))
    page = max(1, request.args.get(arg, 1, type=int))
    return min(page, page_count), page_count

def get_pair_display_name(learner: Learner, volunteer: Volunteer | None) -> str:
    """Returns a formatted name for a learner-volunteer pair.

    Args:
        learner (Learner): The learner in the pair.
        volunteer (Volunteer | None): The matched volunteer, or None if unmatched.

    Returns:
        str: "<learner name> & <volunteer name>".
    """
    learner_name = learner.name or learner.username
    if volunteer:
        volunteer_name = volunteer.name or (volunteer.email.split("@")[0] if volunteer.email else "Volunteer")
    else:
        volunteer_name = "Volunteer"
    return f"{learner_name} & {volunteer_name}"

def normalize_subject_bucket(subject_name: str | None) -> str:
    """Normalizes subject names into standard buckets for matching/recommendations.

    Args:
        subject_name (str | None): Raw subject name.

    Returns:
        str: "language" for any grammar/english/language/greek subject, else
            the lowercased/stripped name, or "general" if empty.
    """
    value = (subject_name or "").strip().lower()
    if any(token in value for token in ["grammar", "english", "language", "greek"]):
        return "language"
    return value or "general"

def tokenize_text(text: str | None) -> list[str]:
    """Tokenizes text for keyword matching.

    Args:
        text (str | None): Text to tokenize.

    Returns:
        list[str]: Lowercased alphanumeric tokens of length >= 3.
    """
    return [
        token
        for token in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(token) >= 3
    ]

def render_markdown(text: str | None) -> str:
    """Converts markdown text to HTML with support for GitHub-style tables and code blocks.

    Args:
        text (str | None): Markdown source.

    Returns:
        str: Rendered HTML, or "" if text is empty.
    """
    if not text:
        return ""
    return markdown.markdown(text, extensions=["fenced_code", "tables"])

def inject_now() -> dict[str, int]:
    """Context processor helper for current year.

    Returns:
        dict[str, int]: {"year": <current UTC year>}.
    """
    return {"year": utcnow_naive().year}

def inject_site_settings() -> dict[str, str]:
    """Context processor helper for the per-deploy values public pages show.

    Returns:
        dict[str, str]: {"contact_email": ..., "github_repo_url": ...}, each "" when not configured.
    """
    from settings import get_settings

    settings = get_settings()
    return {"contact_email": settings.contact_email, "github_repo_url": settings.github_repo_url.rstrip("/")}


def inject_version() -> dict[str, str]:
    """Context processor helper for the deployed build's git commit SHA (baked in at Docker build time; "dev" locally).

    Returns:
        dict[str, str]: {"app_version": <short SHA or "dev">, "app_version_full": <full SHA>}.
    """
    sha = os.environ.get("GIT_SHA", "dev")
    return {"app_version": sha[:7] if sha != "dev" else sha, "app_version_full": sha}

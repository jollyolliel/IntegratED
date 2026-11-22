"""Teacher AI assistant endpoints.

`POST /assistant/message` streams; everything else is ordinary JSON.

## Streaming traps this stack imposes

- **Read every request-bound value before returning the generator.**
  `stream_with_context` keeps the context alive, but `teardown_request` and
  `clear_request_context` still run on the way out. The loop is handed a plain
  `teacher_id` and re-fetches inside.
- **`Cache-Control: no-store` is set here explicitly.** `main.py`'s global
  default only covers `GET`, and this endpoint is a `POST`.
- **`text/event-stream` is not in flask-compress's default `COMPRESS_MIMETYPES`**,
  so the stream passes through uncompressed with no config change.
  `direct_passthrough` and `X-Accel-Buffering: no` handle proxies.

Layout:
  _conversation.py  thread lookup/creation, history list
  _stream.py        the SSE message stream
  _changes.py       staged-change review (apply/reject/update/apply-all)
"""

import logging

from flask import Blueprint, abort
from flask_login import login_required

from extensions import limiter
from helpers.current_user import current_teacher as current_user

logger = logging.getLogger(__name__)

assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")
limiter.limit("20 per minute")(assistant_bp)

MAX_MESSAGE_CHARS = 2000


@assistant_bp.before_request
@login_required
def limit_to_teachers():
    if current_user.user_type != "teacher":
        abort(403)


# Imported at the bottom so each submodule's `@assistant_bp.route(...)`
# decorators run and register against the already-created `assistant_bp`.
from helpers.ai import loop  # noqa: F401
from routes.assistant import _changes, _conversation, _stream  # noqa: F401

# Kept importable at the package root for backward compatibility — tests do
# `from routes.assistant import _frame` and monkeypatch `assistant.loop.run_turn`.
from routes.assistant._stream import _frame  # noqa: F401

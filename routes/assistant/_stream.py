import json

from flask import Response, jsonify, request, stream_with_context

from extensions import db
from helpers.ai import loop
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from helpers.i18n import get_current_lang
from routes.assistant import MAX_MESSAGE_CHARS, assistant_bp, logger
from routes.assistant._conversation import _latest_conversation, _owned_conversation


def _frame(event):
    """One SSE frame, already encoded."""
    # direct_passthrough skips Werkzeug's iter_encoded(), so nothing converts a
    # str on its way to the WSGI server — every yield in the stream is bytes.
    return f"data: {json.dumps(event)}\n\n".encode()


@assistant_bp.route("/message", methods=["POST"])
def assistant_message():
    text = (request.form.get("message") or "").strip()
    if not text:
        return jsonify(success=False, message="Type a question first."), 400
    text = text[:MAX_MESSAGE_CHARS]

    # Everything request-bound is captured HERE, before the generator exists.
    teacher_id = current_user.id
    lang = get_current_lang()
    requested_id = request.form.get("conversation_id", type=int)
    conversation = _owned_conversation(current_user, requested_id) if requested_id else None
    if conversation is None:
        conversation = _latest_conversation(current_user, create=True)
    conversation_id = conversation.id

    capture_event(str(teacher_id), "assistant_message_sent",
                  properties={"chars": len(text)})

    def generate():
        # A comment frame straight away: intermediaries that buffer until first
        # byte release the connection, and the panel can show its spinner.
        yield b": open\n\n"
        try:
            for event in loop.run_turn(teacher_id, conversation_id, text, lang):
                if event.get("type") == "step" and event.get("done"):
                    capture_event(str(teacher_id), "assistant_tool_called", properties={
                        "tool": event.get("tool"),
                        "ms": event.get("ms"),
                        "ok": event.get("ok"),
                    })
                elif event.get("type") == "error":
                    capture_event(str(teacher_id), "assistant_error", properties={
                        "provider": event.get("provider"),
                        "message": (event.get("message") or "")[:200],
                    })
                elif event.get("type") == "changes":
                    for change in event.get("changes") or []:
                        capture_event(str(teacher_id), "assistant_change_staged",
                                      properties={"tool": change.get("tool"),
                                                  "entity": change.get("entity")})
                yield _frame(event)
        except Exception:  # noqa: BLE001 — a raise here truncates the stream
            logger.exception("Assistant stream failed")
            db.session.rollback()
            yield _frame({"type": "error", "message": "Something went wrong on my side."})
            yield _frame({"type": "done"})
        finally:
            db.session.remove()

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        direct_passthrough=True,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response

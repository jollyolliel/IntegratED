from flask import abort, jsonify, request

from extensions import db
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from models import AssistantConversation
from routes.assistant import assistant_bp

MAX_HISTORY_CONVERSATIONS = 30


def _latest_conversation(teacher, create=False):
    conversation = db.session.scalar(
        db.select(AssistantConversation)
        .filter_by(teacher_id=teacher.id)
        .order_by(AssistantConversation.updated_at.desc(),
                  AssistantConversation.id.desc())
    )
    if conversation is None and create:
        conversation = AssistantConversation(teacher_id=teacher.id)
        db.session.add(conversation)
        db.session.commit()
    return conversation


def _owned_conversation(teacher, conversation_id):
    """A specific thread, only if it belongs to this teacher."""
    # The History tab lets a teacher open any past thread of their own, never
    # someone else's.
    conversation = db.session.get(AssistantConversation, conversation_id)
    if conversation is None or conversation.teacher_id != teacher.id:
        return None
    return conversation


@assistant_bp.route("/conversation")
def assistant_conversation():
    """The open thread, so a reopened panel redraws what was already said."""
    # Fetched exactly once per panel open with no `id`, which is what makes
    # that case the honest place to record `assistant_opened` — no extra
    # beacon endpoint. `?id=` reopens a past thread and isn't a fresh open.
    requested_id = request.args.get("id", type=int)
    if requested_id:
        conversation = _owned_conversation(current_user, requested_id)
        if conversation is None:
            abort(404)
    else:
        capture_event(str(current_user.id), "assistant_opened")
        conversation = _latest_conversation(current_user)
    if conversation is None:
        return jsonify(conversation_id=None, messages=[])
    return jsonify(
        conversation_id=conversation.id,
        messages=[
            {
                "role": message.role,
                "content": message.content or "",
                "tool_events": message.tool_events or [],
            }
            for message in conversation.messages
        ],
    )


@assistant_bp.route("/conversations")
def assistant_conversations():
    """Past threads for the History tab, most recent first."""
    # `title` is set from the first message once the turn completes
    # (helpers/ai/loop.py), so a conversation with no reply yet falls back to "".
    conversations = db.session.scalars(
        db.select(AssistantConversation)
        .filter_by(teacher_id=current_user.id)
        .order_by(AssistantConversation.updated_at.desc(),
                  AssistantConversation.id.desc())
        .limit(MAX_HISTORY_CONVERSATIONS)
    ).all()
    return jsonify(conversations=[
        {
            "id": conversation.id,
            "title": conversation.title or "",
            "updated_at": conversation.updated_at.isoformat(),
            "preview": (conversation.messages[-1].content
                       if conversation.messages else "") or "",
        }
        for conversation in conversations
    ])


@assistant_bp.route("/conversation/new", methods=["POST"])
def assistant_new_conversation():
    conversation = AssistantConversation(teacher_id=current_user.id)
    db.session.add(conversation)
    db.session.commit()
    return jsonify(success=True, conversation_id=conversation.id)

"""The agent loop: provider <-> tools, emitting events as it goes.

`run_turn` is a generator of plain dicts, which `routes/assistant.py` renders as
SSE frames. It takes a `teacher_id`, not a user object — the caller must not
hand request-bound state to something that outlives the request context.

Two hard caps, both about the 1 worker x 8 threads budget: a wall-clock deadline
comfortably inside gunicorn's `--timeout 60`, and a maximum number of
tool-calling rounds. A stuck run ends with an apology, never with a pinned
thread.
"""

import functools
import logging
import time
from collections.abc import Generator
from typing import Any

from extensions import db
from helpers.ai import registry, scope, staging
from helpers.ai.provider import ProviderError
from helpers.ai.tools import ToolContext, all_tools, get_tool, tool_specs
from helpers.refusal import Refusal
from models import AssistantConversation, AssistantMessage, Teacher

logger = logging.getLogger(__name__)

# A real question costs several rounds: pick a tool, correct a bad argument,
# then fetch detail per learner. Six cut turns off mid-exploration. The wall
# clock is the actual safety net, not this.
MAX_ITERATIONS = 12
# Must leave room for one more provider call inside gunicorn's `--timeout 60`:
# deadline + gemini.REQUEST_TIMEOUT_SECONDS is the true worst case.
TURN_DEADLINE_SECONDS = 30
# How many earlier messages of the thread are replayed to the model.
HISTORY_TURNS = 12

# Sent when the budget runs out. Answering from partial data beats an apology —
# by this point the tools have usually already returned enough.
FINALIZE_NUDGE = (
    "\n\nYou have no budget left for more tool calls. Answer now from what the "
    "tools have already returned. Say which part is incomplete rather than "
    "asking for another query."
)

OUT_OF_BUDGET = (
    "I ran out of time on that one. Try narrowing it — one learner, or one week."
)

SYSTEM_PROMPT = """\
You are the IntegratED teaching assistant, helping one teacher run a
youth-to-youth learning programme for refugee learners, many of whom cannot
read in any language.

Today is {today}. You are talking to {teacher_name}.

HOW YOU WORK
- You have no memory of the database. Everything you say about learners,
  volunteers, attendance or worksheets must come from a tool call in this turn.
  Never guess a name, a number or a date.
- Start from `list_entities` / `describe_entity` when you are unsure what data
  exists. The schema is read live, so it is always current.
- Prefer the purpose-built tools over raw queries when one fits:
  `pair_summaries`, `learner_snapshot`, `progress_between`,
  `attendance_summary`, `match_score`, `preview_auto_match`. They apply the
  same logic the teacher's own screens use.
- **When one of those already answers the question, answer from it.** Do not
  re-derive the same thing from raw tables to double-check — you have a small
  budget of tool calls and re-checking spends it for nothing.
- Entity names are the ones `list_entities` returns. If a tool reports a bad
  argument, fix that argument and move on; do not switch approach.
- Every read is already restricted to this teacher's own people. You cannot see
  anyone else's, and you should not try.

WRITES
- You never change anything directly. The write tools stage a proposal that the
  teacher reviews and applies themselves.
- Say plainly what you have proposed and that it is waiting for their approval.
  Do not claim something has been done.
- Propose a write only when the teacher asked for one. Answering a question is
  not a reason to change data.

ANSWERING
- Be brief and concrete. Name the learners, give the numbers, say the dates.
- Format in Markdown: short paragraphs, hyphen lists, **bold** for names and
  numbers. Use a table only when comparing several people on the same fields.
- When a tool tells you a limitation, pass it on rather than papering over it.
- If nothing matched, say so — an empty result is an answer.
- Reply in {language_name}.
"""

LANGUAGE_NAMES = {
    "en": "English", "el": "Greek", "ar": "Arabic", "tr": "Turkish",
    "es": "Spanish", "fr": "French", "uk": "Ukrainian", "fa": "Farsi",
    "ps": "Pashto", "so": "Somali", "rhg": "Rohingya", "ti": "Tigrinya",
    "sw": "Swahili",
}


def build_system_prompt(teacher: Teacher, lang: str = "en") -> str:
    """Render the assistant's system prompt for one teacher/language.

    Args:
        teacher (Teacher): The teacher this turn is for.
        lang (str): UI language code, used to pick the reply language.

    Returns:
        str: The formatted system prompt.
    """
    from helpers.utils import utcnow_naive

    return SYSTEM_PROMPT.format(
        today=utcnow_naive().date().isoformat(),
        teacher_name=teacher.name or teacher.email or "the teacher",
        language_name=LANGUAGE_NAMES.get(lang, "English"),
    )


def transcript_for(conversation: AssistantConversation) -> list[dict[str, Any]]:
    """Stored messages -> the neutral transcript the provider consumes.

    Args:
        conversation (AssistantConversation): Conversation to read history from.

    Returns:
        list[dict[str, Any]]: The last `HISTORY_TURNS` user/assistant messages,
            as `{"role", "content"}` dicts.
    """
    messages = []
    for message in (conversation.messages or [])[-HISTORY_TURNS:]:
        if message.role not in ("user", "assistant"):
            continue
        messages.append({"role": message.role, "content": message.content or ""})
    return messages


@functools.cache
def _classification_logged() -> None:
    """Log the FK-graph scope classification exactly once per process (the cache is the latch;
    tests/conftest.py clears it between tests)."""
    scope.log_classification()


def run_turn(teacher_id: int, conversation_id: int, user_text: str, lang: str = "en") -> Generator[dict[str, Any], None, None]:
    """Yield event dicts for one exchange.

    Events: {"type": "step"|"delta"|"changes"|"error"|"done", ...}

    Args:
        teacher_id (int): The teacher this turn belongs to.
        conversation_id (int): The conversation to append to.
        user_text (str): The teacher's message.
        lang (str): UI language code for the reply.

    Returns:
        Generator[dict[str, Any], None, None]: Stream of event dicts consumed
            by `routes/assistant.py` as SSE frames.
    """
    _classification_logged()

    teacher = db.session.get(Teacher, teacher_id)
    if teacher is None:
        yield {"type": "error", "message": "Your account could not be loaded."}
        yield {"type": "done"}
        return

    conversation = db.session.get(AssistantConversation, conversation_id)
    if conversation is None or conversation.teacher_id != teacher.id:
        yield {"type": "error", "message": "That conversation could not be loaded."}
        yield {"type": "done"}
        return

    if not conversation.title:
        # Feeds the History tab's list — first message, not the reply, since
        # the reply can be long and the question is what the teacher recognizes.
        conversation.title = (
            user_text[:57] + "…" if len(user_text) > 57 else user_text
        )
    db.session.add(AssistantMessage(
        conversation_id=conversation.id, role="user", content=user_text
    ))
    db.session.commit()

    ctx = ToolContext(teacher=teacher, conversation_id=conversation.id)
    messages = transcript_for(conversation)
    specs = tool_specs()
    system = build_system_prompt(teacher, lang)

    # Looked up through the module, not a bound name, so tests can swap the
    # provider by patching `helpers.ai.registry.get_provider`.
    provider = registry.get_provider()
    deadline = time.monotonic() + TURN_DEADLINE_SECONDS
    tool_events = []
    answer = ""

    exhausted = False
    for iteration in range(MAX_ITERATIONS):
        if time.monotonic() > deadline:
            exhausted = True
            break

        try:
            reply = provider.complete(system=system, messages=messages, tools=specs)
        except ProviderError as exc:
            logger.warning("Assistant provider failed: %s", exc)
            yield {"type": "error", "message": str(exc), "provider": provider.name}
            yield {"type": "done"}
            return

        if getattr(provider, "downgraded", False):
            yield {"type": "step", "label": "Switched to the backup model",
                   "kind": "notice"}

        if not reply.tool_calls:
            answer = reply.text or "I could not find anything to answer that with."
            break

        messages.append({
            "role": "assistant",
            "content": reply.text or "",
            "tool_calls": reply.tool_calls,
            # Carried so the provider can replay its own turn verbatim rather
            # than have it rebuilt — see ProviderReply.provider_turn.
            "provider_turn": reply.provider_turn,
        })

        for call in reply.tool_calls:
            tool = get_tool(call.name)
            label = tool.human_label(call.arguments) if tool else call.name
            yield {"type": "step", "label": label, "tool": call.name}

            started = time.monotonic()
            try:
                if tool is None:
                    raise Refusal(f"No tool named {call.name!r}.")
                result = tool.fn(ctx, **(call.arguments or {}))
                ok = True
            except (ValueError, LookupError, PermissionError) as exc:
                # Handed back to the model as data, not raised: a bad argument
                # is something it can correct on the next round.
                result = {"error": str(exc)}
                ok = False
            except Exception:
                logger.exception("Assistant tool %s failed", call.name)
                db.session.rollback()
                result = {"error": f"{call.name} failed unexpectedly."}
                ok = False

            elapsed_ms = int((time.monotonic() - started) * 1000)
            tool_events.append({"tool": call.name, "label": label,
                                "ms": elapsed_ms, "ok": ok})
            yield {"type": "step", "label": label, "tool": call.name,
                   "done": True, "ok": ok, "ms": elapsed_ms}

            messages.append({
                "role": "tool", "tool_call_id": call.id,
                "name": call.name, "content": result,
            })
    else:
        exhausted = True

    if exhausted:
        # One last call with no tools offered, so the only thing it can produce
        # is prose. Far better than an apology — the data is already in hand.
        yield {"type": "step", "label": "Wrapping up", "kind": "notice"}
        try:
            final = provider.complete(
                system=system + FINALIZE_NUDGE, messages=messages, tools=[]
            )
            answer = final.text or OUT_OF_BUDGET
        except ProviderError as exc:
            logger.warning("Assistant finalize call failed: %s", exc)
            answer = OUT_OF_BUDGET

    if answer:
        yield {"type": "delta", "text": answer}

    db.session.add(AssistantMessage(
        conversation_id=conversation.id, role="assistant",
        content=answer, tool_events=tool_events,
    ))
    # Stamped explicitly: `onupdate` only fires when a column on this row is
    # itself dirty, and adding a child message does not dirty the parent.
    from helpers.utils import utcnow_naive

    conversation.updated_at = utcnow_naive()
    db.session.commit()

    pending = staging.pending_changes(teacher)
    yield {"type": "changes",
           "changes": [staging.change_payload(c) for c in pending]}
    yield {"type": "done", "tool_events": tool_events}


def tool_catalogue() -> list[dict[str, Any]]:
    """Registered tools, for the docs check and the startup log.

    Returns:
        list[dict[str, Any]]: Each tool's `{"name", "writes"}`, sorted by name.
    """
    return sorted(
        ({"name": t.name, "writes": t.writes} for t in all_tools().values()),
        key=lambda t: t["name"],
    )

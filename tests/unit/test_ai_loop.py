"""The agent loop, driven by a scripted provider.

`run_turn` is a generator of SSE-shaped event dicts. Every branch worth caring
about — a tool round trip, a bad tool argument, the iteration cap, a provider
outage — is deterministic once the provider is a double.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.support.ai import FakeProvider, answer, tool_turn, use_fake_provider
from tests.support.factories import (
    make_assistant_conversation,
    make_learner,
    make_school,
    make_teacher,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def loop(app):
    from helpers.ai import loop as module

    with app.app_context():
        yield module


@pytest.fixture
def thread(db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school, name="Ms Okafor")
    conversation = make_assistant_conversation(db_session, teacher, title=None)
    return {"school": school, "teacher": teacher, "conversation": conversation}


def _events(loop, thread, text="how many learners do I have?", **kwargs):
    return list(
        loop.run_turn(thread["teacher"].id, thread["conversation"].id, text, **kwargs)
    )


def _types(events):
    return [event["type"] for event in events]


# ── system prompt ────────────────────────────────────────────────────────────


def test_the_system_prompt_names_the_teacher(loop, db_session, thread):
    prompt = loop.build_system_prompt(thread["teacher"])

    assert "Ms Okafor" in prompt


def test_the_system_prompt_names_the_requested_language(loop, db_session, thread):
    assert "Arabic" in loop.build_system_prompt(thread["teacher"], lang="ar")


def test_an_unknown_language_falls_back_to_english(loop, db_session, thread):
    assert "English" in loop.build_system_prompt(thread["teacher"], lang="zz")


def test_a_teacher_with_no_name_falls_back_to_their_email(loop, db_session):
    school = make_school(db_session)
    nameless = make_teacher(db_session, school, name=None, email="head@example.com")

    assert "head@example.com" in loop.build_system_prompt(nameless)


# ── transcript ───────────────────────────────────────────────────────────────


def test_the_transcript_keeps_only_user_and_assistant_turns(loop, db_session, thread):
    from tests.support.factories import make_assistant_message

    conversation = thread["conversation"]
    make_assistant_message(db_session, conversation, role="user", content="hi")
    make_assistant_message(db_session, conversation, role="assistant", content="hello")
    make_assistant_message(db_session, conversation, role="tool", content="{}")
    db_session.refresh(conversation)

    transcript = loop.transcript_for(conversation)

    assert [m["role"] for m in transcript] == ["user", "assistant"]


def test_the_transcript_is_capped_to_the_recent_history(loop, db_session, thread):
    from tests.support.factories import make_assistant_message

    conversation = thread["conversation"]
    for index in range(loop.HISTORY_TURNS + 6):
        make_assistant_message(db_session, conversation, role="user", content=str(index))
    db_session.refresh(conversation)

    assert len(loop.transcript_for(conversation)) <= loop.HISTORY_TURNS


# ── bad addressing ───────────────────────────────────────────────────────────


def test_an_unknown_teacher_yields_an_error(loop, db_session, thread):
    events = list(loop.run_turn(999_999, thread["conversation"].id, "hi"))

    assert _types(events) == ["error", "done"]


def test_another_teachers_conversation_is_refused(loop, db_session, thread, monkeypatch):
    outsider = make_teacher(db_session, thread["school"])

    events = list(loop.run_turn(outsider.id, thread["conversation"].id, "hi"))

    assert _types(events) == ["error", "done"]


# ── a plain answer ───────────────────────────────────────────────────────────


def test_a_plain_answer_is_streamed_and_persisted(loop, db_session, thread, monkeypatch):
    from models import AssistantMessage

    use_fake_provider(monkeypatch, FakeProvider([answer("You have 3 learners.")]))

    events = _events(loop, thread)

    assert _types(events) == ["delta", "changes", "done"]
    assert events[0]["text"] == "You have 3 learners."
    stored = db_session.scalars(select(AssistantMessage).filter_by(role="assistant")).one()
    assert stored.content == "You have 3 learners."


def test_the_user_message_is_persisted_before_the_model_runs(loop, db_session, thread, monkeypatch):
    from models import AssistantMessage

    use_fake_provider(monkeypatch, FakeProvider([answer("ok")]))

    _events(loop, thread, text="what happened last week?")

    stored = db_session.scalars(select(AssistantMessage).filter_by(role="user")).one()
    assert stored.content == "what happened last week?"


def test_the_first_message_titles_an_untitled_conversation(loop, db_session, thread, monkeypatch):
    use_fake_provider(monkeypatch, FakeProvider([answer("ok")]))

    _events(loop, thread, text="who missed last session?")

    db_session.refresh(thread["conversation"])
    assert thread["conversation"].title == "who missed last session?"


def test_a_long_first_message_is_truncated_for_the_title(loop, db_session, thread, monkeypatch):
    use_fake_provider(monkeypatch, FakeProvider([answer("ok")]))

    _events(loop, thread, text="x" * 200)

    db_session.refresh(thread["conversation"])
    assert len(thread["conversation"].title) <= 58
    assert thread["conversation"].title.endswith("…")


def test_an_empty_reply_still_produces_an_answer(loop, db_session, thread, monkeypatch):
    use_fake_provider(monkeypatch, FakeProvider([answer("")]))

    events = _events(loop, thread)

    assert events[0]["type"] == "delta"
    assert events[0]["text"]


def test_the_conversation_timestamp_is_stamped_explicitly(loop, db_session, thread, monkeypatch):
    """Adding a child message does not dirty the parent, so onupdate won't fire."""

    use_fake_provider(monkeypatch, FakeProvider([answer("ok")]))
    before = thread["conversation"].updated_at

    _events(loop, thread)

    db_session.refresh(thread["conversation"])
    assert thread["conversation"].updated_at >= before


# ── tool round trip ──────────────────────────────────────────────────────────


def test_a_tool_call_emits_start_and_finish_steps(loop, db_session, thread, monkeypatch):
    make_learner(db_session, thread["school"], thread["teacher"])
    use_fake_provider(
        monkeypatch,
        FakeProvider([
            tool_turn("count_records", {"entity": "Learner"}),
            answer("You have 1 learner."),
        ]),
    )

    events = _events(loop, thread)

    steps = [event for event in events if event["type"] == "step"]
    assert len(steps) == 2
    assert steps[0]["tool"] == "count_records"
    assert steps[1]["done"] is True
    assert steps[1]["ok"] is True


def test_the_tool_result_is_fed_back_to_the_model(loop, db_session, thread, monkeypatch):
    make_learner(db_session, thread["school"], thread["teacher"])
    provider = use_fake_provider(
        monkeypatch,
        FakeProvider([
            tool_turn("count_records", {"entity": "Learner"}),
            answer("done"),
        ]),
    )

    _events(loop, thread)

    second_call = provider.calls[1]["messages"]
    tool_message = next(m for m in second_call if m["role"] == "tool")
    assert tool_message["name"] == "count_records"
    assert tool_message["content"]["count"] == 1


def test_tool_events_are_recorded_on_the_stored_reply(loop, db_session, thread, monkeypatch):
    make_learner(db_session, thread["school"], thread["teacher"])
    use_fake_provider(
        monkeypatch,
        FakeProvider([
            tool_turn("count_records", {"entity": "Learner"}),
            answer("done"),
        ]),
    )

    events = _events(loop, thread)

    from models import AssistantMessage

    stored = db_session.scalars(select(AssistantMessage).filter_by(role="assistant")).one()
    assert [event["tool"] for event in stored.tool_events] == ["count_records"]
    assert events[-1]["tool_events"]


def test_an_unknown_tool_is_reported_to_the_model_rather_than_raised(loop, db_session, thread, monkeypatch):
    provider = use_fake_provider(
        monkeypatch,
        FakeProvider([tool_turn("no_such_tool"), answer("sorry")]),
    )

    events = _events(loop, thread)

    finish = next(e for e in events if e["type"] == "step" and e.get("done"))
    assert finish["ok"] is False
    tool_message = next(m for m in provider.calls[1]["messages"] if m["role"] == "tool")
    assert "error" in tool_message["content"]


def test_a_bad_tool_argument_is_handed_back_as_data(loop, db_session, thread, monkeypatch):
    """The model can correct itself next round, so this must not end the turn."""

    provider = use_fake_provider(
        monkeypatch,
        FakeProvider([
            tool_turn("query_records", {"entity": "Donation"}),
            answer("I cannot see donations."),
        ]),
    )

    events = _events(loop, thread)

    assert events[-1]["type"] == "done"
    tool_message = next(m for m in provider.calls[1]["messages"] if m["role"] == "tool")
    assert "error" in tool_message["content"]


def test_a_staged_write_is_reported_in_the_changes_event(loop, db_session, thread, monkeypatch):
    from tests.support.factories import make_volunteer

    volunteer = make_volunteer(db_session, thread["school"], thread["teacher"])
    use_fake_provider(
        monkeypatch,
        FakeProvider([
            tool_turn("set_volunteer_capacity", {"volunteer_id": volunteer.id, "capacity": 3}),
            answer("Proposed."),
        ]),
    )

    events = _events(loop, thread)

    changes = next(event for event in events if event["type"] == "changes")
    assert len(changes["changes"]) == 1
    assert changes["changes"][0]["tool"] == "set_volunteer_capacity"


# ── failure and budget ───────────────────────────────────────────────────────


def test_a_provider_outage_ends_the_turn_cleanly(loop, db_session, thread, monkeypatch):
    from helpers.ai.provider import ProviderError

    use_fake_provider(monkeypatch, FakeProvider(error=ProviderError("upstream is down")))

    events = _events(loop, thread)

    assert _types(events) == ["error", "done"]
    assert "upstream is down" in events[0]["message"]


def test_the_iteration_cap_forces_a_final_prose_answer(loop, db_session, thread, monkeypatch):
    """A model that only ever calls tools must still produce an answer."""

    make_learner(db_session, thread["school"], thread["teacher"])
    replies = [
        tool_turn("count_records", {"entity": "Learner"}, call_id=f"c{i}")
        for i in range(loop.MAX_ITERATIONS)
    ]
    replies.append(answer("Wrapped up."))
    provider = use_fake_provider(monkeypatch, FakeProvider(replies))

    events = _events(loop, thread)

    notices = [e for e in events if e["type"] == "step" and e.get("kind") == "notice"]
    assert notices, "expected a wrap-up notice once the budget ran out"
    assert events[-1]["type"] == "done"
    # The finalize call offers no tools, so prose is the only possible output.
    assert provider.calls[-1]["tools"] == []


def test_a_failed_finalize_call_falls_back_to_a_fixed_message(loop, db_session, thread, monkeypatch):
    from helpers.ai.provider import ProviderError

    make_learner(db_session, thread["school"], thread["teacher"])

    class FailsOnFinalize(FakeProvider):
        def complete(self, *, system, messages, tools):
            if not tools:
                raise ProviderError("finalize failed")
            return super().complete(system=system, messages=messages, tools=tools)

    replies = [
        tool_turn("count_records", {"entity": "Learner"}, call_id=f"c{i}")
        for i in range(loop.MAX_ITERATIONS)
    ]
    use_fake_provider(monkeypatch, FailsOnFinalize(replies))

    events = _events(loop, thread)

    delta = next(e for e in events if e["type"] == "delta")
    assert delta["text"] == loop.OUT_OF_BUDGET


# ── catalogue ────────────────────────────────────────────────────────────────


def test_the_tool_catalogue_marks_which_tools_write(loop):
    catalogue = {entry["name"]: entry["writes"] for entry in loop.tool_catalogue()}

    assert catalogue["query_records"] is False
    assert catalogue["match_pair"] is True

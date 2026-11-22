"""A scripted LLM provider, so the agent loop can be driven without a network.

`helpers/ai/provider.LLMProvider` is a one-method ABC, which makes the whole of
`helpers/ai/loop.py` — the iteration cap, the turn deadline, the out-of-budget
path, the tool round-trip — reachable from a plain unit test.
"""

from __future__ import annotations

from helpers.ai.provider import LLMProvider, ProviderError, ProviderReply, ToolCall


class FakeProvider(LLMProvider):
    """Replays a fixed list of replies, one per `complete()` call.

    Records every call it received in `calls`, so a test can assert on the
    system prompt, the transcript the loop built, or the tool catalogue that
    was offered.
    """

    name = "fake"

    def __init__(self, replies=None, *, error=None):
        self.replies = list(replies or [])
        self.error = error
        self.calls: list[dict] = []

    def complete(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": list(messages), "tools": list(tools)})
        if self.error is not None:
            raise self.error
        if not self.replies:
            # Running dry means the loop asked for more turns than the test
            # scripted. Answering instead of raising keeps the failure in the
            # test's own assertion rather than in this double.
            return ProviderReply(text="(no more scripted replies)", finish_reason="stop")
        return self.replies.pop(0)


def answer(text):
    """A final assistant turn."""

    return ProviderReply(text=text, finish_reason="stop")


def tool_turn(name, arguments=None, *, call_id="call-1", text=""):
    """An assistant turn that asks for one tool call."""

    return ProviderReply(
        text=text,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments or {})],
        finish_reason="tool_calls",
    )


def use_fake_provider(monkeypatch, provider):
    """Point every `get_provider()` lookup at `provider`.

    Patches the name where it is *used* (`helpers.ai.loop`) as well as the
    registry itself, so it holds regardless of how the caller imported it.
    """

    from helpers.ai import loop, registry

    monkeypatch.setattr(registry, "get_provider", lambda name=None: provider)
    if hasattr(loop, "get_provider"):
        monkeypatch.setattr(loop, "get_provider", lambda name=None: provider)
    return provider


__all__ = [
    "FakeProvider",
    "ProviderError",
    "ProviderReply",
    "ToolCall",
    "answer",
    "tool_turn",
    "use_fake_provider",
]

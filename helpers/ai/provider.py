"""Neutral LLM interface. No vendor name appears in this file.

A transcript is a list of plain dicts:

    {"role": "user",      "content": "who missed last session?"}
    {"role": "assistant", "content": "", "tool_calls": [ToolCall, ...]}
    {"role": "tool",      "tool_call_id": "...", "name": "...", "content": {...}}

Each provider implementation owns the translation to and from its own wire
format in both directions — nothing above this layer knows what that looks
like.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    """One callable exposed to the model. `parameters` is JSON Schema."""
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    """One tool invocation requested by the model."""
    id: str
    name: str
    arguments: dict


@dataclass
class ProviderReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # "stop" | "tool_calls" | "length" | "error"
    finish_reason: str = "stop"
    raw: Any = None
    #: Opaque, provider-owned rendering of this assistant turn. The loop stores
    #: it on the transcript and the provider replays it **verbatim** instead of
    #: rebuilding the turn from `text` + `tool_calls`.
    #:
    #: Reconstructing loses per-part metadata the provider requires back — a
    #: reasoning model that stamps its tool calls and rejects the next request
    #: when the stamp is missing. Round-tripping the original is the only way to
    #: keep that opaque and out of this layer.
    provider_turn: Any = None


class ProviderError(RuntimeError):
    """The model could not be reached or refused the request.

    Raised instead of leaking a vendor exception, so the panel can report it
    as a normal message rather than the stream dying mid-frame.
    """


class LLMProvider(ABC):
    #: Shown in the panel and in the `assistant_error` analytics event.
    name = "provider"

    @abstractmethod
    def complete(self, *, system: str, messages: list[dict],
                 tools: list[ToolSpec]) -> ProviderReply:
        """One turn. Returns text, tool calls, or both.

        Args:
            system (str): System prompt for this turn.
            messages (list[dict]): Neutral transcript so far.
            tools (list[ToolSpec]): Tools offered to the model this turn.

        Returns:
            ProviderReply: The model's reply — text and/or tool calls.
        """
        raise NotImplementedError

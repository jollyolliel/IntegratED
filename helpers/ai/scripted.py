"""The PR preview's stand-in model: no key, no network, the same replies every time (ADR 0007's
provider seam). It calls one real read tool, so a preview still exercises the agent loop, the
tool and its queries, then says what came back."""

from __future__ import annotations

from helpers.ai.provider import LLMProvider, ProviderReply, ToolCall, ToolSpec

__all__ = ["ScriptedProvider"]


class ScriptedProvider(LLMProvider):
    """Asks for the match preview on a question about matching, else the pair summaries."""

    name = "scripted"

    def complete(self, *, system: str, messages: list[dict], tools: list[ToolSpec]) -> ProviderReply:
        """One scripted turn: a tool call after the teacher's message, an answer after the tool.

        Args:
            system (str): Ignored.
            messages (list[dict]): The neutral transcript; only its last entry matters.
            tools (list[ToolSpec]): Tools offered; none means the loop wants a final answer.

        Returns:
            ProviderReply: A tool call or a final answer.
        """
        last = messages[-1] if messages else {}
        if last.get("role") == "user" and tools:
            asked_about_matching = "match" in str(last.get("content", "")).lower()
            tool = "preview_auto_match" if asked_about_matching else "pair_summaries"
            return ProviderReply(
                tool_calls=[ToolCall(id="scripted-1", name=tool, arguments={})], finish_reason="tool_calls"
            )
        ran = f"ran `{last['name']}`" if last.get("role") == "tool" else "had no tool to run"
        return ProviderReply(
            text=(
                f"This is the preview's **scripted** assistant, not an AI. I {ran} on the fake data. "
                "Ask about matching to run the match preview; anything else runs the pair summaries."
            )
        )

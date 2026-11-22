"""The provider swap point and the tool registry."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── provider registry ────────────────────────────────────────────────────────


def test_the_default_provider_is_built_when_nothing_is_configured(monkeypatch):
    from helpers.ai import registry

    monkeypatch.delenv("ASSISTANT_PROVIDER", raising=False)
    built = []
    monkeypatch.setattr(
        registry, "_builders", lambda: {"gemini": lambda: built.append("gemini") or "provider"}
    )

    assert registry.get_provider() == "provider"
    assert built == ["gemini"]


def test_the_environment_selects_the_provider(monkeypatch):
    from helpers.ai import registry

    monkeypatch.setenv("ASSISTANT_PROVIDER", "other")
    monkeypatch.setattr(registry, "_builders", lambda: {"other": lambda: "chosen"})

    assert registry.get_provider() == "chosen"


@pytest.mark.parametrize("given", ["GEMINI", " gemini "])
def test_the_provider_name_is_normalized(monkeypatch, given):
    from helpers.ai import registry

    monkeypatch.setattr(registry, "_builders", lambda: {"gemini": lambda: "ok"})

    assert registry.get_provider(given) == "ok"


def test_an_unknown_provider_is_refused_with_the_available_names(monkeypatch):
    from helpers.ai import registry
    from helpers.ai.provider import ProviderError

    monkeypatch.setattr(registry, "_builders", lambda: {"gemini": lambda: "ok"})

    with pytest.raises(ProviderError, match="gemini"):
        registry.get_provider("wishful")


def test_an_explicit_name_beats_the_environment(monkeypatch):
    from helpers.ai import registry

    monkeypatch.setenv("ASSISTANT_PROVIDER", "gemini")
    monkeypatch.setattr(
        registry, "_builders", lambda: {"gemini": lambda: "env", "other": lambda: "explicit"}
    )

    assert registry.get_provider("other") == "explicit"


# ── tool registry ────────────────────────────────────────────────────────────


def test_every_registered_tool_has_a_usable_schema():
    from helpers.ai import tools

    for name, tool in tools.all_tools().items():
        assert tool.description, name
        assert tool.parameters.get("type") == "object", name
        assert callable(tool.fn), name


def test_tool_specs_are_sorted_and_match_the_registry():
    from helpers.ai import tools

    specs = tools.tool_specs()
    names = [spec.name for spec in specs]

    assert names == sorted(names)
    assert set(names) == set(tools.all_tools())


def test_an_unknown_tool_lookup_returns_none():
    from helpers.ai import tools

    assert tools.get_tool("no_such_tool") is None


def test_a_human_label_is_formatted_with_the_call_arguments():
    from helpers.ai import tools

    tool = tools.get_tool("describe_entity")

    assert tool is not None
    assert tool.human_label({"entity": "Learner"}) == "Inspecting Learner"


def test_a_label_with_a_missing_argument_falls_back_to_the_tool_name():
    """A formatting slip must not kill the turn mid-stream."""

    from helpers.ai import tools

    tool = tools.get_tool("describe_entity")

    assert tool is not None
    assert tool.human_label({}) == "Describe entity"


def test_a_tool_with_no_label_falls_back_to_its_name():
    from helpers.ai.tools import ToolDef

    tool = ToolDef(
        name="count_records", description="d", parameters={}, fn=lambda ctx: None
    )

    assert tool.human_label({}) == "Count records"


def test_write_tools_are_flagged_as_writing():
    from helpers.ai import tools

    registry = tools.all_tools()

    assert registry["match_pair"].writes is True
    assert registry["query_records"].writes is False

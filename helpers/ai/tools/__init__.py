"""Tool registry.

Every module in this package is imported on first use, so dropping a new
`helpers/ai/tools/groups.py` in registers its tools with no edit anywhere else.

A tool is a plain function decorated with `@ai_tool`:

    @ai_tool(
        name="count_records",
        description="How many rows match, without pulling them.",
        label="Counting {entity}",
        parameters={"type": "object", "properties": {...}, "required": [...]},
    )
    def count_records(ctx, entity, filters=None):
        ...

`ctx` is a `ToolContext` — it carries the teacher every scoped query is built
against, so a tool cannot accidentally run unscoped. `label` is formatted with
the call's arguments to produce the step chip the teacher sees; a missing key
falls back to the tool name rather than raising mid-turn.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from helpers.ai.provider import ToolSpec
    from models import Teacher

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Everything a tool is allowed to know about the caller."""
    teacher: Teacher
    conversation_id: int | None = None
    #: Incremented per staged change so apply order is deterministic.
    staged: list[int] = field(default_factory=list)


@dataclass
class ToolDef:
    """One registered tool: its schema, its function, and its step-chip label."""
    name: str
    description: str
    parameters: dict
    fn: Callable
    writes: bool = False
    label: str = ""

    def human_label(self, arguments: dict[str, Any] | None) -> str:
        """Render this tool's step-chip label for one call's arguments.

        Args:
            arguments (dict[str, Any] | None): The call's arguments.

        Returns:
            str: `label.format(**arguments)`, or a title-cased tool name on any format error.
        """
        if not self.label:
            return self.name.replace("_", " ").capitalize()
        try:
            return self.label.format(**(arguments or {}))
        except (KeyError, IndexError, ValueError):
            return self.name.replace("_", " ").capitalize()


_REGISTRY: dict[str, ToolDef] = {}
_loaded = False


def ai_tool(*, name: str, description: str, parameters: dict, writes: bool = False, label: str = "") -> Callable:
    """Decorator registering a function as an assistant tool.

    Args:
        name (str): Unique tool name.
        description (str): Shown to the model in its tool list.
        parameters (dict): JSON Schema for the tool's arguments.
        writes (bool): Whether this tool stages a write (vs. a pure read).
        label (str): `.format(**arguments)`-ed into the step chip the teacher sees.

    Returns:
        Callable: The decorator to apply to the tool function.
    """
    def decorate(fn: Callable) -> Callable:
        """Register `fn` in the tool registry.

        Args:
            fn (Callable): The tool implementation, `(ctx, **kwargs) -> Any`.

        Returns:
            Callable: `fn`, unchanged.
        """
        if name in _REGISTRY:
            raise RuntimeError(f"Duplicate AI tool name: {name}")
        _REGISTRY[name] = ToolDef(
            name=name, description=description, parameters=parameters,
            fn=fn, writes=writes, label=label,
        )
        return fn
    return decorate


def _load() -> None:
    """Import every tool module in this package, once per process.

    Returns:
        None
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{module.name}")
    logger.debug("Assistant tools loaded: %s", ", ".join(sorted(_REGISTRY)))


def all_tools() -> dict[str, ToolDef]:
    """Every registered tool, loading tool modules first if needed.

    Returns:
        dict[str, ToolDef]: Tool name -> its definition.
    """
    _load()
    return dict(_REGISTRY)


def get_tool(name: str) -> ToolDef | None:
    """Look up one registered tool by name.

    Args:
        name (str): Tool name.

    Returns:
        ToolDef | None: The tool, or None if unregistered.
    """
    _load()
    return _REGISTRY.get(name)


def tool_specs() -> list[ToolSpec]:
    """Registry -> the provider's neutral ToolSpec list.

    Returns:
        list[ToolSpec]: One `ToolSpec` per registered tool, sorted by name.
    """
    from helpers.ai.provider import ToolSpec

    return [
        ToolSpec(name=tool.name, description=tool.description, parameters=tool.parameters)
        for tool in sorted(all_tools().values(), key=lambda t: t.name)
    ]

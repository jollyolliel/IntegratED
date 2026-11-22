"""Dot-path helpers for the nested translation files, shared by every translation script."""

from __future__ import annotations

from typing import Any

__all__ = ["flatten_keys", "get_nested", "set_nested"]


def flatten_keys(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Every leaf string of a nested translation dict, by dot path.

    Args:
        data (dict[str, Any]): A parsed translation file (or part of one).
        prefix (str): Dot path of `data` itself.

    Returns:
        dict[str, str]: `{"section.key": "value"}` for every string leaf.
    """
    out: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten_keys(value, path))
        elif isinstance(value, str):
            out[path] = value
    return out


def get_nested(data: dict[str, Any], dot_key: str) -> Any:
    """The value at a dot path, or None when any step is missing.

    Args:
        data (dict[str, Any]): A parsed translation file.
        dot_key (str): e.g. `"learner.quiz.title"`.

    Returns:
        Any: The value (a string, or a dict for a section), or None.
    """
    node: Any = data
    for part in dot_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_nested(data: dict[str, Any], dot_key: str, value: Any) -> None:
    """Set the value at a dot path, creating (or replacing non-dict) sections on the way.

    Args:
        data (dict[str, Any]): A parsed translation file, changed in place.
        dot_key (str): e.g. `"learner.quiz.title"`.
        value (Any): The value to store.
    """
    parts = dot_key.split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value

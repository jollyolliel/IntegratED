"""Unit tests for the PreToolUse hook that keeps translations/*.json script-only."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def reason(tool_name: str, **tool_input):
    from scripts.guard_translations import blocked_reason

    return blocked_reason({"tool_name": tool_name, "tool_input": tool_input})


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
@pytest.mark.parametrize(
    "path",
    [
        "translations/en.json",
        "C:\\repo\\translations\\ar.json",
        "/home/x/repo/translations/needs_translation.json",
    ],
)
def test_file_tools_on_translation_json_are_blocked(tool, path):
    msg = reason(tool, file_path=path)

    assert msg is not None
    assert "scripts/add_translation_key.py" in msg


@pytest.mark.parametrize(
    "path",
    [
        "templates/pages/settings.jx",
        "scripts/translation_comments.json",
        "translations/README.md",
        "tests/fixtures/translations_en.json",
    ],
)
def test_file_tools_elsewhere_are_allowed(path):
    assert reason("Edit", file_path=path) is None


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
@pytest.mark.parametrize(
    "command",
    [
        "sed -i 's/Login/Sign in/' translations/en.json",
        "echo '{}' > translations/ar.json",
        "jq . x.json | tee translations/fr.json",
        "Set-Content translations\\en.json '{}'",
        "python -c \"import json; json.dump({}, open('translations/en.json','w'))\"",
    ],
)
def test_shell_writes_to_translation_json_are_blocked(tool, command):
    assert reason(tool, command=command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "cat translations/en.json",
        "grep -n login translations/en.json",
        "uv run scripts/add_translation_key.py nav.x 'X' > out.txt",
        "uv run scripts/sync_keys.py",
        "echo hi > notes.txt",
        "sed -i 's/a/b/' templates/pages/x.jx",
    ],
)
def test_reads_and_sanctioned_scripts_are_allowed(command):
    assert reason("Bash", command=command) is None


def test_unrelated_tool_is_allowed():
    assert reason("Read", file_path="translations/en.json") is None


@pytest.mark.parametrize(
    "command",
    [
        "uv run scripts/add_translation_key.py --remove old.banner.title",
        "uv run scripts/add_translation_key.py --remove a.b c.d --force",
    ],
)
def test_the_remove_mode_is_allowed(command):
    assert reason("Bash", command=command) is None


def test_the_message_documents_removal():
    from scripts.guard_translations import MESSAGE

    assert "--remove" in MESSAGE

"""PreToolUse hook: translations/*.json are written by scripts, never by hand.

Blocks Edit/Write/MultiEdit on any translations/<name>.json, and Bash or
PowerShell commands that name one alongside a write (sed -i, redirection,
tee, Set-Content, json.dump, ...). Reads stay allowed, and so does any command
running one of the translation scripts. Exit 2 sends the instructions on
stderr back to the agent as blocking feedback.
"""

from __future__ import annotations

import json
import re
import sys

_FILE_TOOLS = {"Edit", "Write", "MultiEdit"}
_SHELL_TOOLS = {"Bash", "PowerShell"}

_TRANSLATION_JSON = re.compile(r"(?:^|[/\\])translations[/\\][\w.-]+\.json$", re.IGNORECASE)
_TRANSLATION_JSON_IN_COMMAND = re.compile(r"(?:^|[\s'\"/\\])translations[/\\][\w.-]+\.json", re.IGNORECASE)
_SANCTIONED_SCRIPT = re.compile(
    r"\b(?:add_translation_key|sync_keys|translate_missing|translation_audit)\.py\b"
)
_SHELL_WRITE = re.compile(
    r"\bsed\b[^|;&]*\s-[a-z]*i"
    r"|\bperl\b[^|;&]*\s-[a-z]*i"
    r"|>>?\s*['\"]?[^\s'\"]*translations[/\\]"
    r"|\btee\b"
    r"|\b(?:Set-Content|Add-Content|Out-File|WriteAllText|Move-Item|Copy-Item|mv|cp)\b"
    r"|json\.dump|write_text|\.write\(",
    re.IGNORECASE,
)

MESSAGE = """\
BLOCKED: translations/*.json are never edited by hand.

Add UI text with the script — it writes en.json, puts the English value as a
placeholder in every other language file, and logs the key in
translations/needs_translation.json:

  uv run scripts/add_translation_key.py <section.key> "<English value>" [<key> "<value>" ...]

Change the English text of an existing key (resets every language to the new
English placeholder and re-logs it for translation):

  uv run scripts/add_translation_key.py --update <section.key> "<new English value>"

Stop there: leave the English placeholders. Don't translate them or run the
translation tools — translation is done separately, not by agents.
"""


def blocked_reason(payload: dict) -> str | None:
    """The message to block this tool call with, or None to let it through."""
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool in _FILE_TOOLS:
        path = str(tool_input.get("file_path", ""))
        return MESSAGE if _TRANSLATION_JSON.search(path) else None

    if tool in _SHELL_TOOLS:
        command = str(tool_input.get("command", ""))
        if (
            _TRANSLATION_JSON_IN_COMMAND.search(command)
            and _SHELL_WRITE.search(command)
            and not _SANCTIONED_SCRIPT.search(command)
        ):
            return MESSAGE
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    reason = blocked_reason(payload if isinstance(payload, dict) else {})
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

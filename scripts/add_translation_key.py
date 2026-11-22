"""
Add (or change) UI text in every translation file at once.

translations/*.json are script-only — a PreToolUse hook
(scripts/guard_translations.py) blocks editing them by hand. This writes the
English value to en.json, the same English as a placeholder to every other
language file, and logs the key in needs_translation.json for translators.

Usage:
  uv run scripts/add_translation_key.py learner.garden.title "My Garden"
  uv run scripts/add_translation_key.py a.one "One" a.two "Two"     # several pairs
  uv run scripts/add_translation_key.py --update nav.login "Sign in"  # change English text

--update overwrites every language's value with the new English placeholder,
since the old translations no longer match. Without it an existing key is
refused. All pairs are validated before anything is written.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ty: ignore[unresolved-attribute]
sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # ty: ignore[unresolved-attribute]

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.file_lock import LockTimeout, locked
from scripts.sync_keys import (
    TRANSLATIONS_DIR,
    get_nested,
    load_json,
    save_json,
    set_nested,
)

NEEDS_TRANSLATION = "needs_translation.json"
_KEY_RE = re.compile(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*")


class TranslationKeyError(ValueError):
    """A key/value pair that can't be written as asked."""


def _check_pair(en: dict, key: str, value: str, update: bool) -> bool:
    """Raise on a bad pair; return True when it would change en.json."""
    if not _KEY_RE.fullmatch(key):
        raise TranslationKeyError(f"{key!r}: keys are dot-separated letters, digits and underscores")
    if not value.strip():
        raise TranslationKeyError(f"{key}: English value is empty")

    node = en
    parts = key.split(".")
    for i, part in enumerate(parts[:-1]):
        node = node.get(part)
        if node is None:
            return True
        if not isinstance(node, dict):
            parent = ".".join(parts[: i + 1])
            raise TranslationKeyError(f"{key}: {parent} is already a string, not a section")
    leaf = node.get(parts[-1])
    if isinstance(leaf, dict):
        raise TranslationKeyError(f"{key}: is a section of keys, not a single string")
    if leaf is not None and not update:
        raise TranslationKeyError(f"{key}: already exists as {leaf!r} — pass --update to change it")
    return leaf != value


# Two chats adding keys at once would each rewrite every language file from
# what they read, dropping the other's key; the lock makes them take turns.
LOCK_NAME = ".write.lock"
LOCK_TIMEOUT = 30


def add_keys(
    pairs: list[tuple[str, str]],
    *,
    update: bool = False,
    translations_dir: str = TRANSLATIONS_DIR,
    today: str | None = None,
) -> list[str]:
    """Write each pair to every language file; return the keys that changed."""
    en_path = os.path.join(translations_dir, "en.json")
    en = load_json(en_path)
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise TranslationKeyError("the same key is given more than once")
    changed =[key for key, value in pairs if _check_pair(en, key, value, update)]
    if not changed:
        return []
    values = dict(pairs)

    langs = sorted(
        f[:-5]
        for f in os.listdir(translations_dir)
        if f.endswith(".json") and f not in ("en.json", NEEDS_TRANSLATION)
    )

    for key in changed:
        set_nested(en, key, values[key])
    save_json(en_path, en)

    for lang in langs:
        path = os.path.join(translations_dir, f"{lang}.json")
        data = load_json(path)
        for key in changed:
            if update or get_nested(data, key) is None:
                set_nested(data, key, values[key])
        save_json(path, data)

    needs_path = os.path.join(translations_dir, NEEDS_TRANSLATION)
    needs = (
        load_json(needs_path)
        if os.path.exists(needs_path)
        else {"description": "Keys added as English placeholders — need real translations"}
    )
    tracked = needs.setdefault("keys", {})
    for key in changed:
        tracked[key] = {
            "en": values[key],
            "added": today or str(date.today()),
            "langs_needing_translation": langs,
        }
    save_json(needs_path, needs)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pairs", nargs="+", metavar="KEY VALUE", help="dotted key followed by its English text")
    parser.add_argument("--update", action="store_true", help="change the English text of existing keys")
    parser.add_argument("--dir", default=TRANSLATIONS_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if len(args.pairs) % 2:
        print("ERROR: arguments must be KEY VALUE pairs (got an odd count)", file=sys.stderr)
        return 1
    pairs = list(zip(args.pairs[::2], args.pairs[1::2]))

    try:
        with locked(os.path.join(args.dir, LOCK_NAME), timeout=LOCK_TIMEOUT):
            changed = add_keys(pairs, update=args.update, translations_dir=args.dir)
    except LockTimeout:
        print("ERROR: busy: another chat is adding translation keys; try again", file=sys.stderr)
        return 1
    except TranslationKeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not changed:
        print("Nothing changed — every key already has that English value.")
        return 0
    for key in changed:
        print(f"  + {key}")
    print(f"\n{len(changed)} key(s) written to en.json, every language file, and {NEEDS_TRANSLATION}.")
    print("Done — leave the English placeholders; translation is done separately, not by agents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

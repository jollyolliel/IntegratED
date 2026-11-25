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
  uv run scripts/add_translation_key.py --remove old.banner.title    # delete unused keys
  uv run scripts/add_translation_key.py --unused                     # list keys nothing uses

--update overwrites every language's value with the new English placeholder,
since the old translations no longer match. Without it an existing key is
refused. All pairs are validated before anything is written.

--remove deletes keys from every language file and needs_translation.json,
pruning sections left empty. It first searches the code (templates, Python,
JS, JSON) for the key in quotes, or for a quoted prefix it could be built from
(t('section.key_' ~ x)), and refuses if found unless --force is given.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date

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
from scripts.translation_keys import flatten_keys

NEEDS_TRANSLATION = "needs_translation.json"
_KEY_RE = re.compile(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*")


class TranslationKeyError(ValueError):
    """A key/value pair that can't be written as asked."""


class KeyInUseError(TranslationKeyError):
    """A key asked to be removed is still referenced in the code."""


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

    langs = _languages(translations_dir)

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


def _languages(translations_dir: str) -> list[str]:
    """Codes of every language file other than English."""
    return sorted(
        f[:-5]
        for f in os.listdir(translations_dir)
        if f.endswith(".json") and f not in ("en.json", NEEDS_TRANSLATION)
    )


# --- Where keys are used ------------------------------------------------------

_SCANNED_EXTENSIONS = (".py", ".jx", ".html", ".js", ".json")
_SKIPPED_DIRS = {"node_modules", "__pycache__"}
# Notes about keys for translators, not uses of them.
_SKIPPED_FILES = {"scripts/translation_comments.json"}
# A whole dotted key in quotes: t('learner.quiz.title'), "nav.login".
_QUOTED_KEY = re.compile(r"""['"`]([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)['"`]""")
# The quoted start of a key finished at runtime: 'a.b_' ~ x, "a.b." + x, f"a.b_{x}", `a.b_${x}`.
_KEY_PREFIX = re.compile(
    r"""['"`]([A-Za-z0-9_]+\.[A-Za-z0-9_.]*)['"`]\s*[~+]"""
    r"""|\bf['"]([A-Za-z0-9_]+\.[A-Za-z0-9_.]*)\{"""
    r"""|`([A-Za-z0-9_]+\.[A-Za-z0-9_.]*)\$\{"""
)


class _References:
    """Every quoted key and key prefix in the code, with the files each appears in."""

    def __init__(self, code_root: str) -> None:
        self.literals: dict[str, set[str]] = {}
        self.prefixes: dict[str, set[str]] = {}
        for dirpath, dirnames, filenames in os.walk(code_root):
            rel_dir = os.path.relpath(dirpath, code_root)
            dirnames[:] = [
                d
                for d in dirnames
                if not d.startswith(".")
                and d not in _SKIPPED_DIRS
                and not (rel_dir == "." and d == "translations")  # the files being changed
            ]
            for name in filenames:
                if not name.endswith(_SCANNED_EXTENSIONS):
                    continue
                rel = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, "/")
                if rel in _SKIPPED_FILES:
                    continue
                try:
                    with open(os.path.join(dirpath, name), encoding="utf-8") as handle:
                        text = handle.read()
                except (OSError, UnicodeDecodeError):
                    continue
                for match in _QUOTED_KEY.finditer(text):
                    self.literals.setdefault(match.group(1), set()).add(rel)
                for match in _KEY_PREFIX.finditer(text):
                    prefix = next(group for group in match.groups() if group)
                    self.prefixes.setdefault(prefix, set()).add(rel)

    def files_using(self, key: str) -> list[str]:
        """Files that name `key` outright or hold a prefix it could be built from."""
        files = set(self.literals.get(key, ()))
        for prefix, where in self.prefixes.items():
            if key.startswith(prefix) and key != prefix:
                files |= where
        return sorted(files)


def unused_keys(*, translations_dir: str = TRANSLATIONS_DIR, code_root: str = ROOT) -> list[str]:
    """Keys in en.json that nothing in the code references, in file order."""
    refs = _References(code_root)
    en = load_json(os.path.join(translations_dir, "en.json"))
    return [key for key in flatten_keys(en) if not refs.files_using(key)]


# --- Removing keys --------------------------------------------------------------


def _delete_nested(data: dict, key: str) -> bool:
    """Delete the leaf at `key` and any sections it leaves empty; True if it was there."""
    parts = key.split(".")
    trail = [data]
    for part in parts[:-1]:
        node = trail[-1].get(part)
        if not isinstance(node, dict):
            return False
        trail.append(node)
    if parts[-1] not in trail[-1] or isinstance(trail[-1][parts[-1]], dict):
        return False
    del trail[-1][parts[-1]]
    for depth in range(len(parts) - 1, 0, -1):
        if trail[depth]:
            break
        del trail[depth - 1][parts[depth - 1]]
    return True


def remove_keys(
    keys: list[str],
    *,
    force: bool = False,
    translations_dir: str = TRANSLATIONS_DIR,
    code_root: str = ROOT,
) -> list[str]:
    """Delete each key from every language file and needs_translation.json; return the keys.

    Every key is checked first — well formed, a string in en.json, and (unless `force`)
    not referenced in the code — so a refusal writes nothing.
    """
    if len(set(keys)) != len(keys):
        raise TranslationKeyError("the same key is given more than once")
    en_path = os.path.join(translations_dir, "en.json")
    en = load_json(en_path)
    for key in keys:
        if not _KEY_RE.fullmatch(key):
            raise TranslationKeyError(f"{key!r}: keys are dot-separated letters, digits and underscores")
        value = get_nested(en, key)
        if value is None:
            raise TranslationKeyError(f"{key}: not in en.json — nothing to remove")
        if isinstance(value, dict):
            raise TranslationKeyError(f"{key}: is a section of keys — remove its keys one by one")

    if not force:
        refs = _References(code_root)
        in_use = {key: files for key in keys if (files := refs.files_using(key))}
        if in_use:
            lines = [f"  {key}: {', '.join(files)}" for key, files in in_use.items()]
            raise KeyInUseError(
                "still referenced, so not removed:\n"
                + "\n".join(lines)
                + "\nDrop those uses first, or pass --force if they don't really use the key."
            )

    for key in keys:
        _delete_nested(en, key)
    save_json(en_path, en)

    for lang in _languages(translations_dir):
        path = os.path.join(translations_dir, f"{lang}.json")
        data = load_json(path)
        found = [_delete_nested(data, key) for key in keys]  # every key, no short-circuit
        if any(found):
            save_json(path, data)

    needs_path = os.path.join(translations_dir, NEEDS_TRANSLATION)
    if os.path.exists(needs_path):
        needs = load_json(needs_path)
        tracked = needs.get("keys", {})
        logged = [tracked.pop(key, None) is not None for key in keys]  # every key, no short-circuit
        if any(logged):
            save_json(needs_path, needs)
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "pairs", nargs="*", metavar="KEY VALUE", help="dotted key followed by its English text (keys alone with --remove)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="change the English text of existing keys")
    mode.add_argument("--remove", action="store_true", help="delete unused keys from every language file")
    mode.add_argument("--unused", action="store_true", help="list keys in en.json that nothing references")
    parser.add_argument("--force", action="store_true", help="with --remove: delete even if the code references the key")
    parser.add_argument("--dir", default=TRANSLATIONS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--code-root", default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.force and not args.remove:
        print("ERROR: --force only goes with --remove", file=sys.stderr)
        return 1
    if args.unused:
        if args.pairs:
            print("ERROR: --unused takes no keys", file=sys.stderr)
            return 1
        unused = unused_keys(translations_dir=args.dir, code_root=args.code_root)
        for key in unused:
            print(key)
        print(f"\n{len(unused)} key(s) in en.json that nothing references (keys built at runtime count as used).")
        return 0
    if not args.pairs:
        print("ERROR: give at least one key", file=sys.stderr)
        return 1
    if args.remove:
        return _main_remove(args)

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


def _main_remove(args: argparse.Namespace) -> int:
    try:
        with locked(os.path.join(args.dir, LOCK_NAME), timeout=LOCK_TIMEOUT):
            removed = remove_keys(args.pairs, force=args.force, translations_dir=args.dir, code_root=args.code_root)
    except LockTimeout:
        print("ERROR: busy: another chat is changing translation keys; try again", file=sys.stderr)
        return 1
    except TranslationKeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for key in removed:
        print(f"  - {key}")
    print(f"\n{len(removed)} key(s) removed from every language file and {NEEDS_TRANSLATION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

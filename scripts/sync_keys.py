"""
Sync translation keys across all language files.

New keys go through scripts/add_translation_key.py, which writes every file
itself. This is the repair pass: any key in en.json missing from another
language file is added there (English as placeholder) and logged to
translations/needs_translation.json — e.g. after taking one side of a merge
conflict in a generated language file.

Usage:
  python scripts/sync_keys.py            # sync + report
  python scripts/sync_keys.py --dry-run  # preview without writing
  python scripts/sync_keys.py --audit    # also scan templates for undefined keys
"""

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date

ROOT = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(ROOT) not in sys.path:
    sys.path.insert(0, os.path.abspath(ROOT))

from scripts.translation_keys import flatten_keys, get_nested, set_nested

TRANSLATIONS_DIR = os.path.join(ROOT, "translations")
TEMPLATES_DIR = os.path.join(ROOT, "templates")
NEEDS_TRANSLATION_PATH = os.path.join(TRANSLATIONS_DIR, "needs_translation.json")

# Keys pulled in via t() that are dynamic/programmatic — not static template strings
DYNAMIC_KEY_PREFIXES = ("learner.", "volunteer.", "teacher.")  # keep audit noise low


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    """Write `data` to a temp file beside `path`, then swap it in.

    Several chats share one working tree, so a reader never sees a half-written file.
    """
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        if os.path.exists(path):
            shutil.copymode(path, tmp)
        else:  # mkstemp makes the file private; a new file gets the usual permissions
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(tmp, 0o666 & ~umask)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ---------------------------------------------------------------------------
# Nested-dict helpers (dot-notation)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Template scanner
# ---------------------------------------------------------------------------

# Match t('key') / t("key") only inside Jinja delimiters {{ }} or {% %}
_JINJA_BLOCK_RE = re.compile(r"\{[{%].*?[%}]\}", re.DOTALL)
_T_CALL_RE = re.compile(r"""(?<![a-zA-Z0-9_])t\(\s*['"]([a-zA-Z][a-zA-Z0-9_.]*)['"]\s*[,)]""")


def scan_template_keys(templates_dir: str) -> set[str]:
    """Walk all .jx and .html files; extract t('key') calls inside Jinja blocks only."""
    keys = set()
    for dirpath, _, filenames in os.walk(templates_dir):
        for fname in filenames:
            if not fname.endswith((".jx", ".html")):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError) as exc:
                print(f"  WARNING: skipping unreadable template {fpath}: {exc}")
                continue
            for block in _JINJA_BLOCK_RE.finditer(text):
                for m in _T_CALL_RE.finditer(block.group()):
                    keys.add(m.group(1))
    return keys


# ---------------------------------------------------------------------------
# Needs-translation tracker
# ---------------------------------------------------------------------------

def load_needs_translation() -> dict:
    if os.path.exists(NEEDS_TRANSLATION_PATH):
        return load_json(NEEDS_TRANSLATION_PATH)
    return {"description": "Keys added as English placeholders — need real translations", "keys": {}}


def save_needs_translation(data: dict) -> None:
    save_json(NEEDS_TRANSLATION_PATH, data)


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def sync_lang(lang: str, en_keys: dict[str, str], dry_run: bool) -> list[str]:
    """
    Ensure every key in en_keys exists in <lang>.json.
    Missing keys are added with the English value as placeholder.
    Returns list of dotpaths that were (or would be) added.
    """
    lang_path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
    target = load_json(lang_path) if os.path.exists(lang_path) else {}

    added = []
    for dotpath, en_value in en_keys.items():
        if get_nested(target, dotpath) is None:
            added.append(dotpath)
            if not dry_run:
                set_nested(target, dotpath, en_value)

    if not dry_run and added:
        save_json(lang_path, target)

    return added


def main():
    dry_run = "--dry-run" in sys.argv
    audit = "--audit" in sys.argv

    en_path = os.path.join(TRANSLATIONS_DIR, "en.json")
    if not os.path.exists(en_path):
        print("ERROR: translations/en.json not found")
        sys.exit(1)

    en_data = load_json(en_path)
    en_keys = flatten_keys(en_data)

    lang_files = sorted(
        f[:-5]
        for f in os.listdir(TRANSLATIONS_DIR)
        if f.endswith(".json") and f not in ("en.json", "needs_translation.json")
    )

    print(f"en.json: {len(en_keys)} keys")
    print(f"Targets: {', '.join(lang_files)}")
    print(f"Mode: {'DRY RUN — no files written' if dry_run else 'LIVE'}\n")

    # ------------------------------------------------------------------
    # Optional: audit templates for keys missing from en.json
    # ------------------------------------------------------------------
    if audit:
        template_keys = scan_template_keys(TEMPLATES_DIR)
        undefined = sorted(k for k in template_keys if k not in en_keys)
        if undefined:
            print(f"AUDIT — {len(undefined)} template key(s) not in en.json:")
            for k in undefined:
                print(f"  MISSING  {k}")
        else:
            print("AUDIT — all template keys exist in en.json ✓")
        print()

    # ------------------------------------------------------------------
    # Sync each language file — collect newly added keys as we go
    # ------------------------------------------------------------------
    today = str(date.today())
    grand_total = 0
    # Union of keys added across all langs (same set per lang — track once)
    all_newly_added: set[str] = set()

    for lang in lang_files:
        added = sync_lang(lang, en_keys, dry_run)
        grand_total += len(added)
        all_newly_added.update(added)
        verb = "would add" if dry_run else "added"
        if added:
            print(f"  {lang}: {verb} {len(added)} key(s)")
            for k in added:
                print(f"    + {k}")
        else:
            print(f"  {lang}: up to date")

    # ------------------------------------------------------------------
    # Update needs_translation.json with exactly the keys we just added
    # ------------------------------------------------------------------
    if not dry_run and all_newly_added:
        needs_data = load_needs_translation()
        existing_tracked = set(needs_data.get("keys", {}).keys())
        newly_tracked = {}
        for dotpath in sorted(all_newly_added):
            if dotpath not in existing_tracked:
                newly_tracked[dotpath] = {
                    "en": en_keys[dotpath],
                    "added": today,
                    "langs_needing_translation": lang_files,
                }
        if newly_tracked:
            needs_data.setdefault("keys", {}).update(newly_tracked)
            save_needs_translation(needs_data)
            print(f"\n  Logged {len(newly_tracked)} new key(s) to needs_translation.json")

    print(f"\nDone. {grand_total} key(s) {'would be ' if dry_run else ''}added total.")

    if not dry_run and grand_total > 0:
        print("\nPlaceholders are logged in needs_translation.json; translation is done")
        print("  separately, not by agents.")


if __name__ == "__main__":
    main()

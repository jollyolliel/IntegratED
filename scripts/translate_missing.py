"""
Translate missing keys from en.json to all other language files.
Usage: python scripts/translate_missing.py [--dry-run]

Batches missing strings into chunks <=4000 chars per API call.
Only fills keys present in en.json but absent in target. Never overwrites.
"""

import json
import os
import sys

TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "translations")
SEPARATOR = " ||| "
MAX_CHARS = 4000

# Rohingya has no ISO 639-1 code recognised by Google Translate.
# needs_translation is a tracking file, not a language, but lives alongside
# the lang files and matches the *.json glob below.
SKIP_LANGS = {"rhg", "needs_translation"}


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def collect_missing(source: dict, target: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Return [(dotpath, english_value)] for keys in source missing from target."""
    missing = []
    for k, v in source.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            sub = target.get(k, {})
            if not isinstance(sub, dict):
                sub = {}
            missing.extend(collect_missing(v, sub, path))
        elif isinstance(v, str) and _get_nested(target, path) is None:
            missing.append((path, v))
    return missing


def _get_nested(d: dict, dotpath: str):
    parts = dotpath.split(".")
    node = d
    for p in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return node if isinstance(node, str) else None


def _set_nested(d: dict, dotpath: str, value: str) -> None:
    parts = dotpath.split(".")
    node = d
    for p in parts[:-1]:
        if p not in node or not isinstance(node[p], dict):
            node[p] = {}
        node = node[p]
    node[parts[-1]] = value


def _translate_chunk(texts: list[str], lang: str, translator) -> list[str]:
    """Translate one chunk via single API call. Falls back to English on error."""
    joined = SEPARATOR.join(texts)
    try:
        result = translator.translate(joined)
        if result:
            parts = result.split(SEPARATOR.strip())
            if len(parts) == len(texts):
                return [p.strip() for p in parts]
            # Try alternate separators Google may mangle
            for sep in ["|||", " | ", "|"]:
                parts = result.split(sep)
                if len(parts) == len(texts):
                    return [p.strip() for p in parts]
    except Exception as e:  # noqa: BLE001 - optional external Google Translate call, one chunk failing must not abort the whole sync run
        print(f"    chunk error: {e}")
    return texts  # fallback to English


def batch_translate(texts: list[str], lang: str) -> list[str]:
    """Translate list of strings chunked to stay under 4000 char API limit."""
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source="en", target=lang)
    results = []
    chunk, chunk_len = [], 0

    def flush():
        nonlocal chunk, chunk_len
        if chunk:
            results.extend(_translate_chunk(chunk, lang, translator))
            chunk, chunk_len = [], 0

    for text in texts:
        seg_len = len(text) + len(SEPARATOR)
        if chunk and chunk_len + seg_len > MAX_CHARS:
            flush()
        chunk.append(text)
        chunk_len += seg_len

    flush()
    return results


def translate_lang(lang: str, en_data: dict, target_data: dict, dry_run: bool) -> int:
    missing = collect_missing(en_data, target_data)
    if not missing:
        print(f"  {lang}: complete — 0 missing")
        return 0

    paths = [m[0] for m in missing]
    en_values = [m[1] for m in missing]

    chunks_needed = max(1, sum(len(v) for _, v in missing) // MAX_CHARS + 1)
    print(f"  {lang}: translating {len(missing)} keys (~{chunks_needed} API calls)...")
    translated_values = batch_translate(en_values, lang)

    added = 0
    for dotpath, value in zip(paths, translated_values):
        if not dry_run:
            _set_nested(target_data, dotpath, value)
        added += 1

    status = "would add" if dry_run else "added"
    print(f"  {lang}: {status} {added} keys")
    return added


def count_strings(d: dict) -> int:
    return sum(
        count_strings(v) if isinstance(v, dict) else 1
        for v in d.values()
    )


def main():
    dry_run = "--dry-run" in sys.argv

    en_path = os.path.join(TRANSLATIONS_DIR, "en.json")
    if not os.path.exists(en_path):
        print("ERROR: translations/en.json not found")
        sys.exit(1)

    en_data = load_json(en_path)
    lang_files = sorted(
        f[:-5]
        for f in os.listdir(TRANSLATIONS_DIR)
        if f.endswith(".json") and f != "en.json"
    )

    print(f"Source: en.json ({count_strings(en_data)} strings)")
    print(f"Targets: {', '.join(lang_files)}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")

    total_added = 0
    for lang in lang_files:
        if lang in SKIP_LANGS:
            print(f"  {lang}: SKIPPED (no Google Translate support)")
            continue

        lang_path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
        target_data = load_json(lang_path) if os.path.exists(lang_path) else {}

        added = translate_lang(lang, en_data, target_data, dry_run)
        total_added += added

        if not dry_run and added > 0:
            save_json(lang_path, target_data)
            print(f"    saved {lang}.json")

    print(f"\nDone. {total_added} keys {'would be ' if dry_run else ''}added total.")


if __name__ == "__main__":
    main()

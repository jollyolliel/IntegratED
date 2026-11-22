import json
import os
from collections.abc import Callable
from typing import Any

from flask import session

from settings import get_settings

NATIVE_LANGS = {"en", "ar", "tr", "es", "fr", "uk", "fa", "ps", "so", "rhg", "ti", "sw", "el"}
RTL_LANGS = {"ar", "he", "fa", "ur", "ps"}

_translations_cache: dict[str, dict] = {}
_seen_mtimes: dict[str, int] | None = None

_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "translations")

__all__ = ["get_current_lang", "get_ui_direction", "i18n_context_processor", "make_translator"]


def _load_json(lang: str) -> dict | None:
    """Load and cache `translations/<lang>.json`.

    Args:
        lang (str): Language code.

    Returns:
        dict | None: The parsed translation tree, or None if the file doesn't exist.
    """
    if lang in _translations_cache:
        return _translations_cache[lang]
    path = os.path.join(_TRANSLATIONS_DIR, f"{lang}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _translations_cache[lang] = data
    return data


def _resolve(d: dict, key: str) -> str | None:
    """Walk a nested translation dict by dot-notation key.

    Args:
        d (dict): Translation tree to search.
        key (str): Dot-notation key, e.g. "learner.dashboard.title".

    Returns:
        str | None: The resolved string, or None if the path doesn't lead to one.
    """
    parts = key.split(".")
    node = d
    for p in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return node if isinstance(node, str) else None


def _translate_dict_via_google(lang: str, source: dict) -> dict:
    """Machine-translate every string value in a translation tree.

    Args:
        lang (str): Target language code.
        source (dict): Source translation tree (English).

    Returns:
        dict: Translated tree, same shape as `source`. Falls back to the
            original string on a per-value translation failure.
    """
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source="en", target=lang)

    def recurse(d: dict) -> dict:
        """Translate every string value in `d`, recursing into nested dicts."""
        out = {}
        for k, v in d.items():
            if isinstance(v, str):
                try:
                    out[k] = translator.translate(v) or v
                except Exception:  # noqa: BLE001 - optional external Google Translate call, one string failing must not block the whole page from rendering
                    out[k] = v
            elif isinstance(v, dict):
                out[k] = recurse(v)
            else:
                out[k] = v
        return out

    return recurse(source)


def _get_translations(lang: str) -> dict:
    """Get the translation tree for a language, auto-translating if needed.

    Args:
        lang (str): Language code.

    Returns:
        dict: Native translations if `translations/<lang>.json` exists,
            else a Google-Translate pass over English, else English itself.
    """
    data = _load_json(lang)
    if data is not None:
        return data

    # Try Google Translate for non-native languages
    en_data = _load_json("en") or {}
    try:
        translated = _translate_dict_via_google(lang, en_data)
        _translations_cache[lang] = translated
        return translated
    except Exception:  # noqa: BLE001 - optional external Google Translate call, a failure must fall back to English rather than break the page
        return en_data


def get_current_lang() -> str:
    """Get the current session's UI language.

    Returns:
        str: Language code, defaulting to "en".
    """
    return session.get("ui_lang", "en")


def get_ui_direction(lang: str) -> str:
    """Text direction for a language.

    Args:
        lang (str): Language code.

    Returns:
        str: "rtl" for a right-to-left language, else "ltr".
    """
    return "rtl" if lang in RTL_LANGS else "ltr"


def make_translator(lang: str) -> Callable[..., str]:
    """Build a `t(key, **kwargs)` translator bound to one language.

    Args:
        lang (str): Language code to translate into.

    Returns:
        Callable[..., str]: Translator function; falls back to English, then
            the raw key, and format()s `{placeholder}`s from kwargs.
    """
    translations = _get_translations(lang)
    en_fallback = _load_json("en") or {}

    def t(key: str, **kwargs: Any) -> str:
        """Resolve `key` to a translated, format()-substituted string."""
        value = _resolve(translations, key)
        if value is None:
            value = _resolve(en_fallback, key) or key
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError):
                return value
        return value

    return t


def _drop_cache_if_files_changed() -> None:
    """Dev-only: clear the translation cache when a translations file changes."""
    global _seen_mtimes
    current = {
        entry.name: entry.stat().st_mtime_ns
        for entry in os.scandir(_TRANSLATIONS_DIR)
        if entry.name.endswith(".json")
    }
    if _seen_mtimes is not None and current != _seen_mtimes:
        _translations_cache.clear()
    _seen_mtimes = current


def i18n_context_processor() -> dict[str, Any]:
    """Flask context processor injecting translation helpers into every template.

    Returns:
        dict[str, Any]: `t` (translator), `ui_lang`, `ui_dir`, `ui_rtl`, `native_langs`.
    """
    if get_settings().is_development:
        _drop_cache_if_files_changed()
    lang = get_current_lang()
    translator = make_translator(lang)
    return {
        "t": translator,
        "ui_lang": lang,
        "ui_dir": get_ui_direction(lang),
        "ui_rtl": lang in RTL_LANGS,
        "native_langs": list(NATIVE_LANGS),
    }

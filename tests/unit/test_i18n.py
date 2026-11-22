"""Translation lookup, fallback, and direction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TRANSLATIONS_DIR = Path(__file__).resolve().parents[2] / "translations"


# ── dotted-key resolution ────────────────────────────────────────────────────


def test_a_dotted_key_walks_nested_dicts():
    from helpers.i18n import _resolve

    assert _resolve({"nav": {"home": "Home"}}, "nav.home") == "Home"


def test_a_missing_key_resolves_to_nothing():
    from helpers.i18n import _resolve

    assert _resolve({"nav": {"home": "Home"}}, "nav.away") is None


def test_a_key_that_lands_on_a_dict_is_not_a_translation():
    """`nav` alone is a section, not a string, and must not be rendered."""

    from helpers.i18n import _resolve

    assert _resolve({"nav": {"home": "Home"}}, "nav") is None


def test_walking_through_a_non_dict_resolves_to_nothing():
    from helpers.i18n import _resolve

    assert _resolve({"nav": "Home"}, "nav.home.deep") is None


# ── direction ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["ar", "fa", "ps", "he", "ur"])
def test_right_to_left_languages_report_rtl(lang):
    from helpers.i18n import get_ui_direction

    assert get_ui_direction(lang) == "rtl"


@pytest.mark.parametrize("lang", ["en", "es", "sw", "el", "unknown"])
def test_everything_else_reports_ltr(lang):
    from helpers.i18n import get_ui_direction

    assert get_ui_direction(lang) == "ltr"


# ── the translator ───────────────────────────────────────────────────────────


def test_a_known_key_is_translated():
    from helpers.i18n import _load_json, make_translator

    english = _load_json("en") or {}
    section = next(k for k, v in english.items() if isinstance(v, dict))
    key = next(k for k, v in english[section].items() if isinstance(v, str))

    t = make_translator("en")

    assert t(f"{section}.{key}") == english[section][key]


def test_an_unknown_key_renders_as_itself():
    """Better a visible key than a blank label."""

    from helpers.i18n import make_translator

    t = make_translator("en")

    assert t("nothing.here.at.all") == "nothing.here.at.all"


def test_placeholders_are_filled_in(monkeypatch):
    from helpers import i18n

    monkeypatch.setitem(i18n._translations_cache, "en", {"greet": {"hi": "Hello {name}"}})

    assert i18n.make_translator("en")("greet.hi", name="Ada") == "Hello Ada"


def test_a_placeholder_with_no_value_leaves_the_string_intact(monkeypatch):
    """A formatting slip must not raise mid-render."""

    from helpers import i18n

    monkeypatch.setitem(i18n._translations_cache, "en", {"greet": {"hi": "Hello {name}"}})

    assert i18n.make_translator("en")("greet.hi", other="x") == "Hello {name}"


def test_a_missing_translation_falls_back_to_english(monkeypatch):
    from helpers import i18n

    monkeypatch.setitem(i18n._translations_cache, "en", {"nav": {"home": "Home"}})
    monkeypatch.setitem(i18n._translations_cache, "ar", {"nav": {}})

    assert i18n.make_translator("ar")("nav.home") == "Home"


def test_editing_a_translation_file_is_picked_up_without_a_restart(monkeypatch, tmp_path):
    from helpers import i18n

    (tmp_path / "en.json").write_text(json.dumps({"a": "before"}), encoding="utf-8")
    monkeypatch.setattr(i18n, "_TRANSLATIONS_DIR", str(tmp_path))
    monkeypatch.setattr(i18n, "_seen_mtimes", None)
    i18n._translations_cache.clear()

    i18n._drop_cache_if_files_changed()  # baseline
    assert i18n.make_translator("en")("a") == "before"

    path = tmp_path / "en.json"
    path.write_text(json.dumps({"a": "after"}), encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    i18n._drop_cache_if_files_changed()
    assert i18n.make_translator("en")("a") == "after"


# ── language files ───────────────────────────────────────────────────────────


def test_every_native_language_has_a_translation_file():
    from helpers.i18n import NATIVE_LANGS

    missing = [
        lang for lang in NATIVE_LANGS if not (TRANSLATIONS_DIR / f"{lang}.json").exists()
    ]

    assert not missing, f"declared native but no file: {sorted(missing)}"


def test_every_translation_file_is_valid_json():
    broken = []
    for path in TRANSLATIONS_DIR.glob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            broken.append((path.name, str(exc)))

    assert not broken, broken


def test_no_translation_is_an_empty_string():
    """`t()` falls back only when a key is *absent*. A key present as "" makes
    the label vanish for that language with no fallback, and the key-sync
    script fills `None`, not `""` — so it cannot repair these either."""

    def empties(node, prefix=""):
        found = []
        for key, value in node.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                found.extend(empties(value, f"{path}."))
            elif value == "":
                found.append(path)
        return found

    offenders = {}
    for path in TRANSLATIONS_DIR.glob("*.json"):
        keys = empties(json.loads(path.read_text(encoding="utf-8")))
        if keys:
            offenders[path.name] = keys[:5]

    assert not offenders, offenders


# ── session language ─────────────────────────────────────────────────────────


def test_the_language_defaults_to_english(app):
    from helpers.i18n import get_current_lang

    with app.test_request_context():
        assert get_current_lang() == "en"


def test_the_session_language_is_used_when_set(app):
    from flask import session

    from helpers.i18n import get_current_lang

    with app.test_request_context():
        session["ui_lang"] = "ar"

        assert get_current_lang() == "ar"


def test_the_context_processor_exposes_direction_and_translator(app):
    from flask import session

    from helpers.i18n import i18n_context_processor

    with app.test_request_context():
        session["ui_lang"] = "ar"
        context = i18n_context_processor()

    assert context["ui_lang"] == "ar"
    assert context["ui_dir"] == "rtl"
    assert context["ui_rtl"] is True
    assert callable(context["t"])

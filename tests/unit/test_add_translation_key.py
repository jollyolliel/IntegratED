"""Unit tests for scripts/add_translation_key.py — the one sanctioned way to add UI text."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit

TODAY = "2026-10-04"


def write_json(path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def tdir(tmp_path):
    write_json(tmp_path / "en.json", {"nav": {"login": "Login"}})
    write_json(tmp_path / "ar.json", {"nav": {"login": "تسجيل الدخول"}})
    write_json(tmp_path / "fr.json", {"nav": {"login": "Connexion"}})
    write_json(
        tmp_path / "needs_translation.json",
        {"description": "Keys added as English placeholders — need real translations", "keys": {}},
    )
    return tmp_path


def add(tdir, pairs, **kw):
    from scripts.add_translation_key import add_keys

    return add_keys(pairs, translations_dir=str(tdir), today=TODAY, **kw)


def test_new_key_lands_in_english_and_every_language(tdir):
    add(tdir, [("learner.garden.title", "My Garden")])

    assert read_json(tdir / "en.json")["learner"]["garden"]["title"] == "My Garden"
    assert read_json(tdir / "ar.json")["learner"]["garden"]["title"] == "My Garden"
    assert read_json(tdir / "fr.json")["learner"]["garden"]["title"] == "My Garden"


def test_new_key_is_logged_for_translation(tdir):
    add(tdir, [("learner.garden.title", "My Garden")])

    entry = read_json(tdir / "needs_translation.json")["keys"]["learner.garden.title"]
    assert entry == {"en": "My Garden", "added": TODAY, "langs_needing_translation": ["ar", "fr"]}


def test_existing_translations_are_untouched(tdir):
    add(tdir, [("learner.garden.title", "My Garden")])

    assert read_json(tdir / "ar.json")["nav"]["login"] == "تسجيل الدخول"
    assert read_json(tdir / "needs_translation.json")["description"].startswith("Keys added")


def test_several_pairs_in_one_call(tdir):
    add(tdir, [("a.one", "One"), ("a.two", "Two")])

    assert read_json(tdir / "fr.json")["a"] == {"one": "One", "two": "Two"}
    assert set(read_json(tdir / "needs_translation.json")["keys"]) == {"a.one", "a.two"}


def test_existing_key_is_refused_without_update(tdir):
    from scripts.add_translation_key import TranslationKeyError

    with pytest.raises(TranslationKeyError, match="--update"):
        add(tdir, [("nav.login", "Sign in")])

    assert read_json(tdir / "en.json")["nav"]["login"] == "Login"


def test_refusal_writes_nothing_even_for_valid_pairs_in_the_same_call(tdir):
    from scripts.add_translation_key import TranslationKeyError

    with pytest.raises(TranslationKeyError):
        add(tdir, [("a.fresh", "Fresh"), ("nav.login", "Sign in")])

    assert "a" not in read_json(tdir / "en.json")
    assert "a" not in read_json(tdir / "ar.json")
    assert read_json(tdir / "needs_translation.json")["keys"] == {}


def test_update_rewrites_english_and_resets_translations_to_placeholder(tdir):
    add(tdir, [("nav.login", "Sign in")], update=True)

    assert read_json(tdir / "en.json")["nav"]["login"] == "Sign in"
    assert read_json(tdir / "ar.json")["nav"]["login"] == "Sign in"
    entry = read_json(tdir / "needs_translation.json")["keys"]["nav.login"]
    assert entry["en"] == "Sign in"


def test_update_with_same_value_changes_nothing(tdir):
    add(tdir, [("nav.login", "Login")], update=True)

    assert read_json(tdir / "ar.json")["nav"]["login"] == "تسجيل الدخول"
    assert read_json(tdir / "needs_translation.json")["keys"] == {}


@pytest.mark.parametrize(
    "key",
    [
        "nav.login.extra",  # parent is already a string
        "nav",  # would replace a whole section
    ],
)
def test_key_that_collides_with_the_tree_shape_is_refused(tdir, key):
    from scripts.add_translation_key import TranslationKeyError

    with pytest.raises(TranslationKeyError):
        add(tdir, [(key, "x")], update=True)


@pytest.mark.parametrize("key", ["", "nav..login", "nav.login!", ".nav", "nav login"])
def test_malformed_key_is_refused(tdir, key):
    from scripts.add_translation_key import TranslationKeyError

    with pytest.raises(TranslationKeyError):
        add(tdir, [(key, "x")])


def test_empty_value_is_refused(tdir):
    from scripts.add_translation_key import TranslationKeyError

    with pytest.raises(TranslationKeyError):
        add(tdir, [("a.blank", "  ")])


def test_cli_rejects_an_odd_number_of_arguments(tdir, capsys):
    from scripts.add_translation_key import main

    assert main(["--dir", str(tdir), "a.one", "One", "a.two"]) == 1
    assert "pairs" in capsys.readouterr().err


def test_cli_adds_a_pair(tdir):
    from scripts.add_translation_key import main

    assert main(["--dir", str(tdir), "a.one", "One"]) == 0
    assert read_json(tdir / "ar.json")["a"]["one"] == "One"


def test_a_second_writer_waits_for_the_first_and_gives_up_cleanly(tdir, monkeypatch, capsys):
    from scripts import add_translation_key
    from scripts.file_lock import locked

    monkeypatch.setattr(add_translation_key, "LOCK_TIMEOUT", 0.2)
    with locked(str(tdir / ".write.lock")):
        assert add_translation_key.main(["--dir", str(tdir), "a.one", "One"]) == 1

    assert "busy" in capsys.readouterr().err
    assert "a" not in read_json(tdir / "en.json")

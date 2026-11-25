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


# --- --remove ---------------------------------------------------------------


@pytest.fixture
def code_root(tmp_path):
    """An empty code tree for the usage scan: nothing references any key."""
    root = tmp_path / "code"
    (root / "templates").mkdir(parents=True)
    return root


@pytest.fixture
def rdir(tdir):
    """Translation files holding a dead key, a live key and a logged placeholder."""
    write_json(tdir / "en.json", {"nav": {"login": "Login"}, "old": {"banner": {"title": "Hi"}}, "zeta": "Z"})
    write_json(tdir / "ar.json", {"nav": {"login": "تسجيل الدخول"}, "old": {"banner": {"title": "مرحبا"}}, "zeta": "Z"})
    write_json(tdir / "fr.json", {"nav": {"login": "Connexion"}, "zeta": "Z"})
    write_json(
        tdir / "needs_translation.json",
        {
            "description": "Keys added as English placeholders — need real translations",
            "keys": {"old.banner.title": {"en": "Hi", "added": TODAY, "langs_needing_translation": ["ar", "fr"]}},
        },
    )
    return tdir


def remove(rdir, code_root, keys, **kw):
    from scripts.add_translation_key import remove_keys

    return remove_keys(keys, translations_dir=str(rdir), code_root=str(code_root), **kw)


def test_remove_deletes_the_key_everywhere_and_prunes_empty_sections(rdir, code_root):
    assert remove(rdir, code_root, ["old.banner.title"]) == ["old.banner.title"]

    for lang in ("en", "ar", "fr"):
        assert "old" not in read_json(rdir / f"{lang}.json")
    assert read_json(rdir / "needs_translation.json")["keys"] == {}


def test_remove_keeps_other_keys_their_order_and_the_file_format(rdir, code_root):
    remove(rdir, code_root, ["old.banner.title"])

    text = (rdir / "ar.json").read_text(encoding="utf-8")
    assert text == json.dumps({"nav": {"login": "تسجيل الدخول"}, "zeta": "Z"}, ensure_ascii=False, indent=2) + "\n"
    assert list(read_json(rdir / "en.json")) == ["nav", "zeta"]


def test_remove_leaves_a_section_that_still_has_keys(rdir, code_root):
    write_json(rdir / "en.json", {"nav": {"login": "Login", "logout": "Logout"}})

    remove(rdir, code_root, ["nav.logout"])

    assert read_json(rdir / "en.json") == {"nav": {"login": "Login"}}


def test_removing_a_missing_key_is_an_error_and_writes_nothing(rdir, code_root):
    from scripts.add_translation_key import TranslationKeyError

    before = {p.name: p.read_text(encoding="utf-8") for p in rdir.glob("*.json")}
    with pytest.raises(TranslationKeyError, match="nav.nope"):
        remove(rdir, code_root, ["old.banner.title", "nav.nope"])

    assert {p.name: p.read_text(encoding="utf-8") for p in rdir.glob("*.json")} == before


def test_removing_a_whole_section_is_refused(rdir, code_root):
    from scripts.add_translation_key import TranslationKeyError

    with pytest.raises(TranslationKeyError, match="section"):
        remove(rdir, code_root, ["old.banner"])


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("templates/pages/x.jx", "{{ t('old.banner.title') }}"),
        ("templates/pages/x.html", '<h1>{{ t("old.banner.title", name=n) }}</h1>'),
        ("routes/learner.py", 'flash_key = "old.banner.title"'),
    ],
)
def test_removing_a_referenced_key_is_refused_with_the_files(rdir, code_root, path, source):
    from scripts.add_translation_key import KeyInUseError

    (code_root / path).parent.mkdir(parents=True, exist_ok=True)
    (code_root / path).write_text(source, encoding="utf-8")

    with pytest.raises(KeyInUseError) as exc:
        remove(rdir, code_root, ["old.banner.title"])

    assert path in str(exc.value)
    assert read_json(rdir / "en.json")["old"]["banner"]["title"] == "Hi"


def test_a_key_built_from_a_dynamic_prefix_counts_as_referenced(rdir, code_root):
    from scripts.add_translation_key import KeyInUseError

    (code_root / "templates" / "x.jx").write_text("{{ t('old.banner.' ~ part) }}", encoding="utf-8")

    with pytest.raises(KeyInUseError, match="templates/x.jx"):
        remove(rdir, code_root, ["old.banner.title"])


def test_a_longer_key_sharing_the_name_is_not_a_reference(rdir, code_root):
    (code_root / "templates" / "x.jx").write_text("{{ t('old.banner.title_long') }}", encoding="utf-8")

    assert remove(rdir, code_root, ["old.banner.title"]) == ["old.banner.title"]


def test_translation_files_themselves_are_not_references(rdir, code_root):
    (code_root / "translations").mkdir()
    write_json(code_root / "translations" / "en.json", {"x": "old.banner.title"})

    assert remove(rdir, code_root, ["old.banner.title"]) == ["old.banner.title"]


def test_force_removes_a_referenced_key(rdir, code_root):
    (code_root / "templates" / "x.jx").write_text("{{ t('old.banner.title') }}", encoding="utf-8")

    assert remove(rdir, code_root, ["old.banner.title"], force=True) == ["old.banner.title"]
    assert "old" not in read_json(rdir / "en.json")


def test_unused_lists_keys_nothing_references(rdir, code_root):
    from scripts.add_translation_key import unused_keys

    (code_root / "templates" / "x.jx").write_text("{{ t('nav.login') }}", encoding="utf-8")

    assert unused_keys(translations_dir=str(rdir), code_root=str(code_root)) == ["old.banner.title", "zeta"]


def test_cli_remove(rdir, code_root, capsys):
    from scripts.add_translation_key import main

    assert main(["--dir", str(rdir), "--code-root", str(code_root), "--remove", "old.banner.title"]) == 0
    assert "old" not in read_json(rdir / "fr.json")
    assert "- old.banner.title" in capsys.readouterr().out


def test_cli_remove_refuses_a_referenced_key_and_names_the_file(rdir, code_root, capsys):
    from scripts.add_translation_key import main

    (code_root / "templates" / "x.jx").write_text("{{ t('old.banner.title') }}", encoding="utf-8")

    assert main(["--dir", str(rdir), "--code-root", str(code_root), "--remove", "old.banner.title"]) == 1
    err = capsys.readouterr().err
    assert "templates/x.jx" in err
    assert "--force" in err


def test_cli_remove_and_update_together_are_refused(rdir, code_root, capsys):
    from scripts.add_translation_key import main

    with pytest.raises(SystemExit):
        main(["--dir", str(rdir), "--remove", "--update", "old.banner.title"])


def test_cli_force_without_remove_is_refused(rdir, capsys):
    from scripts.add_translation_key import main

    assert main(["--dir", str(rdir), "--force", "a.one", "One"]) == 1
    assert "--force" in capsys.readouterr().err


def test_writes_go_through_a_temp_file_and_replace(rdir, code_root, monkeypatch):
    import os

    replaced = []
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: (replaced.append(dst), real_replace(src, dst)))

    remove(rdir, code_root, ["old.banner.title"])

    # fr.json never had the key, so it isn't rewritten.
    assert {os.path.basename(p) for p in replaced} == {"en.json", "ar.json", "needs_translation.json"}
    leftovers = sorted(p.name for p in rdir.iterdir() if p.is_file())
    assert leftovers == ["ar.json", "en.json", "fr.json", "needs_translation.json"]

"""The i18n scanners on `.jx` templates: scripts/jx_i18n.py (what jx syntax counts as
text), and the tool built on it, scripts/translation_audit.py (its offline --report and its fixes)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import jx
import pytest

from scripts import jx_i18n, translation_audit

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "i18n" / "hardcoded.jx"
FIXTURE_NAME = "pages/learner/hardcoded.jx"


def fixture_source() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def line_of(source: str, needle: str) -> int:
    return source[: source.index(needle)].count("\n") + 1


# --- jx_i18n: what counts as text in jx ---


def test_a_quoted_text_prop_on_a_component_is_hard_coded():
    _, items = jx_i18n.scan_jx(fixture_source(), FIXTURE_NAME)
    props = [(item.tag, item.prop, item.text) for item in items if item.prop]
    assert props == [("Button", "label", "Back to start")]


def test_an_expression_prop_and_a_config_prop_are_not_text():
    _, items = jx_i18n.scan_jx(fixture_source(), FIXTURE_NAME)
    texts = {item.text for item in items}
    assert "sky" not in texts and "admin" not in texts and "clock" not in texts
    assert not any("fixture." in text for text in texts)


def test_bare_text_inside_a_component_is_hard_coded():
    source = fixture_source()
    _, items = jx_i18n.scan_jx(source, FIXTURE_NAME)
    children = [(item.tag, item.text, item.line) for item in items if item.prop is None]
    assert children == [
        ("Button", "Save changes", line_of(source, "Save changes")),
        ("Card", "Caption here", line_of(source, "Caption here")),
    ]


def test_text_inside_html_in_a_component_and_html_split_by_expressions_is_not_component_text():
    _, items = jx_i18n.scan_jx(fixture_source(), FIXTURE_NAME)
    texts = {item.text for item in items}
    assert "Inside a paragraph" not in texts
    assert not any("alt=" in text or "<" in text or ">" in text for text in texts)


def test_each_item_knows_the_exact_source_it_replaces():
    source = fixture_source()
    _, items = jx_i18n.scan_jx(source, FIXTURE_NAME)
    assert {source[item.start : item.end] for item in items} == {'label="Back to start"', "Save changes", "Caption here"}


def test_markup_blanks_declarations_comments_and_component_tags_but_keeps_lines():
    source = fixture_source()
    markup, _ = jx_i18n.scan_jx(source, FIXTURE_NAME)
    assert markup.count("\n") == source.count("\n")
    for gone in ("Doc comment words", "@components/base/button.jx", "heading_text",
                 "A template comment", "<Button", "</Button>", "<Page", "</Page>", "Back to start"):
        assert gone not in markup
    assert line_of(markup, "<h1") == line_of(source, "<h1")
    assert '<input type="search" placeholder="Search learners" />' in markup


def test_jx_replacement_writes_the_expression_form():
    source = fixture_source()
    _, items = jx_i18n.scan_jx(source, FIXTURE_NAME)
    by_text = {item.text: item for item in items}
    assert jx_i18n.replacement(by_text["Back to start"], "a.back") == "label={{ t('a.back') }}"
    assert jx_i18n.replacement(by_text["Save changes"], "a.save") == "{{ t('a.save') }}"


def test_translatable_templates_cover_jx_and_the_remaining_html():
    found = {str(path.relative_to(jx_i18n.TEMPLATES_DIR)).replace("\\", "/")
             for path in jx_i18n.translatable_templates()}
    assert {"pages/learner/dashboard.jx", "page_components/public/articles_results.jx",
            "components/shell/header.jx", "components/base/button.jx", "starting_up.html"} <= found
    assert not {"components/shell/theme.jx", "pages/dev/components.jx"} & found


# --- scripts/translation_audit.py --report ---


def report_findings(tmp_path: Path, monkeypatch) -> list[tuple[int, str, str, str]]:
    templates = tmp_path / "templates"
    target = templates / FIXTURE_NAME
    target.parent.mkdir(parents=True)
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(translation_audit, "TEMPLATES_DIR", templates)
    return translation_audit.report_findings(target)


def test_the_report_lists_html_text_props_component_text_and_html_attributes(tmp_path, monkeypatch):
    source = fixture_source()
    found = {(line, element, text) for line, element, text, _ in report_findings(tmp_path, monkeypatch)}
    assert found == {
        (line_of(source, "Hello there"), "<h1>", "Hello there"),
        (line_of(source, "Back to start"), "<Button>@label", "Back to start"),
        (line_of(source, "Save changes"), "<Button>", "Save changes"),
        (line_of(source, "Caption here"), "<Card>", "Caption here"),
        (line_of(source, "Inside a paragraph"), "<p>", "Inside a paragraph"),
        (line_of(source, "Total rows"), "<td>", "Total rows"),
        (line_of(source, "Search learners"), "@placeholder", "Search learners"),
    }


def test_the_report_suggests_keys_in_the_page_section(tmp_path, monkeypatch):
    keys = {key for *_, key in report_findings(tmp_path, monkeypatch)}
    assert "learner.save_changes" in keys


@pytest.mark.parametrize(("path", "section"), [
    ("pages/learner/dashboard.jx", "learner"),
    ("pages/learner/learning/quiz.jx", "learner"),
    ("page_components/teacher/people_list.jx", "teacher"),
    ("pages/about.jx", "about"),
    ("components/shell/header.jx", "components"),
    ("starting_up.html", "starting_up"),
])
def test_the_report_derives_the_section_from_the_jx_path(path, section):
    assert translation_audit.infer_section(Path(path)) == section


def test_the_report_needs_no_api_key():
    env = {key: value for key, value in __import__("os").environ.items() if key != "GEMINI_API_KEY"}
    result = subprocess.run(
        [sys.executable, "scripts/translation_audit.py", "--report"], cwd=ROOT, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "=== i18n report ===" in result.stdout


# --- scripts/translation_audit.py ---


def audit_copy(tmp_path: Path, monkeypatch) -> Path:
    templates = tmp_path / "templates"
    target = templates / FIXTURE_NAME
    target.parent.mkdir(parents=True)
    shutil.copy(FIXTURE, target)
    monkeypatch.setattr(translation_audit, "TEMPLATES_DIR", templates)
    return target


def test_translation_audit_scans_jx_text_and_missing_keys(tmp_path, monkeypatch):
    target = audit_copy(tmp_path, monkeypatch)
    result = translation_audit.scan_template(target, {"fixture.page_title": "Page"})
    texts = [issue["text"] for issue in result["hardcoded"]]
    assert sorted(texts) == [
        "Back to start", "Caption here", "Hello there", "Inside a paragraph", "Save changes", "Search learners",
        "Total rows",
    ]
    assert "fixture.translated_intro" in result["missing_keys"]
    assert "fixture.page_title" not in result["missing_keys"]


def test_translation_audit_context_shows_the_original_source(tmp_path, monkeypatch):
    target = audit_copy(tmp_path, monkeypatch)
    [save] = [i for i in translation_audit.scan_template(target, {})["hardcoded"] if i["text"] == "Save changes"]
    assert '<Button variant="gray" icon="clock">Save changes</Button>' in save["context_lines"]


def test_translation_audit_fix_patches_jx_props_and_text(tmp_path, monkeypatch):
    target = audit_copy(tmp_path, monkeypatch)
    issues = translation_audit.scan_template(target, {})["hardcoded"]
    keys = {"Back to start": "fixture.back", "Save changes": "fixture.save", "Hello there": "fixture.hello",
            "Caption here": "fixture.caption", "Inside a paragraph": "fixture.paragraph", "Total rows": "fixture.rows",
            "Search learners": "fixture.search"}
    patched = translation_audit.apply_template_patches(target, [{**i, "key": keys[i["text"]]} for i in issues])
    content = target.read_text(encoding="utf-8")
    assert patched == 7
    assert "placeholder=\"{{ t('fixture.search') }}\"" in content
    assert """<td class="py-2 {% if rows > 0 %}text-primary{% endif %}">{{ t('fixture.rows') }}</td>""" in content
    assert "alt=\"\" /> {{ t('fixture.caption') }}</Card>" in content
    assert "\">{{ t('fixture.paragraph') }}</p></Card>" in content
    assert "label={{ t('fixture.back') }}" in content
    assert '<Button variant="gray" icon="clock">{{ t(\'fixture.save\') }}</Button>' in content
    assert "<h1 class=\"text-xl\">{{ t('fixture.hello') }}</h1>" in content
    assert 'data-live-label="Live variant name"' in content
    jx.parse_ast(content, name=FIXTURE_NAME)


@pytest.mark.parametrize("arg", ["pages/about.jx", "templates/pages/about.jx"])
def test_translation_audit_resolves_a_template_relative_to_templates_or_the_repo(arg):
    assert translation_audit.resolve_template(arg) == ROOT / "templates" / "pages" / "about.jx"


@pytest.mark.parametrize(("path", "role"), [
    ("components/shell/header.jx", "Global site header / navigation"),
    ("components/shell/footer.jx", "Global site footer"),
    ("pages/login.jx", "Login page"),
    ("pages/teacher/people.jx", "Teacher portal for managing pairs, attendance, worksheets"),
    ("components/base/button.jx", "Shared UI component"),
    ("page_components/teacher/people_list.jx", "Teacher portal for managing pairs, attendance, worksheets"),
])
def test_translation_audit_describes_jx_templates(path, role):
    assert translation_audit._template_role(path) == role


# --- scripts/translation_audit.py talking to Gemini ---


def test_the_gemini_key_travels_in_a_header_not_the_url(monkeypatch):
    """A key in the query string ends up in tracebacks, proxy logs and request errors."""
    sent = {}

    class Reply:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    def fake_post(url, **kwargs):
        sent["url"], sent["headers"] = url, kwargs.get("headers", {})
        return Reply()

    monkeypatch.setattr(translation_audit, "GEMINI_API_KEY", "test-key-123")
    monkeypatch.setattr(translation_audit.requests, "post", fake_post)

    assert translation_audit.gemini_call("hi") == "{}"
    assert "test-key-123" not in sent["url"]
    assert sent["headers"]["x-goog-api-key"] == "test-key-123"

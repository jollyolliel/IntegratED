"""Form bases in templates/components/base/, and the form pieces composed from them."""

from __future__ import annotations

import pytest

from tests.support.html import parse
from tests.support.jx import imports as _imports

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("kind", ["text", "email", "password", "number", "date", "time", "search", "tel", "url"])
def test_input_is_a_clay_input_of_each_type(render_jx, kind):
    field = parse(render_jx(_imports("Input") + f'<Input type="{kind}" name="q" id="q" required />')).find("input")

    assert field.classes == ["clay-input"]
    assert (field.attrs["type"], field.attrs["name"], field.attrs["id"]) == (kind, "q", "q")
    assert "required" in field.attrs


def test_input_defaults_to_text(render_jx):
    assert parse(render_jx(_imports("Input") + "<Input />")).find("input").attrs["type"] == "text"


def test_input_raises_on_an_unknown_type(render_jx):
    with pytest.raises(ValueError, match="Input.*type.*checkbox"):
        render_jx(_imports("Input") + '<Input type="checkbox" />')


def test_input_with_an_icon_insets_the_text_past_it(render_jx):
    html = render_jx(_imports("Input") + '<Input icon="magnifying-glass" id="ws-search" class="flex-1" />')
    wrapper = parse(html).find("div")
    field = wrapper.find("input")

    assert wrapper.find("svg")
    assert field.attrs["id"] == "ws-search"
    assert "clay-input" in field.classes
    assert "flex-1" in wrapper.classes


def test_a_password_input_carries_a_show_password_toggle(render_jx):
    html = render_jx(_imports("Input") + '<Input type="password" name="pw" id="pw" class="flex-1" />')
    wrapper = parse(html).find("div", "password-field")
    field = wrapper.find("input")
    toggle = wrapper.find("button", "password-toggle")

    assert (field.attrs["type"], field.attrs["id"]) == ("password", "pw")
    assert "clay-input" in field.classes
    assert "flex-1" in wrapper.classes and "flex-1" not in field.classes
    assert toggle.attrs["type"] == "button"
    assert toggle.attrs["aria-pressed"] == "false"
    assert toggle.attrs["aria-controls"] == "pw"
    assert toggle.attrs["aria-label"] == "Show password"
    open_eye, crossed_eye = toggle.find_all("svg")  # the icon shows the field state: crossed out while hidden
    assert "hidden" in open_eye.attrs and "hidden" not in crossed_eye.attrs


def test_a_password_input_without_an_id_still_gets_its_toggle(render_jx):
    toggle = parse(render_jx(_imports("Input") + '<Input type="password" name="pw" />')).find("button", "password-toggle")

    assert "aria-controls" not in toggle.attrs


@pytest.mark.parametrize("kind", ["text", "email", "search"])
def test_only_a_password_input_has_a_toggle(render_jx, kind):
    html = render_jx(_imports("Input") + f'<Input type="{kind}" name="q" />')

    assert "password-toggle" not in html


def test_a_large_input_adds_the_large_look(render_jx):
    field = parse(render_jx(_imports("Input") + '<Input type="password" size="lg" id="pw" />')).find("input")

    assert field.classes == ["clay-input", "clay-input-lg"]


def test_input_raises_on_an_unknown_size(render_jx):
    with pytest.raises(ValueError, match="Input.*size.*xl"):
        render_jx(_imports("Input") + '<Input size="xl" />')


def test_textarea_holds_its_value(render_jx):
    area = parse(render_jx(_imports("Textarea") + '<Textarea name="bio" rows="4">Hello</Textarea>')).find("textarea")

    assert area.classes == ["clay-textarea"]
    assert area.attrs["rows"] == "4"
    assert area.all_text == "Hello"


def test_a_field_error_starts_hidden_under_its_control(render_jx):
    html = render_jx(
        _imports("Field", "Input")
        + '<Field label="Name" for_id="name" error="Required" error_id="error-name"><Input id="name" /></Field>'
    )
    wrapper = parse(html).find("div")
    error = wrapper.children[-1]

    assert (error.tag, error.classes) == ("p", ["error-msg", "hidden"])
    assert error.attrs["id"] == "error-name"
    assert error.all_text == "Required"


def test_a_field_without_an_error_has_no_message(render_jx):
    html = render_jx(_imports("Field", "Input") + '<Field label="Name"><Input /></Field>')

    assert not parse(html).find_all("p")


def test_a_field_with_no_label_is_just_its_choices_and_error(render_jx):
    html = render_jx(
        _imports("Field", "Choice")
        + '<Field error="Pick one" error_id="error-hobbies"><Choice name="hobbies" value="Music" /></Field>'
    )

    assert not parse(html).find_all("label", cls="block")
    assert parse(html).find("p").attrs["id"] == "error-hobbies"


def test_form_heading_is_the_section_heading(render_jx):
    heading = parse(render_jx(_imports("FormHeading") + "<FormHeading>Personal</FormHeading>")).find("div")

    assert heading.classes == ["section-heading"]
    assert heading.all_text == "Personal"


@pytest.mark.parametrize("kind", ["checkbox", "radio"])
def test_choice_wraps_its_input_in_a_tappable_row(render_jx, kind):
    html = render_jx(
        _imports("Choice")
        + f'<Choice type="{kind}" name="motivation" value="friend" label="Make a friend" checked class="sm:col-span-2" data-x="1" />'
    )
    label = parse(html).find("label")
    field = label.find("input")

    assert label.classes == ["choice-label", "sm:col-span-2"]
    assert (field.attrs["type"], field.attrs["name"], field.attrs["value"]) == (kind, "motivation", "friend")
    assert "checked" in field.attrs
    assert field.attrs["data-x"] == "1"
    assert label.find("span").classes == ["choice-text"]
    assert label.all_text == "Make a friend"


def test_choice_raises_on_an_unknown_type(render_jx):
    with pytest.raises(ValueError, match="Choice.*type.*text"):
        render_jx(_imports("Choice") + '<Choice type="text" name="x" value="y" label="z" />')


def test_language_row_offers_a_level_for_each_language(render_jx):
    html = render_jx(
        _imports("LanguageRow")
        + '<LanguageRow value="Greek" levels={{ ["Beginner", "Intermediate", "Advanced"] }} />'
    )
    row = parse(html).find("div", "lang-row")
    check = row.find("input", "lang-check")
    radios = row.find("div", "lang-level-group").find_all("input")

    assert (check.attrs["name"], check.attrs["value"]) == ("languages", "Greek")
    assert [r.attrs["value"] for r in radios] == ["Beginner", "Intermediate", "Advanced"]
    assert {r.attrs["name"] for r in radios} == {"language_level_Greek"}
    assert not any("disabled" in r.attrs or "checked" in r.attrs for r in radios)
    assert [label.classes for label in row.find_all("label", "lang-level-label")] == [["lang-level-label"]] * 3


def test_a_saved_language_checks_its_level_and_locks_the_rest(render_jx):
    html = render_jx(
        _imports("LanguageRow")
        + '<LanguageRow value="Greek" checked levels={{ ["Beginner", "Advanced"] }} level="Advanced" />'
    )
    row = parse(html).find("div", "lang-row")
    beginner, advanced = row.find("div", "lang-level-group").find_all("input")

    assert "checked" in row.find("input", "lang-check").attrs
    assert "disabled" in beginner.attrs
    assert "checked" in advanced.attrs


def test_a_language_row_without_levels_is_a_single_muted_choice(render_jx):
    html = render_jx(_imports("LanguageRow") + '<LanguageRow value="None" label="Other / none" muted id="lang-none" />')
    row = parse(html).find("div", "lang-row")

    assert not row.find_all("div", "lang-level-group")
    assert row.find("input").attrs["id"] == "lang-none"
    assert "text-sky-400" in row.find("span").classes

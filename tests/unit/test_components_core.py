"""Base components in templates/components/base/ (icon, button, card, badge), and the composed
buttons, cards and badges built on them.

Each renders the expected element and classes for every allowed value, passes
unknown attributes through with `class` merged, and raises on a value the
source of truth doesn't allow. A composed component adds utilities to its base
to reproduce the look its old standalone class had (ADR 0012).
"""

from __future__ import annotations

import pytest

from tests.support.html import parse
from tests.support.jx import imports as _imports

pytestmark = pytest.mark.unit


# ── Icon ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("size", "classes"),
    [("3", "w-3 h-3"), ("3.5", "w-3.5 h-3.5"), ("4", "w-4 h-4"), ("5", "w-5 h-5"),
     ("6", "w-6 h-6"), ("8", "w-8 h-8"), ("10", "w-10 h-10")],
)
def test_icon_renders_an_outline_svg_at_each_size(render_jx, size, classes):
    svg = parse(render_jx(_imports("Icon") + f'<Icon name="home" size="{size}" />')).find("svg")

    assert svg.attrs["class"] == classes
    assert svg.attrs["stroke-width"] == "2"
    assert svg.attrs["aria-hidden"] == "true"


def test_icon_defaults_to_size_four(render_jx):
    svg = parse(render_jx(_imports("Icon") + '<Icon name="home" />')).find("svg")

    assert svg.classes == ["w-4", "h-4"]


def test_a_directional_icon_component_carries_the_rtl_flip(render_jx):
    svg = parse(render_jx(_imports("Icon") + '<Icon name="chevron-right" />')).find("svg")

    assert "icon-flip-rtl" in svg.classes


def test_icon_merges_class_and_passes_attributes_through(render_jx):
    html = render_jx(_imports("Icon") + '<Icon name="home" class="text-primary" data-ph="x" />')
    svg = parse(html).find("svg")

    assert svg.classes == ["w-4", "h-4", "text-primary"]
    assert svg.attrs["data-ph"] == "x"


def test_icon_raises_on_an_unknown_size(render_jx):
    with pytest.raises(ValueError, match="Icon.*size.*7"):
        render_jx(_imports("Icon") + '<Icon name="home" size="7" />')


# ── Button ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("variant", ["accent", "sky", "soft", "gray", "danger", "amber", "rose"])
def test_button_renders_a_clay_button_in_each_colour(render_jx, variant):
    button = parse(render_jx(_imports("Button") + f'<Button variant="{variant}">Go</Button>')).find("button")

    assert button.classes == ["btn-clay", f"btn-{variant}"]
    assert button.attrs["type"] == "button"
    assert button.all_text == "Go"


def test_button_defaults_to_the_accent_colour(render_jx):
    button = parse(render_jx(_imports("Button") + "<Button>Go</Button>")).find("button")

    assert button.classes == ["btn-clay", "btn-accent"]


def test_button_large_size_adds_btn_large(render_jx):
    button = parse(render_jx(_imports("Button") + '<Button size="lg">Go</Button>')).find("button")

    assert button.classes == ["btn-clay", "btn-accent", "btn-large"]


def test_flat_button_is_a_chip(render_jx):
    button = parse(render_jx(_imports("Button") + '<Button variant="danger" flat>Delete</Button>')).find("button")

    assert button.classes == ["btn-clay", "btn-danger", "btn-flat"]


def test_a_flat_button_cannot_be_large(render_jx):
    with pytest.raises(ValueError, match="Button.*size.*lg"):
        render_jx(_imports("Button") + '<Button flat size="lg">Go</Button>')


def test_button_with_href_is_a_link(render_jx):
    link = parse(render_jx(_imports("Button") + '<Button variant="sky" href="/go">Go</Button>')).find("a")

    assert link.attrs["href"] == "/go"
    assert link.classes == ["btn-clay", "btn-sky"]
    assert "type" not in link.attrs


def test_a_disabled_link_drops_its_href_and_is_aria_disabled(render_jx):
    link = parse(render_jx(_imports("Button") + '<Button href="/go" disabled>Go</Button>')).find("a")

    assert "href" not in link.attrs
    assert link.attrs["aria-disabled"] == "true"


def test_a_disabled_button_is_disabled(render_jx):
    button = parse(render_jx(_imports("Button") + "<Button disabled={{ 2 > 1 }}>Go</Button>")).find("button")

    assert "disabled" in button.attrs


def test_button_passes_form_attributes_through_and_merges_class(render_jx):
    html = render_jx(
        _imports("Button")
        + '<Button type="submit" form="f1" name="action" value="save" id="save-btn" aria-label="Save"'
        ' data-ph-capture="save_clicked" class="flex-1">Save</Button>'
    )
    button = parse(html).find("button")

    assert button.attrs["type"] == "submit"
    assert (button.attrs["form"], button.attrs["name"], button.attrs["value"]) == ("f1", "action", "save")
    assert (button.attrs["id"], button.attrs["aria-label"]) == ("save-btn", "Save")
    assert button.attrs["data-ph-capture"] == "save_clicked"
    assert button.classes == ["btn-clay", "btn-accent", "flex-1"]


def test_button_icons_sit_before_and_after_the_label(render_jx):
    html = render_jx(_imports("Button") + '<Button icon="check" icon_end="chevron-right">Next</Button>')
    button = parse(html).find("button")
    first, last = button.children[0], button.children[-1]

    assert (first.tag, last.tag) == ("svg", "svg")
    assert "icon-flip-rtl" in last.classes
    assert "icon-flip-rtl" not in first.classes


def test_button_raises_on_an_unknown_variant(render_jx):
    with pytest.raises(ValueError, match="Button.*variant.*blue"):
        render_jx(_imports("Button") + '<Button variant="blue">Go</Button>')


# ── Card ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tone", "cls"),
    [("sky", "clay-card"), ("green", "clay-card-green"), ("amber", "clay-card-amber"),
     ("purple", "clay-card-purple"), ("pink", "clay-card-pink"), ("rose", "clay-card-rose")],
)
def test_card_is_one_standalone_class_per_tone(render_jx, tone, cls):
    card = parse(render_jx(_imports("Card") + f'<Card tone="{tone}" class="p-0">Body</Card>')).find("div")

    assert card.classes == [cls, "p-0"]
    assert card.all_text == "Body"


@pytest.mark.parametrize("tag", ["div", "section", "article", "aside"])
def test_card_renders_the_requested_element(render_jx, tag):
    assert parse(render_jx(_imports("Card") + f'<Card tag="{tag}" role="alertdialog">x</Card>')).find(tag).attrs[
        "role"
    ] == "alertdialog"


def test_card_raises_on_an_unknown_tone(render_jx):
    with pytest.raises(ValueError, match="Card.*tone.*blue"):
        render_jx(_imports("Card") + '<Card tone="blue">x</Card>')


@pytest.mark.parametrize(
    ("tone", "cls"),
    [("sky", "quick-action-card"), ("green", "quick-action-card-green"),
     ("amber", "quick-action-card-amber"), ("rose", "quick-action-card-rose")],
)
def test_a_card_with_href_is_a_clickable_link_in_each_tone(render_jx, tone, cls):
    link = parse(render_jx(_imports("Card") + f'<Card tone="{tone}" href="/x">Go</Card>')).find("a")

    assert link.classes == [cls]
    assert link.attrs["href"] == "/x"


def test_a_clickable_card_without_href_is_a_button(render_jx):
    html = render_jx(_imports("Card") + '<Card clickable data-value="salt" disabled>Salt</Card>')
    button = parse(html).find("button")

    assert button.classes == ["quick-action-card"]
    assert button.attrs["type"] == "button"
    assert button.attrs["data-value"] == "salt"
    assert "disabled" in button.attrs


def test_a_clickable_card_has_no_purple(render_jx):
    with pytest.raises(ValueError, match="Card.*tone.*purple"):
        render_jx(_imports("Card") + '<Card tone="purple" href="/x">x</Card>')


def test_empty_state_shows_its_message(render_jx):
    box = parse(render_jx(_imports("EmptyState") + '<EmptyState message="Nothing yet" class="mt-4" />')).find("div")

    assert box.classes == ["empty-state", "mt-4"]
    assert box.all_text == "Nothing yet"


def test_empty_state_content_replaces_the_message(render_jx):
    html = render_jx(_imports("EmptyState") + '<EmptyState message="unused"><p>Custom</p></EmptyState>')

    assert parse(html).find("div").all_text == "Custom"


# ── Badge ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tone", "cls"),
    [("sky", "clay-badge"), ("green", "clay-badge-green"), ("amber", "clay-badge-amber"), ("red", "clay-badge-red")],
)
def test_badge_is_one_standalone_class_per_tone(render_jx, tone, cls):
    badge = parse(render_jx(_imports("Badge") + f'<Badge tone="{tone}" class="mb-2">New</Badge>')).find("span")

    assert badge.classes == [cls, "mb-2"]
    assert badge.all_text == "New"


def test_badge_can_be_a_div(render_jx):
    assert parse(render_jx(_imports("Badge") + '<Badge tag="div">x</Badge>')).find("div", "clay-badge")


def test_badge_raises_on_an_unknown_tone(render_jx):
    with pytest.raises(ValueError, match="Badge.*tone.*purple"):
        render_jx(_imports("Badge") + '<Badge tone="purple">x</Badge>')


# ── Badges built on Badge ────────────────────────────────────────────

SECTION_BADGE = ["inline-block", "text-[0.7rem]", "px-3", "py-1", "uppercase", "tracking-[0.06em]", "mb-2"]


@pytest.mark.parametrize(("tone", "cls"), [("sky", "clay-badge"), ("amber", "clay-badge-amber")])
def test_section_badge_is_an_uppercase_badge_above_a_heading(render_jx, tone, cls):
    html = render_jx(_imports("SectionBadge") + f'<SectionBadge tone="{tone}">Teacher Portal</SectionBadge>')
    badge = parse(html).find("span")

    assert badge.classes == [cls, *SECTION_BADGE]
    assert badge.all_text == "Teacher Portal"


def test_section_badge_can_be_a_div(render_jx):
    assert parse(render_jx(_imports("SectionBadge") + '<SectionBadge tag="div">x</SectionBadge>')).find("div", "clay-badge")


@pytest.mark.parametrize(("tone", "cls"), [("sky", "clay-badge"), ("green", "clay-badge-green"), ("amber", "clay-badge-amber")])
def test_count_pill_is_an_inline_badge(render_jx, tone, cls):
    pill = parse(render_jx(_imports("CountPill") + f'<CountPill tone="{tone}">12</CountPill>')).find("span")

    assert pill.classes == [cls, "inline"]
    assert pill.all_text == "12"


@pytest.mark.parametrize(
    ("status", "cls", "dot"),
    [("matched", "clay-badge-green", "bg-green-500"), ("unmatched", "clay-badge-amber", "bg-yellow-400")],
)
def test_status_pill_is_a_badge_with_its_own_dot(render_jx, status, cls, dot):
    pill = parse(render_jx(_imports("StatusPill") + f'<StatusPill status="{status}">Matched</StatusPill>')).find("span")

    assert pill.classes == [cls, "text-[0.78rem]", "px-3", "py-1", "border-[1.5px]"]
    assert dot in pill.children[0].classes
    assert pill.all_text == "Matched"


@pytest.mark.parametrize(
    ("kind", "classes", "label"),
    [("pdf", ["clay-badge-red"], "PDF"), ("md", ["clay-badge", "text-sky-700"], "Markdown")],
)
def test_file_type_badge_names_the_file_type(render_jx, kind, classes, label):
    badge = parse(render_jx(_imports("FileTypeBadge") + f'<FileTypeBadge type="{kind}" />')).find("span")

    assert badge.classes[: len(classes)] == classes
    assert {"uppercase", "text-[0.7rem]", "px-2.5", "py-[3px]"} <= set(badge.classes)
    assert badge.all_text == label


def test_file_type_badge_raises_on_an_unknown_type(render_jx):
    with pytest.raises(ValueError, match="FileTypeBadge.*type.*docx"):
        render_jx(_imports("FileTypeBadge") + '<FileTypeBadge type="docx" />')


# ── Special buttons ──────────────────────────────────────────────────


def test_google_button_links_with_the_google_mark(render_jx):
    html = render_jx(_imports("GoogleButton") + '<GoogleButton href="/login/google">Sign in with Google</GoogleButton>')
    link = parse(html).find("a")

    assert link.classes == ["btn-google"]
    assert link.attrs["href"] == "/login/google"
    assert link.find("img").attrs["alt"] == "Google"
    assert link.all_text == "Sign in with Google"


def test_google_button_without_a_link_is_a_button_for_its_form(render_jx):
    html = render_jx(_imports("GoogleButton") + '<GoogleButton type="submit">Sign up with Google</GoogleButton>')
    button = parse(html).find("button")

    assert button.classes == ["btn-google"]
    assert button.attrs["type"] == "submit"
    assert "href" not in button.attrs
    assert button.find("img").attrs["alt"] == "Google"
    assert button.all_text == "Sign up with Google"


def test_lang_button_marks_the_active_language_with_a_check(render_jx):
    active = parse(render_jx(_imports("LangButton") + '<LangButton type="submit" active>English</LangButton>')).find("button")
    idle = parse(render_jx(_imports("LangButton") + "<LangButton>Ελληνικά</LangButton>")).find("button")

    assert active.classes == ["btn-lang", "active"]
    assert active.attrs["type"] == "submit"
    assert active.find("svg")
    assert idle.classes == ["btn-lang"]
    assert idle.attrs["type"] == "button"
    assert not idle.find_all("svg")


def test_audio_button_is_an_icon_only_button_with_a_label(render_jx):
    html = render_jx(_imports("AudioButton") + '<AudioButton label="Read aloud" id="demoSpeak" onclick="speak()" />')
    button = parse(html).find("button")

    assert button.classes == ["audio-play-btn"]
    assert (button.attrs["aria-label"], button.attrs["id"], button.attrs["type"]) == ("Read aloud", "demoSpeak", "button")
    assert button.attrs["onclick"] == "speak()"
    assert button.find("svg")


def test_audio_button_has_a_large_size_with_a_bigger_icon(render_jx):
    small = parse(render_jx(_imports("AudioButton") + '<AudioButton label="Listen" />')).find("button")
    large = parse(render_jx(_imports("AudioButton") + '<AudioButton label="Listen" size="lg" />')).find("button")

    assert large.classes == ["audio-play-btn", "audio-play-btn-lg"]
    assert "w-10" in large.find("svg").classes
    assert "w-5" in small.find("svg").classes

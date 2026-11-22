"""Composed components in templates/components/: built from the bases in templates/components/base/."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.support.html import parse
from tests.support.jx import imports as _imports

pytestmark = pytest.mark.unit


# ── IconBox ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tone", "bg", "border"),
    [("sky", "bg-sky-50", "border-card-sky-border"), ("green", "bg-green-50", "border-card-green-border"),
     ("amber", "bg-amber-50", "border-card-amber-border"), ("rose", "bg-rose-50", "border-card-rose-border"),
     ("purple", "bg-purple-50", "border-card-purple-border"), ("pink", "bg-pink-50", "border-card-pink-border")],
)
def test_icon_box_is_a_pale_tile_in_each_tone(render_jx, tone, bg, border):
    box = parse(render_jx(_imports("IconBox") + f'<IconBox icon="users" tone="{tone}" />')).find("div")

    assert {bg, border, "border-2"} <= set(box.classes)
    assert not [c for c in box.classes if c.startswith("shadow")]
    assert box.find("svg")


@pytest.mark.parametrize(
    ("size", "box", "icon"), [("sm", "w-9", "w-4"), ("md", "w-10", "w-5"), ("lg", "w-12", "w-6"), ("xl", "w-16", "w-8")]
)
def test_icon_box_sizes_scale_the_box_and_its_icon(render_jx, size, box, icon):
    tile = parse(render_jx(_imports("IconBox") + f'<IconBox icon="users" size="{size}" class="mx-auto" />')).find("div")

    assert box in tile.classes
    assert "mx-auto" in tile.classes
    assert icon in tile.find("svg").classes


def test_icon_box_raises_on_an_unknown_tone(render_jx):
    with pytest.raises(ValueError, match="IconBox.*tone.*gray"):
        render_jx(_imports("IconBox") + '<IconBox icon="users" tone="gray" />')


# ── StatTile ─────────────────────────────────────────────────────────


#: What a stat tile adds to its Card: the old impact-card padding, centring and thicker border.
STAT_TILE = {"text-center", "px-4", "py-[22px]", "border-[length:var(--clay-border-width)]"}


@pytest.mark.parametrize(
    ("tone", "card"),
    [("sky", "clay-card"), ("green", "clay-card-green"), ("amber", "clay-card-amber"), ("rose", "clay-card-rose")],
)
def test_stat_tile_shows_value_then_label_on_a_card(render_jx, tone, card):
    html = render_jx(_imports("StatTile") + f'<StatTile tone="{tone}" label="Learners" value="42" sub="this term" />')
    tile = parse(html).find("div", card)
    value = tile.find(cls="display-font")
    colour = {"sky": "text-primary", "green": "text-accent", "amber": "text-amber-600", "rose": "text-rose-600"}[tone]

    assert STAT_TILE <= set(tile.classes)
    assert value.all_text == "42"
    assert colour in value.classes
    assert tile.all_text == "42 Learners this term"


def test_stat_tile_with_an_icon_puts_its_icon_box_on_top(render_jx):
    tile = parse(render_jx(_imports("StatTile") + '<StatTile tone="green" icon="clock" label="Hours" value="3.5" />')).find(
        "div", "clay-card-green"
    )

    assert tile.children[0].find("svg")
    assert "bg-green-50" in tile.children[0].classes


def test_stat_tile_raises_on_an_unknown_tone(render_jx):
    with pytest.raises(ValueError, match="StatTile.*tone.*purple"):
        render_jx(_imports("StatTile") + '<StatTile tone="purple" label="x" value="1" />')


# ── QuickAction ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("tone", "cls"), [("sky", "quick-action-card"), ("green", "quick-action-card-green"),
                                           ("amber", "quick-action-card-amber"), ("rose", "quick-action-card-rose")])
def test_quick_action_stacks_icon_title_and_description(render_jx, tone, cls):
    html = render_jx(
        _imports("QuickAction")
        + f'<QuickAction href="/people" tone="{tone}" icon="users" title="Manage people" description="Add and match" />'
    )
    link = parse(html).find("a")

    assert cls in link.classes
    assert link.attrs["href"] == "/people"
    assert link.find("h3").all_text == "Manage people"
    assert f"text-{tone}-900" in link.find("h3").classes
    assert link.find("p").all_text == "Add and match"


def test_a_row_quick_action_leads_with_an_eyebrow_and_ends_with_a_mirrored_arrow(render_jx):
    html = render_jx(
        _imports("QuickAction")
        + '<QuickAction layout="row" href="/t/1" tone="green" icon="bookmark" eyebrow="Start here"'
        ' title="Fractions" description="Your level" onclick="track()" />'
    )
    link = parse(html).find("a")

    assert {"flex", "items-center"} <= set(link.classes)
    assert link.attrs["onclick"] == "track()"
    assert link.all_text == "Start here Fractions Your level"
    assert {"icon-flip-rtl", "text-accent"} <= set(link.children[-1].classes)


def test_quick_action_raises_on_an_unknown_layout(render_jx):
    with pytest.raises(ValueError, match="QuickAction.*layout.*grid"):
        render_jx(_imports("QuickAction") + '<QuickAction layout="grid" href="/" icon="users" title="x" />')


# ── ProgressBar ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("tone", "fill"), [("sky", "bg-sky-500"), ("green", "bg-green-500"), ("amber", "bg-amber-500")])
def test_progress_bar_fills_to_its_value(render_jx, tone, fill):
    track = parse(render_jx(_imports("ProgressBar") + f'<ProgressBar value={{{{ 40 }}}} tone="{tone}" />')).find("div")
    bar = track.children[0]

    assert track.attrs["role"] == "progressbar"
    assert track.attrs["aria-valuenow"] == "40"
    assert fill in bar.classes
    assert bar.attrs["style"] == "width: 40%"


def test_progress_bar_clamps_its_value(render_jx):
    over = parse(render_jx(_imports("ProgressBar") + "<ProgressBar value={{ 140 }} />")).find("div")
    under = parse(render_jx(_imports("ProgressBar") + "<ProgressBar value={{ -5 }} />")).find("div")

    assert over.children[0].attrs["style"] == "width: 100%"
    assert under.children[0].attrs["style"] == "width: 0%"


@pytest.mark.parametrize(("size", "height"), [("xs", "h-1.5"), ("sm", "h-2"), ("md", "h-3")])
def test_progress_bar_sizes(render_jx, size, height):
    track = parse(render_jx(_imports("ProgressBar") + f'<ProgressBar value={{{{ 1 }}}} size="{size}" />')).find("div")

    assert height in track.classes


# ── StepIndicator ────────────────────────────────────────────────────


def test_step_indicator_marks_done_current_and_upcoming_steps(render_jx):
    row = parse(render_jx(_imports("StepIndicator") + "<StepIndicator current={{ 2 }} />")).find("ol")
    steps = row.find_all("li", "step-item")

    assert [s.classes[-1] for s in steps] == ["step-done", "step-current", "step-upcoming"]
    assert [s.attrs.get("aria-current") for s in steps] == [None, "step", None]
    assert row.attrs["aria-label"] == "Step 2 of 3"


def test_step_indicator_numbers_every_step_even_once_done(render_jx):
    row = parse(render_jx(_imports("StepIndicator") + "<StepIndicator current={{ 2 }} />")).find("ol")

    assert [d.all_text for d in row.find_all("span", "step-dot")] == ["1", "2", "3"]


def test_step_indicator_names_each_step_of_the_sign_up_journey(render_jx):
    row = parse(render_jx(_imports("StepIndicator") + "<StepIndicator current={{ 1 }} />")).find("ol")

    assert [n.all_text for n in row.find_all("span", "step-name")] == ["Account", "About you", "Quiz"]


def test_a_two_step_indicator_drops_the_quiz(render_jx):
    row = parse(render_jx(_imports("StepIndicator") + "<StepIndicator total={{ 2 }} current={{ 2 }} />")).find("ol")

    assert [n.all_text for n in row.find_all("span", "step-name")] == ["Account", "About you"]
    assert row.attrs["aria-label"] == "Step 2 of 2"


# ── JourneyScene / JourneyLoader ─────────────────────────────────────


def test_journey_scene_draws_its_illustration_for_screen_readers_to_skip(render_jx):
    art = parse(render_jx(_imports("JourneyScene") + '<JourneyScene name="quiz" class="w-28" />')).find("svg")

    assert {"journey-scene", "journey-scene-quiz", "w-28"} <= set(art.classes)
    assert art.attrs["aria-hidden"] == "true"
    assert art.attrs["viewbox"] == "0 0 200 200"


def test_journey_scene_raises_on_an_unknown_name(render_jx):
    with pytest.raises(ValueError, match="JourneyScene.*name.*rocket"):
        render_jx(_imports("JourneyScene") + '<JourneyScene name="rocket" />')


def test_journey_loader_is_a_hidden_overlay_announcing_its_working_line(render_jx):
    html = render_jx(_imports("JourneyLoader") + '<JourneyLoader scene="quiz" step={{ 3 }} working="Looking at your answers" />')
    root = parse(html)
    overlay = root.find("div", "journey-loader")

    assert "hidden" in overlay.attrs
    assert overlay.find("svg", "journey-scene-quiz")
    status = overlay.find(None, "journey-status")
    assert (status.attrs["role"], status.attrs["aria-live"]) == ("status", "polite")
    assert status.find(None, "journey-title").all_text == "Looking at your answers"
    assert "window.JourneyLoader" in html


def test_journey_loader_tracks_the_step_it_is_finishing_as_current(render_jx):
    track = parse(render_jx(_imports("JourneyLoader") + '<JourneyLoader scene="quiz" step={{ 2 }} working="Saving" />')).find(
        "ol", "journey-track"
    )
    stops = track.find_all("li", "journey-stop")

    assert [s.classes[-1] for s in stops] == ["journey-done", "journey-current", "journey-upcoming"]
    assert track.attrs["aria-hidden"] == "true"


def test_a_two_step_journey_loader_has_two_stops(render_jx):
    track = parse(
        render_jx(_imports("JourneyLoader") + '<JourneyLoader scene="quiz" step={{ 2 }} total={{ 2 }} working="Saving" />')
    ).find("ol", "journey-track")

    assert len(track.find_all("li", "journey-stop")) == 2


def test_journey_loader_names_the_next_step_and_the_finish_for_its_script(render_jx):
    html = render_jx(_imports("JourneyLoader") + '<JourneyLoader scene="quiz" step={{ 1 }} working="Opening" />')
    overlay = parse(html).find("div", "journey-loader")

    assert overlay.attrs["data-next"] == "Next: About you"
    last = parse(
        render_jx(_imports("JourneyLoader") + '<JourneyLoader scene="quiz" step={{ 3 }} working="Looking" />')
    ).find("div", "journey-loader")
    assert last.attrs["data-next"] == "All steps done"


# ── Field ────────────────────────────────────────────────────────────


def test_field_labels_its_control(render_jx):
    html = render_jx(
        _imports("Field", "Input") + '<Field label="Name" for_id="name" required class="mb-4"><Input id="name" /></Field>'
    )
    wrapper = parse(html).find("div")
    label = wrapper.find("label")

    assert "mb-4" in wrapper.classes
    assert label.attrs["for"] == "name"
    assert label.all_text == "Name *"
    assert wrapper.find("input").attrs["id"] == "name"


# ── SectionTitle ─────────────────────────────────────────────────────


@pytest.mark.parametrize("tone", ["sky", "green", "amber"])
def test_section_title_pairs_an_icon_heading_and_count(render_jx, tone):
    html = render_jx(_imports("SectionTitle") + f'<SectionTitle icon="users" tone="{tone}" count={{{{ 7 }}}}>Teachers</SectionTitle>')
    title = parse(html).find("div", "section-title")

    assert title.find("h2").all_text == "Teachers"
    assert title.find("span", "inline").all_text == "7"
    assert f"bg-{tone}-50" in title.children[0].classes


# ── WorksheetCard ────────────────────────────────────────────────────


def _worksheet(**overrides):
    fields = {"id": 5, "title": "Fractions 1", "subject": "Maths", "topic": "Fractions", "file_type": "pdf"}
    return SimpleNamespace(**{**fields, **overrides})


def test_teacher_worksheet_card_suggests_pairs_and_offers_assign(render_jx):
    ws = _worksheet()
    pair = SimpleNamespace(
        worksheets=[ws],
        learner=SimpleNamespace(name="Ana", username="ana"),
        volunteer=SimpleNamespace(name="Ben", email="ben@x.org"),
    )
    html = render_jx(
        _imports("WorksheetCard")
        + "{#def ws, pairs #}"
        '<WorksheetCard ws={{ ws }} primary_url="/p/5" primary_label="Preview" matched_pairs={{ pairs }}'
        ' assign_url="/a/5" assign_label="Assign" />',
        ws=ws, pairs=[pair],
    )
    card = parse(html).find("article")

    assert card.attrs["id"] == "ws-card-5"
    assert (card.attrs["data-title"], card.attrs["data-subject"]) == ("fractions 1", "maths")
    assert card.find("h3").all_text == "Fractions 1"
    assert "Ana & Ben" in card.all_text
    assert card.find("span", "clay-badge-red").all_text == "PDF"
    preview, assign = card.find_all("a")
    assert ("btn-sky" in preview.classes, "btn-accent" in assign.classes) == (True, True)


def test_volunteer_worksheet_card_has_one_full_width_action(render_jx):
    html = render_jx(
        _imports("WorksheetCard") + '{#def ws #}<WorksheetCard ws={{ ws }} primary_url="/v/5" primary_label="View" />',
        ws=_worksheet(file_type="md", topic=None),
    )
    card = parse(html).find("article")
    (only,) = card.find_all("a")

    assert {"btn-accent", "w-full"} <= set(only.classes)
    assert card.find("span", "text-sky-700").all_text == "Markdown"


def test_a_recommended_worksheet_card_turns_amber(render_jx):
    html = render_jx(
        _imports("WorksheetCard")
        + '{#def ws #}<WorksheetCard ws={{ ws }} primary_url="/v" primary_label="View" highlighted />',
        ws=_worksheet(),
    )
    card = parse(html).find("article")

    assert "clay-card-amber" in card.classes
    assert "Recommended" in card.all_text


# ── MatchScoreChip ───────────────────────────────────────────────────


@pytest.mark.parametrize("band", ["strong", "good", "fair", "weak"])
def test_match_score_chip_colours_by_band(render_jx, band):
    html = render_jx(_imports("MatchScoreChip") + "{#def match #}<MatchScoreChip match={{ match }} />",
                     match={"score": 82, "band": band})
    chip = parse(html).find("span")

    assert chip.classes == ["match-score-chip", f"match-score-{band}"]
    assert chip.all_text == "82"
    assert "82" in (chip.attrs["title"] or "")


def test_an_unmatched_person_has_no_score_chip(render_jx):
    assert render_jx(_imports("MatchScoreChip") + "<MatchScoreChip match={{ none }} />").strip() == ""


def test_match_score_chip_raises_on_an_unknown_band(render_jx):
    with pytest.raises(ValueError, match="MatchScoreChip.*band.*great"):
        render_jx(_imports("MatchScoreChip") + "{#def match #}<MatchScoreChip match={{ match }} />",
                  match={"score": 1, "band": "great"})


# ── Game overlays ────────────────────────────────────────────────────


def test_mc_options_defines_its_styles_and_script_api(render_jx):
    html = render_jx(_imports("McOptions") + "<McOptions />")

    assert ".mc-option" in html
    assert "window.MCOptions" in html or "MCOptions =" in html


def test_mc_options_enlarges_emoji_only_answers(render_jx):
    html = render_jx(_imports("McOptions") + "<McOptions />")

    assert ".mc-option-emoji" in html
    assert "Extended_Pictographic" in html


def test_level_up_modal_is_a_hidden_amber_card_dialog_with_a_dismiss_button(render_jx):
    root = parse(render_jx(_imports("LevelUpModal") + "<LevelUpModal />"))
    modal = root.find("div")
    card = modal.find("div", "clay-card-amber")

    assert modal.attrs["id"] == "levelUpModal"
    assert "hidden" in modal.classes
    assert (card.attrs["role"], card.attrs["aria-modal"], card.attrs["aria-labelledby"]) == ("dialog", "true", "levelUpTitle")
    assert card.find("button", "btn-accent").attrs["onclick"] == "window.dismissLevelUp()"
    assert "window.showLevelUpModal" in root.find_all("script")[-1].all_text


def test_level_up_modal_sets_the_level_number_inside_the_badge_art(render_jx):
    stage = parse(render_jx(_imports("LevelUpModal") + "<LevelUpModal />")).find("div", "level-up-stage")
    badge = stage.find("div", "level-up-badge")

    assert stage.attrs["aria-hidden"] == "true"
    assert badge.find("img").attrs["src"] == "/static/svg/level-badge.svg"
    assert badge.find("span").attrs["id"] == "levelUpNumber"


def test_level_up_modal_builds_new_items_from_an_amber_card_template_without_emoji(render_jx):
    root = parse(render_jx(_imports("LevelUpModal") + "<LevelUpModal />"))
    template = root.find("template")

    assert template.attrs["id"] == "levelUpItemTemplate"
    assert template.find("div", "clay-card-amber").find("svg")


def _completion_overlay(render_jx):
    html = render_jx(_imports("CompletionOverlay") + "{#def lesson #}<CompletionOverlay lesson={{ lesson }} />",
                     lesson=SimpleNamespace(title="Shapes", topic_id=3))
    return html, parse(html)


def test_completion_overlay_is_a_hidden_dialog_naming_the_lesson_and_linking_back_to_its_topic(render_jx):
    _, root = _completion_overlay(render_jx)
    screen = root.find("div")
    card = screen.find("div", "clay-card")

    assert screen.attrs["id"] == "completionScreen"
    assert "hidden" in screen.classes
    assert (card.attrs["role"], card.attrs["aria-modal"], card.attrs["aria-labelledby"]) == ("dialog", "true", "completionTitle")
    assert card.find("span", "completion-lesson").all_text == "Shapes"
    hrefs = [a.attrs["href"] for a in root.find_all("a")]
    assert "/learner/learn/topics/3/lessons" in hrefs
    assert "window.CompletionOverlay" in root.find_all("script")[-1].all_text


def test_completion_overlay_stages_the_celebration_art_and_swaps_in_the_trophy_for_a_finished_topic(render_jx):
    _, root = _completion_overlay(render_jx)
    stage = root.find("div", "completion-stage")
    art = stage.find("img", "completion-art")

    assert stage.attrs["aria-hidden"] == "true"
    assert art.attrs["alt"] == ""
    assert art.attrs["src"] == art.attrs["data-lesson-art"] == "/static/svg/celebrate.svg"
    assert art.attrs["data-topic-art"] == "/static/svg/trophy.svg"


def test_completion_overlay_shows_xp_as_a_gold_sticker_and_the_score_as_a_green_one(render_jx):
    _, root = _completion_overlay(render_jx)
    xp, score = root.find_all("div", "completion-sticker")

    assert "clay-card-amber" in xp.classes and xp.find("p").attrs["id"] == "completionXP"
    assert "clay-card-green" in score.classes and score.find("p").attrs["id"] == "completionScore"


def test_completion_overlays_next_topic_is_the_green_clickable_card_hidden_until_shown(render_jx):
    _, root = _completion_overlay(render_jx)
    nxt = root.find("button", "quick-action-card-green")

    assert nxt.attrs["id"] == "nextLessonCard"
    assert "hidden" in nxt.classes
    assert nxt.find("div", "bg-green-50").find("svg")


def test_completion_overlays_topic_finished_line_sits_on_an_amber_card(render_jx):
    _, root = _completion_overlay(render_jx)
    finished = next(d for d in root.find_all("div") if d.attrs.get("id") == "completedAllSection")

    assert "hidden" in finished.classes
    assert "You completed all lessons in this topic!" in finished.find("div", "clay-card-amber").all_text


# ── TopicCard ────────────────────────────────────────────────────────


def _topic():
    return SimpleNamespace(id=7, title="Fractions", description="Parts of a whole", icon="star", level=2)


def _topic_card(render_jx, state):
    source = _imports("TopicCard") + "{#def topic #}" + f'<TopicCard topic={{{{ topic }}}} state="{state}" href="/t/7" />'
    return parse(render_jx(source, topic=_topic())).children[0]


def test_topic_card_completed_is_a_green_link_so_the_topic_can_be_redone(render_jx):
    card = _topic_card(render_jx, "completed")

    assert (card.tag, card.attrs["href"]) == ("a", "/t/7")
    assert {"topic-card", "topic-card-completed"} <= set(card.classes)
    assert "fa-lock-open" in card.find("div", "topic-icon-completed").find("i").classes
    assert card.find("span", "finished-pill").all_text == "Finished"
    assert card.find("div", "arrow-circle")


def test_topic_card_in_progress_is_an_amber_link_with_its_own_pill(render_jx):
    card = _topic_card(render_jx, "in_progress")

    assert (card.tag, card.attrs["href"]) == ("a", "/t/7")
    assert "topic-card-in-progress" in card.classes
    assert "fa-star" in card.find("div", "topic-icon-default").find("i").classes
    assert card.find("span", "in-progress-pill").all_text == "In Progress"


def test_topic_card_empty_is_a_plain_link_with_no_pill(render_jx):
    card = _topic_card(render_jx, "empty")

    assert (card.tag, card.attrs["href"]) == ("a", "/t/7")
    assert card.classes == ["topic-card"]
    assert card.find_all("span") == []
    assert card.find("div", "arrow-circle")


def test_topic_card_recommended_is_a_green_link_that_tracks_the_click(render_jx):
    card = _topic_card(render_jx, "recommended")

    assert (card.tag, card.attrs["href"]) == ("a", "/t/7")
    assert "topic-card-recommended" in card.classes
    assert card.find("span", "start-here-pill").all_text == "Start Here"
    assert "map_recommendation_clicked" in card.attrs["onclick"]


@pytest.mark.parametrize("state", ["completed", "in_progress", "recommended"])
def test_topic_card_pills_size_their_icon_from_css_not_inline_style(render_jx, state):
    card = _topic_card(render_jx, state)

    assert "style" not in card.find("span").find("i").attrs


def test_topic_card_raises_on_an_unknown_state(render_jx):
    with pytest.raises(ValueError, match="TopicCard.*state.*locked"):
        _topic_card(render_jx, "locked")

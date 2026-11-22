"""Learner routes: onboarding gates, the learning path, games, worksheets."""

from __future__ import annotations

import re

import pytest

from tests.support.assertions import assert_denied, assert_redirects_to, assert_success
from tests.support.auth import login_as
from tests.support.factories import (
    make_feature_announcement,
    make_learner,
    make_learning_content,
    make_teacher,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.web

AJAX = {"X-Requested-With": "XMLHttpRequest"}

GAME_PAGES = [
    ("rocket", "/learner/learn/rocket/{lesson_id}"),
    ("word_storm", "/learner/learn/word-storm/{lesson_id}"),
    ("match_up", "/learner/learn/match-up/{lesson_id}"),
    ("garden_grow", "/learner/learn/garden-grow/{lesson_id}"),
    ("potion_workshop", "/learner/learn/potion-workshop/{lesson_id}"),
]


# ── dashboard ────────────────────────────────────────────────────────────────


def test_learner_dashboard_renders_for_an_authenticated_learner(client, db_session, authenticated_learner):
    body = assert_success(client.get("/learner/")).get_data(as_text=True)

    assert "learner" in body.lower()


@pytest.mark.parametrize(
    "path", ["/learner/", "/learner/learn/subjects"]
)
def test_learner_pages_render(client, db_session, authenticated_learner, path):
    assert_success(client.get(path))


def test_the_dashboard_renders_its_tabs_stats_and_wardrobe(client, db_session, authenticated_learner):
    body = assert_success(client.get("/learner/")).get_data(as_text=True)

    for marker in [
        "Welcome back, Test Learner", "My Learning", "My Character", "Hours Learned", "Placement Levels",
        "English Grammar: Lvl 1", "Topics Completed", "MAP Status", "Current Learning Progress",
        "Your Volunteer Match", 'class="av-fig" viewBox="0 0 200 300" role="img" aria-label="My Character"', "Wardrobe",
        'id="tab-learning"', 'id="tab-character"', "onclick=\"switchTab('learning')\"",
        'role="tab"', 'aria-selected="true"', 'aria-controls="section-character"', 'role="tabpanel"',
        'id="section-learning"', 'id="section-character"', 'data-layer="species"', 'data-av-tabs="group"',
        'data-av-panel="face:species"', 'data-item-id="', 'onclick="avEquip(this)"',
        "var faceState = ", "function markWorksheetDone(",
    ]:
        assert marker in body


def test_the_dashboard_reminds_a_deferred_learner_to_take_the_placement_test(client, db_session, school):
    teacher = make_teacher(db_session, school)
    deferred = make_learner(db_session, school, teacher, map_test_deferred=True)
    login_as(client, deferred)

    body = assert_success(client.get("/learner/")).get_data(as_text=True)

    assert "You saved the MAP test for later" in body
    assert 'href="/learner/map-intro"' in body
    assert "Take MAP Test" in body


def test_the_dashboard_recommends_the_placement_topic_and_tracks_the_click(client, db_session, authenticated_learner):
    subject, topic, _lesson, _question = make_learning_content(db_session)
    authenticated_learner.subject_levels = {subject.name: topic.level}
    db_session.commit()

    body = assert_success(client.get("/learner/")).get_data(as_text=True)

    card = re.search(rf'<a [^>]*href="/learner/learn/topics/{topic.id}/lessons"[^>]*>', body)
    assert card is not None
    assert "map_recommendation_clicked" in card.group()
    assert f"topic_id: {topic.id}," in card.group()
    assert "Recommended start" in body
    assert topic.title in body


def test_the_dashboard_drops_the_recommended_start_once_a_lesson_is_finished(client, db_session, authenticated_learner):
    subject, topic, lesson, _question = make_learning_content(db_session)
    authenticated_learner.subject_levels = {subject.name: topic.level}
    authenticated_learner.completed_lesson_ids = [lesson.id]
    db_session.commit()

    body = assert_success(client.get("/learner/")).get_data(as_text=True)

    assert "Recommended start" not in body
    assert "map_recommendation_clicked" not in body


def test_the_dashboard_shows_a_pending_feature_announcement(client, db_session, authenticated_learner):
    make_feature_announcement(db_session, roles=["learner"], title="Brand new garden")

    body = assert_success(client.get("/learner/")).get_data(as_text=True)

    assert "Brand new garden" in body


def test_a_teacher_cannot_reach_the_learner_area(client, db_session, authenticated_teacher):
    assert client.get("/learner/").status_code == 403


# ── onboarding gates ─────────────────────────────────────────────────────────


def test_a_learner_who_has_not_taken_the_survey_is_sent_to_it(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(
        db_session, school, teacher, completed_survey=False, completed_map_test=False
    )
    login_as(client, fresh)

    assert_redirects_to(client.get("/learner/"), "/learner/survey")


@pytest.mark.parametrize("path", ["/learner/", "/learner/learn/subjects"])
def test_a_learner_who_took_the_survey_but_not_the_placement_test_is_sent_to_it(client, db_session, school, path):
    # Sending them back to the survey looped: re-submitting it returns to the dashboard.
    teacher = make_teacher(db_session, school)
    halfway = make_learner(db_session, school, teacher, completed_survey=True, completed_map_test=False)
    login_as(client, halfway)

    assert_redirects_to(client.get(path), "/learner/map-intro")
    assert_success(client.get("/learner/map-intro"))


def test_the_survey_page_renders_for_a_new_learner(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    assert_success(client.get("/learner/survey"))


def test_the_survey_choices_are_shown_in_the_learners_language_but_still_submit_english(
    client, db_session, school
):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)
    with client.session_transaction() as session:
        session["ui_lang"] = "el"

    html = client.get("/learner/survey").get_data(as_text=True)

    assert "Αθλητισμός" in html  # hobby label
    assert "Αραβικά" in html  # language name
    assert 'value="Sports"' in html  # saved answers stay English
    assert 'name="language_level_Arabic" value="Beginner"' in html
    assert ">Sports<" not in html and "Outgoing &amp; Social<" not in html


def test_a_learner_who_finished_the_survey_can_still_reach_it_to_redo_it(client, db_session, authenticated_learner):
    assert_success(client.get("/learner/survey"))


def test_the_redo_survey_page_renders_when_survey_data_predates_the_field(client, db_session, school):
    """`scripts/flood.py` seeds learners with `completed_survey=True` and no
    `survey_data` at all — the redo page must not 500 on that combination."""
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_survey=True, survey_data=None)
    login_as(client, fresh)

    assert_success(client.get("/learner/survey"))


def test_submitting_the_survey_records_it(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    client.post(
        "/learner/survey",
        data={"languages": ["Arabic"], "language_level_Arabic": "beginner"},
    )

    db_session.expire_all()
    assert fresh.completed_survey is True


def test_a_new_learners_first_submission_is_sent_to_the_map_intro(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    response = client.post(
        "/learner/survey",
        data={"name": "Ada", "languages": ["Arabic"], "language_level_Arabic": "beginner"},
    )

    assert_redirects_to(response, "/learner/map-intro")


def test_redoing_the_survey_is_sent_back_to_the_dashboard_not_the_map_intro(client, db_session, authenticated_learner):
    response = client.post(
        "/learner/survey",
        data={"name": "New Name", "languages": ["Arabic"], "language_level_Arabic": "beginner"},
    )

    assert_redirects_to(response, "/learner/")


def test_redoing_the_survey_keeps_the_learners_existing_name_rather_than_the_submitted_one(
    client, db_session, authenticated_learner
):
    original_name = authenticated_learner.name

    client.post(
        "/learner/survey",
        data={"name": "Somebody Else", "languages": ["Arabic"], "language_level_Arabic": "beginner"},
    )

    db_session.expire_all()
    assert authenticated_learner.name == original_name


def test_the_redo_survey_page_autofills_past_language_selections(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(
        db_session,
        school,
        teacher,
        completed_survey=True,
        survey_data={"languages": [{"language": "Arabic", "level": "Intermediate"}]},
    )
    login_as(client, fresh)

    body = assert_success(client.get("/learner/survey")).get_data(as_text=True)

    intermediate_radio = re.search(
        r'name="language_level_Arabic"\s+value="Intermediate"[^>]*', body
    )
    assert intermediate_radio is not None
    assert "checked" in intermediate_radio.group()


def test_a_new_learner_sees_the_survey_step_its_fields_and_an_editable_name(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_survey=False, completed_map_test=False)
    login_as(client, fresh)

    body = assert_success(client.get("/learner/survey")).get_data(as_text=True)

    for marker in [
        "Step 2 of 3", "Tell us about yourself", 'id="surveyForm"', 'action="/learner/survey"',
        'name="name"', 'name="age"', 'name="personality"', 'name="traits"', 'name="hobbies"',
        'name="languages"', 'name="language_level_English"', 'name="tech_interest"', 'name="match_activities"',
        'class="lang-check"', 'id="lang-none-learner"', 'id="error-traits"', 'id="error-hobbies"',
        'id="error-languages"', 'id="error-tech_interest"', 'id="error-match_activities"', 'type="submit"',
        "function skipSurvey(", "/api/skip-map-test",
    ]:
        assert marker in body
    assert re.search(r'<input[^>]*name="name"[^>]*\brequired\b', body)


def test_the_redo_survey_locks_the_name_and_checks_saved_answers(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(
        db_session, school, teacher, name="Ada",
        survey_data={"personality": "Quiet & Thoughtful", "traits": ["Patient"], "hobbies": ["Music"],
                     "tech_interest": ["Coding"], "match_activities": ["Storytelling"]},
    )
    login_as(client, fresh)

    body = assert_success(client.get("/learner/survey")).get_data(as_text=True)

    assert "Step 2 of 3" not in body
    name_input = re.search(r'<input[^>]*name="name"[^>]*>', body)
    assert name_input is not None
    assert 'value="Ada"' in name_input.group()
    assert "readonly" in name_input.group()
    for name, value in [
        ("personality", "Quiet &amp; Thoughtful"), ("traits", "Patient"), ("hobbies", "Music"),
        ("tech_interest", "Coding"), ("match_activities", "Storytelling"),
    ]:
        field = re.search(rf'<input[^>]*name="{name}"[^>]*value="{value}"[^>]*>', body)
        assert field is not None and "checked" in field.group(), name


def test_the_placement_test_intro_offers_start_and_skip(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_map_test=False)
    login_as(client, fresh)

    body = assert_success(client.get("/learner/map-intro")).get_data(as_text=True)

    for marker in [
        "Step 3 of 3", "Start the Quiz", "Takes about", 'href="/learner/map"', 'onclick="skipMapTest()"',
        "function skipMapTest(", "/api/skip-map-test",
    ]:
        assert marker in body


def test_the_placement_test_page_holds_its_question_and_completion_ui(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_map_test=False)
    login_as(client, fresh)

    body = assert_success(client.get("/learner/map")).get_data(as_text=True)

    for marker in [
        "Assessment in Progress", "Assessment Complete!", 'id="loading-indicator"', 'id="quiz-interface"',
        'id="audio-container"', 'onclick="playQuestionAudio()"', 'id="question-audio"', 'id="question-prompt"',
        'id="question-text-title"', 'id="question-text"', 'id="options-container"', 'id="open-answer-input"',
        'id="next-button"', 'id="completion-state"', 'id="recommendation-section"',
        'id="recommendation-start-btn"', 'id="recommendation-topic"', 'id="dashboard-link"',
        'href="/learner/"', "/api/map/question", "var MAP_T = ",
        "journey-loader", "journey-scene-quiz", "Looking at your answers", "Found your place to start!",
        "All done!", "All steps done", "JourneyLoader.run(",
    ]:
        assert marker in body


def test_the_placement_test_answers_use_the_quiz_multiple_choice_buttons(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(db_session, school, teacher, completed_map_test=False)
    login_as(client, fresh)

    body = assert_success(client.get("/learner/map")).get_data(as_text=True)

    assert "MCOptions.render(" in body
    assert "option-button" not in body


def test_a_learner_who_took_the_placement_test_skips_the_intro(client, db_session, authenticated_learner):
    assert_redirects_to(client.get("/learner/map-intro"), "/learner/")


def test_a_deferred_learner_may_return_to_the_placement_test(client, db_session, school):
    """`completed_map_test` is a gate, not proof the test was taken."""

    teacher = make_teacher(db_session, school)
    deferred = make_learner(
        db_session, school, teacher, completed_map_test=True, map_test_deferred=True
    )
    login_as(client, deferred)

    assert_success(client.get("/learner/map-intro"))
    assert_success(client.get("/learner/map"))


def test_the_placement_test_sends_an_unsurveyed_learner_back(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_learner(
        db_session, school, teacher,
        completed_survey=False, completed_map_test=True, map_test_deferred=True,
    )
    login_as(client, fresh)

    assert_redirects_to(client.get("/learner/map"), "/learner/survey")


# ── the learning path ────────────────────────────────────────────────────────


def test_the_subject_list_renders(client, db_session, authenticated_learner):
    subject, _topic, _lesson, _question = make_learning_content(db_session)

    body = assert_success(client.get("/learner/learn/subjects")).get_data(as_text=True)

    assert subject.name in body


def test_the_topic_list_renders_for_a_subject(client, db_session, authenticated_learner):
    subject, topic, _lesson, _question = make_learning_content(db_session)

    body = assert_success(
        client.get(f"/learner/learn/subjects/{subject.id}/topics")
    ).get_data(as_text=True)

    assert topic.title in body


def test_an_unknown_subject_is_a_404(client, db_session, authenticated_learner):
    assert client.get("/learner/learn/subjects/999999/topics").status_code == 404


def test_the_lesson_list_renders_for_a_topic(client, db_session, authenticated_learner):
    _subject, topic, lesson, _question = make_learning_content(db_session)

    body = assert_success(
        client.get(f"/learner/learn/topics/{topic.id}/lessons")
    ).get_data(as_text=True)

    assert lesson.title in body


def test_an_unknown_topic_is_a_404(client, db_session, authenticated_learner):
    assert client.get("/learner/learn/topics/999999/lessons").status_code == 404


def test_a_lesson_overview_renders(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session)

    assert_success(client.get(f"/learner/learn/overview/{lesson.id}"))


def test_the_overview_sidebar_links_each_lesson_in_the_topic(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session)

    body = assert_success(client.get(f"/learner/learn/overview/{lesson.id}")).get_data(as_text=True)

    assert f'href="/learner/learn/overview/{lesson.id}"' in body
    assert 'href="#"' not in body


def test_the_quiz_page_renders(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session)

    assert_success(client.get(f"/learner/learn/questions/{lesson.id}"))


def page_css(client, body):
    """The page's own markup plus every static/css/pages sheet it links — the CSS it ends up with."""
    sheets = re.findall(r'href="(/static/css/pages/[\w-]+\.css)"', body)
    return body + "".join(assert_success(client.get(sheet)).get_data(as_text=True) for sheet in sheets)


@pytest.mark.parametrize("button_class", ["quiz-btn-accent", "quiz-btn-outline"])
def test_the_quiz_page_lets_hidden_hide_its_check_and_next_buttons(
    client, db_session, authenticated_learner, button_class
):
    # games.css is linked after the Tailwind stylesheet, so its `display: inline-flex`
    # beats `.hidden` at equal specificity unless the partial hides the pair itself.
    _subject, _topic, lesson, _question = make_learning_content(db_session)

    body = assert_success(client.get(f"/learner/learn/questions/{lesson.id}")).get_data(as_text=True)

    hiding_rules = re.findall(r"([^{}]*)\{\s*display:\s*none;?\s*\}", page_css(client, body))
    assert any(f".{button_class}.hidden" in selectors for selectors in hiding_rules)


def test_the_quiz_page_offers_a_hint_after_wrong_typed_answers_and_enter_to_continue(
    client, db_session, authenticated_learner
):
    _subject, _topic, lesson, _question = make_learning_content(db_session)

    body = assert_success(client.get(f"/learner/learn/questions/{lesson.id}")).get_data(as_text=True)

    assert 'id="hintButton"' in body
    assert 'id="hintAnswer"' in body
    # The hint text comes from validate-answer; the page never holds an answer of its own.
    assert "data.hint" in body
    assert "fill_blank_options" not in body
    assert "question.answer" not in body
    assert "Show hint" in body
    # Enter on the page (not just in the input) moves on once the answer is right.
    assert "document.addEventListener('keydown'" in body


LEARN_PAGES = [
    (None, "/learner/learn/subjects"),
    (None, "/learner/learn/subjects/{subject_id}/topics"),
    (None, "/learner/learn/topics/{topic_id}/lessons"),
    (None, "/learner/learn/overview/{lesson_id}"),
    (None, "/learner/learn/questions/{lesson_id}"),
    *GAME_PAGES,
]


def _learn_nav_links(body):
    """The header's desktop and mobile-menu Learn links, as raw opening tags."""
    tags = re.findall(r'<a [^>]*href="/learner/learn/subjects"[^>]*>', body)
    bar = [tag for tag in tags if 'data-label="Learn"' in tag]
    menu = [tag for tag in tags if "px-4 py-3" in tag]
    return bar, menu


@pytest.mark.parametrize("game_type,path", LEARN_PAGES)
def test_every_learn_page_marks_the_learn_nav_link_active(
    client, db_session, authenticated_learner, game_type, path
):
    subject, topic, lesson, _question = make_learning_content(db_session, game_type=game_type)
    url = path.format(subject_id=subject.id, topic_id=topic.id, lesson_id=lesson.id)

    bar, menu = _learn_nav_links(assert_success(client.get(url)).get_data(as_text=True))

    assert bar and all("nav-link-active" in tag for tag in bar)
    assert menu and all("bg-sky-100" in tag for tag in menu)


def test_the_learn_nav_link_is_not_active_on_the_dashboard(client, db_session, authenticated_learner):
    bar, menu = _learn_nav_links(assert_success(client.get("/learner/")).get_data(as_text=True))

    assert bar and all("nav-link-inactive" in tag for tag in bar)
    assert menu and not any("bg-sky-100" in tag for tag in menu)


def test_an_unknown_lesson_quiz_is_a_404(client, db_session, authenticated_learner):
    assert client.get("/learner/learn/questions/999999").status_code == 404


def test_the_subject_list_shows_its_heading_and_links_each_subject(client, db_session, authenticated_learner):
    subject, _topic, _lesson, _question = make_learning_content(db_session)

    body = assert_success(client.get("/learner/learn/subjects")).get_data(as_text=True)

    assert "Choose a Subject" in body
    assert f'href="/learner/learn/subjects/{subject.id}/topics"' in body
    assert "subject-card subject-card-0" in body


def test_the_topic_list_marks_finished_and_recommended_topics(client, db_session, authenticated_learner):
    from tests.support.factories import make_topic

    subject, topic, _lesson, _question = make_learning_content(db_session)
    finished = make_topic(db_session, subject, title="Finished Topic", level=2)
    authenticated_learner.completed_topic_ids = [finished.id]
    authenticated_learner.subject_levels = {subject.name: topic.level}
    db_session.commit()

    body = assert_success(
        client.get(f"/learner/learn/subjects/{subject.id}/topics")
    ).get_data(as_text=True)

    assert f"{subject.name} Topics" in body
    assert 'href="/learner/learn/subjects"' in body
    assert f'href="/learner/learn/topics/{topic.id}/lessons"' in body
    assert "topic-card-recommended" in body
    assert "map_recommendation_clicked" in body
    assert "topic-card-completed" in body
    assert "font-awesome" in body


def test_start_here_shows_on_the_recommended_topic_before_any_lesson_is_finished(client, db_session, authenticated_learner):
    from tests.support.html import parse

    subject, topic, _lesson, _question = make_learning_content(db_session)
    authenticated_learner.subject_levels = {subject.name: topic.level}
    db_session.commit()

    page = parse(client.get(f"/learner/learn/subjects/{subject.id}/topics").get_data(as_text=True))

    card = page.find("a", "topic-card-recommended")
    assert card.attrs["href"] == f"/learner/learn/topics/{topic.id}/lessons"
    assert card.find("span", "start-here-pill").all_text == "Start Here"


def test_start_here_goes_once_a_lesson_in_the_subject_is_finished(client, db_session, authenticated_learner):
    from tests.support.factories import make_lesson
    from tests.support.html import parse

    subject, topic, lesson, _question = make_learning_content(db_session)
    make_lesson(db_session, topic, title="Second Lesson")
    authenticated_learner.subject_levels = {subject.name: topic.level}
    authenticated_learner.completed_lesson_ids = [lesson.id]
    db_session.commit()

    page = parse(client.get(f"/learner/learn/subjects/{subject.id}/topics").get_data(as_text=True))

    assert page.find_all(cls="start-here-pill") == []
    assert page.find_all(cls="topic-card-recommended") == []


def test_start_here_goes_once_a_lesson_in_another_subject_is_finished(client, db_session, authenticated_learner):
    from tests.support.html import parse

    subject, topic, _lesson, _question = make_learning_content(db_session)
    _other_subject, _other_topic, other_lesson, _other_question = make_learning_content(db_session)
    authenticated_learner.subject_levels = {subject.name: topic.level}
    authenticated_learner.completed_lesson_ids = [other_lesson.id]
    db_session.commit()

    page = parse(client.get(f"/learner/learn/subjects/{subject.id}/topics").get_data(as_text=True))

    assert page.find_all(cls="start-here-pill") == []


def test_a_topic_with_some_lessons_finished_is_marked_in_progress(client, db_session, authenticated_learner):
    from tests.support.factories import make_lesson, make_topic
    from tests.support.html import parse

    subject, topic, lesson, _question = make_learning_content(db_session)
    make_lesson(db_session, topic, title="Second Lesson")
    untouched = make_topic(db_session, subject, title="Untouched Topic", level=2)
    make_lesson(db_session, untouched, title="Untouched Lesson")
    authenticated_learner.completed_lesson_ids = [lesson.id]
    db_session.commit()

    page = parse(client.get(f"/learner/learn/subjects/{subject.id}/topics").get_data(as_text=True))

    [card] = page.find_all("a", "topic-card-in-progress")
    assert card.attrs["href"] == f"/learner/learn/topics/{topic.id}/lessons"
    assert card.find("span", "in-progress-pill").all_text == "In Progress"


def test_a_finished_topic_is_not_also_marked_in_progress(client, db_session, authenticated_learner):
    from tests.support.html import parse

    subject, topic, lesson, _question = make_learning_content(db_session)
    authenticated_learner.completed_lesson_ids = [lesson.id]
    authenticated_learner.completed_topic_ids = [topic.id]
    db_session.commit()

    page = parse(client.get(f"/learner/learn/subjects/{subject.id}/topics").get_data(as_text=True))

    assert page.find_all(cls="topic-card-in-progress") == []
    page.find("a", "topic-card-completed")


def test_the_lesson_list_badges_each_game_and_offers_a_redo(client, db_session, authenticated_learner):
    from tests.support.factories import make_lesson

    _subject, topic, lesson, _question = make_learning_content(db_session, game_type="rocket")
    done = make_lesson(db_session, topic, title="Done Lesson", game_type="garden_grow")
    authenticated_learner.completed_lesson_ids = [done.id]
    db_session.commit()

    body = assert_success(client.get(f"/learner/learn/topics/{topic.id}/lessons")).get_data(as_text=True)

    assert f"{topic.title} Lessons" in body
    assert f'href="/learner/learn/subjects/{topic.subject_id}/topics"' in body
    assert f'href="/learner/learn/overview/{lesson.id}"' in body
    assert "game-badge-rocket" in body
    assert "game-badge-garden_grow" in body
    assert "topic-card-redo" in body


@pytest.mark.parametrize("game_type,start_url", [
    (None, "/learner/learn/questions/{lesson_id}"),
    ("rocket", "/learner/learn/rocket/{lesson_id}"),
    ("word_storm", "/learner/learn/word-storm/{lesson_id}"),
    ("match_up", "/learner/learn/match-up/{lesson_id}"),
    ("garden_grow", "/learner/learn/garden-grow/{lesson_id}"),
    ("potion_workshop", "/learner/learn/potion-workshop/{lesson_id}"),
])
def test_the_lesson_overview_starts_the_lessons_own_game(
    client, db_session, authenticated_learner, game_type, start_url
):
    _subject, topic, lesson, _question = make_learning_content(db_session, game_type=game_type)

    body = assert_success(client.get(f"/learner/learn/overview/{lesson.id}")).get_data(as_text=True)

    assert f"Understanding {lesson.title}" in body
    assert f"onclick=\"window.location.href = '{start_url.format(lesson_id=lesson.id)}';\"" in body
    assert f'href="/learner/learn/topics/{topic.id}/lessons"' in body
    assert 'class="progress-ticks"' in body
    assert "katex" in body


#: Per game page: its URL and markers its script depends on (ids, handlers, its completion call).
GAME_MARKERS = {
    "quiz": ("/learner/learn/questions/{lesson_id}", [
        'id="progressCondenseSentinel"', 'id="progressTicks"', 'id="submitButton"',
        'onclick="submitAnswer()"', 'onclick="nextQuestion()"', 'id="openResponseInput"',
        'onclick="location.reload()"', "GameKit.init({ lessonId, game: 'quiz' })", "const MCOptions",
    ]),
    "rocket": ("/learner/learn/rocket/{lesson_id}", [
        'id="rkScene"', 'id="rkWorld"', 'id="rkRocket"', 'id="answerGrid"', 'id="speakerBtn"',
        'id="tryAgain"', "GameKit.init({ lessonId, game: 'rocket' })",
    ]),
    "word_storm": ("/learner/learn/word-storm/{lesson_id}", [
        'id="wsStage"', 'id="lanternLayer"', 'id="skyChart"', 'id="speakerBtn"', 'id="tryAgain"',
        'id="burstCanvas"', "GameKit.init({ lessonId, game: 'word_storm' })",
    ]),
    "match_up": ("/learner/learn/match-up/{lesson_id}", [
        'id="muScene"', 'id="muHero"', 'id="muLeft"', 'id="muRight"', 'id="speakerBtn"',
        'id="tryAgain"', "GameKit.init({ lessonId, game: 'match_up' })",
    ]),
    "garden_grow": ("/learner/learn/garden-grow/{lesson_id}", [
        'id="gardenScene"', 'id="plantBtn"', 'id="waterBtn"', 'id="speakerBtn"', 'id="tryAgain"',
        "const N_PLOTS = 8;", "GameKit.init({ lessonId, game: 'garden_grow' })",
    ]),
    "potion_workshop": ("/learner/learn/potion-workshop/{lesson_id}", [
        'id="bookScreen"', 'id="brewScreen"', 'id="stirBtn"', 'id="cauldronSvg"', 'id="collectionRow"',
        'id="tryAgain"', "GameKit.init({ lessonId, game: 'potion_workshop' })",
    ]),
}


@pytest.mark.parametrize("game_type", list(GAME_MARKERS))
def test_each_game_page_renders_its_game_and_one_of_each_overlay(
    client, db_session, authenticated_learner, game_type
):
    url, markers = GAME_MARKERS[game_type]
    _subject, _topic, lesson, _question = make_learning_content(
        db_session, game_type=None if game_type == "quiz" else game_type
    )

    body = assert_success(client.get(url.format(lesson_id=lesson.id))).get_data(as_text=True)

    assert [marker for marker in markers if marker not in body] == []
    assert body.count('id="levelUpModal"') == 1
    assert body.count('id="completionScreen"') == 1
    assert body.count("window.GameKit = ") == 1
    assert "gsap.min.js" in body
    assert re.search(r"<title>[^<]*" + re.escape(lesson.title), body)


def test_a_replayed_garden_shows_the_no_xp_notice(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="garden_grow")
    authenticated_learner.completed_lesson_ids = [lesson.id]
    db_session.commit()

    body = assert_success(client.get(f"/learner/learn/garden-grow/{lesson.id}")).get_data(as_text=True)

    assert "already completed this garden!" in body


def test_a_replayed_rocket_plays_straight_away_with_the_no_xp_notice(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="rocket")
    authenticated_learner.completed_lesson_ids = [lesson.id]
    db_session.commit()

    body = assert_success(client.get(f"/learner/learn/rocket/{lesson.id}")).get_data(as_text=True)

    assert "already completed this rocket game!" in body
    assert 'id="answerGrid"' in body


def test_rocket_is_calm_no_fuel_to_lose(client, db_session, authenticated_learner):
    # Calm pattern (designing-for-learners.md): a wrong answer makes the rocket sputter and wait.
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="rocket")

    body = assert_success(client.get(f"/learner/learn/rocket/{lesson.id}")).get_data(as_text=True)

    assert "fuel" not in body.lower()


def test_word_storm_is_calm_no_hearts_countdown_or_game_over(client, db_session, authenticated_learner):
    # Calm pattern (designing-for-learners.md): a wrong lantern dims and drifts back, nothing is lost.
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="word_storm")

    body = assert_success(client.get(f"/learner/learn/word-storm/{lesson.id}")).get_data(as_text=True)

    assert [m for m in ("heart", "countdown", "gameOver", "restartGame", "Storm Failed") if m in body] == []


def test_a_replayed_word_storm_shows_the_no_xp_notice_and_plays_on(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="word_storm")
    authenticated_learner.completed_lesson_ids = [lesson.id]
    db_session.commit()

    body = assert_success(client.get(f"/learner/learn/word-storm/{lesson.id}")).get_data(as_text=True)

    assert "You can replay without earning more XP." in body
    assert 'id="lanternLayer"' in body


def test_match_up_is_calm_no_hearts_or_game_over(client, db_session, authenticated_learner):
    # Calm pattern (designing-for-learners.md): a wrong pair bounces apart, nothing is lost.
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="match_up")

    body = assert_success(client.get(f"/learner/learn/match-up/{lesson.id}")).get_data(as_text=True)

    assert [m for m in ("heart", "gameOver", "restartGame", "Match Failed") if m in body] == []


def test_a_replayed_match_up_shows_the_no_xp_notice_and_plays_on(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="match_up")
    authenticated_learner.completed_lesson_ids = [lesson.id]
    db_session.commit()

    body = assert_success(client.get(f"/learner/learn/match-up/{lesson.id}")).get_data(as_text=True)

    assert "already completed this match up!" in body
    assert 'id="muLeft"' in body
    assert "startReplay" not in body


# ── games ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("game_type,url", GAME_PAGES)
def test_a_game_page_renders_for_its_own_lesson(client, db_session, authenticated_learner, game_type, url):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type=game_type)

    assert_success(client.get(url.format(lesson_id=lesson.id)))


@pytest.mark.parametrize("game_type,url", GAME_PAGES)
def test_a_game_page_redirects_when_the_lesson_is_a_plain_quiz(
    client, db_session, authenticated_learner, game_type, url
):
    """Opening the rocket page for a non-rocket lesson falls back to the quiz."""

    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type=None)

    assert_redirects_to(
        client.get(url.format(lesson_id=lesson.id)),
        f"/learner/learn/questions/{lesson.id}",
    )


@pytest.mark.parametrize("game_type,url", GAME_PAGES)
def test_an_unknown_game_lesson_is_a_404(client, db_session, authenticated_learner, game_type, url):
    assert client.get(url.format(lesson_id=999999)).status_code == 404


# ── worksheets ───────────────────────────────────────────────────────────────


@pytest.fixture
def assignment(db_session, authenticated_learner):
    teacher = make_teacher(db_session, authenticated_learner.school)
    authenticated_learner.teacher_id = teacher.id
    worksheet = make_worksheet(db_session, title="Homework")
    db_session.commit()
    return make_worksheet_assignment(db_session, teacher, authenticated_learner, worksheet)


def test_an_assigned_worksheet_renders(client, db_session, assignment):
    body = assert_success(
        client.get(f"/learner/worksheets/{assignment.id}")
    ).get_data(as_text=True)

    assert "Homework" in body


def test_an_open_worksheet_offers_mark_done_and_the_way_back(client, db_session, assignment):
    body = assert_success(client.get(f"/learner/worksheets/{assignment.id}")).get_data(as_text=True)

    for marker in [
        "Back to Dashboard", 'href="/learner/"', "Mark as Done",
        f'action="/learner/worksheets/{assignment.id}/complete"', 'type="submit"',
    ]:
        assert marker in body


def test_a_pdf_worksheet_links_its_file(client, db_session, assignment):
    assignment.worksheet.file_type = "pdf"
    db_session.commit()

    body = assert_success(client.get(f"/learner/worksheets/{assignment.id}")).get_data(as_text=True)

    assert "Open PDF" in body
    assert f'href="/learner/worksheets/{assignment.id}/file"' in body


def test_a_done_worksheet_shows_completed_instead_of_the_button(client, db_session, assignment):
    assignment.completed = True
    db_session.commit()

    body = assert_success(client.get(f"/learner/worksheets/{assignment.id}")).get_data(as_text=True)

    assert "Completed" in body
    assert "Mark as Done" not in body


def test_the_dashboard_lists_an_open_worksheet_with_mark_done_and_view(client, db_session, assignment):
    body = assert_success(client.get("/learner/")).get_data(as_text=True)

    assert "Assigned Worksheets" in body
    assert "Homework" in body
    assert f'id="assignment-status-{assignment.id}"' in body
    assert f"onclick=\"markWorksheetDone({assignment.id}, this)\"" in body
    assert f'href="/learner/worksheets/{assignment.id}"' in body


def test_another_learners_worksheet_is_refused(client, db_session, assignment, school):
    other_teacher = make_teacher(db_session, school)
    other_learner = make_learner(db_session, school, other_teacher)
    worksheet = make_worksheet(db_session)
    theirs = make_worksheet_assignment(db_session, other_teacher, other_learner, worksheet)

    assert_denied(client.get(f"/learner/worksheets/{theirs.id}"))


def test_an_unknown_assignment_is_refused(client, db_session, authenticated_learner):
    assert_denied(client.get("/learner/worksheets/999999"))


def test_a_learner_can_mark_their_worksheet_done(client, db_session, assignment):
    from models import WorksheetAssignment

    client.post(f"/learner/worksheets/{assignment.id}/complete")

    db_session.expire_all()
    assert db_session.get(WorksheetAssignment, assignment.id).completed is True


def test_completing_a_worksheet_can_answer_json(client, db_session, assignment):
    response = assert_success(
        client.post(f"/learner/worksheets/{assignment.id}/complete", headers=AJAX)
    )

    assert response.get_json()["success"] is True


def test_a_learner_cannot_complete_someone_elses_worksheet(client, db_session, assignment, school):
    from models import WorksheetAssignment

    other_teacher = make_teacher(db_session, school)
    other_learner = make_learner(db_session, school, other_teacher)
    worksheet = make_worksheet(db_session)
    theirs = make_worksheet_assignment(db_session, other_teacher, other_learner, worksheet)

    assert_denied(client.post(f"/learner/worksheets/{theirs.id}/complete"))
    db_session.expire_all()
    assert db_session.get(WorksheetAssignment, theirs.id).completed is False


def test_a_markdown_worksheet_has_no_downloadable_file(client, db_session, assignment):
    """Only PDF-backed worksheets serve a file."""

    assert client.get(f"/learner/worksheets/{assignment.id}/file").status_code == 404


def test_a_pdf_worksheet_with_no_stored_path_is_a_404(client, db_session, assignment):
    assignment.worksheet.file_type = "pdf"
    assignment.worksheet.filepath = None
    db_session.commit()

    assert client.get(f"/learner/worksheets/{assignment.id}/file").status_code == 404


# ── assets ───────────────────────────────────────────────────────────────────


def test_word_storm_lantern_art_is_served_as_a_static_svg(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="word_storm")
    body = assert_success(client.get(f"/learner/learn/word-storm/{lesson.id}")).get_data(as_text=True)
    sprites = set(re.findall(r'(/static/svg/games/word_storm/[\w.-]+\.svg)', body))

    assert "/static/svg/games/word_storm/lanterns.svg" in sprites
    for sprite in sprites:
        assert assert_success(client.get(sprite)).mimetype == "image/svg+xml"


def test_the_face_builder_parts_are_served_as_static_svgs(client, db_session, authenticated_learner):
    body = assert_success(client.get("/learner/")).get_data(as_text=True)
    parts = set(re.findall(r'(/static/svg/avatar/[\w.-]+\.svg)', body))

    assert {"/static/svg/avatar/face_species_cat.svg", "/static/svg/avatar/avatar_top_hoodie.svg"} <= parts
    for part in parts:
        assert assert_success(client.get(part)).mimetype == "image/svg+xml"



def test_a_learner_at_the_top_level_is_not_offered_a_level_beyond_it(client, db_session, authenticated_learner):
    authenticated_learner.xp = 9000
    db_session.commit()

    import html

    body = html.unescape(assert_success(client.get("/learner/")).get_data(as_text=True))

    assert "Legend" in body
    assert "level 8" not in body.lower()
    assert "You've reached the top level!" in body

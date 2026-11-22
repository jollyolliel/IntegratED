"""The lesson run API (routes/api/lessons.py) for the quiz and every game: questions, grading
one answer or Match Up pair, and completion."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.support.assertions import assert_success
from tests.support.factories import (
    make_learning_content,
    make_lesson,
    make_question,
    make_subject,
    make_topic,
)

pytestmark = pytest.mark.web

#: Every game finishes through the one lesson completion route.
GAMES = [
    (game_type, "/api/lesson/{lesson_id}/completion")
    for game_type in ("rocket", "word_storm", "match_up", "garden_grow", "potion_workshop")
]


# ── game completions ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("game_type,url", GAMES)
def test_game_completion_awards_xp_and_persists_a_learning_session(
    client, db_session, authenticated_learner, game_type, url
):
    from models import LearningSession

    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type=game_type)

    response = assert_success(
        client.post(url.format(lesson_id=lesson.id), json={"correct_count": 1})
    )

    assert response.get_json()
    db_session.expire_all()
    assert authenticated_learner.xp > 0
    assert db_session.scalar(select(func.count()).select_from(LearningSession).filter_by(
        learner_id=authenticated_learner.id, session_type=game_type
    )) == 1


@pytest.mark.parametrize("game_type,url", GAMES)
def test_a_game_completion_for_an_unknown_lesson_is_a_404(
    client, db_session, authenticated_learner, game_type, url
):
    response = client.post(url.format(lesson_id=999999), json={"correct_count": 1})

    assert response.status_code == 404


def _match_lesson(db_session, words=("cat", "dog", "sun", "map")):
    lesson, _questions = _quiz_of(db_session)
    lesson.game_type = "match_up"
    topic = lesson.topic
    question = make_question(
        db_session, topic.subject, topic, lesson, content_type="match", options=None,
        match_pairs=[{"left": w, "right": w.upper()} for w in words],
    )
    return lesson, question


def _pair(client, lesson, left, right):
    return client.post(f"/api/match-up/{lesson.id}/pair", json={"left": left, "right": right})


def test_match_up_scores_every_pair_not_just_the_one_question(client, db_session, authenticated_learner):
    lesson, _question = _match_lesson(db_session)
    for word in ("cat", "dog", "sun", "map"):
        assert _pair(client, lesson, word, word.upper()).get_json() == {"is_correct": True}

    payload = assert_success(
        client.post(f"/api/lesson/{lesson.id}/completion", json={"correct_count": 4, "total_count": 4})
    ).get_json()

    assert payload["xp_earned"] == 4 * 10 + 50


def test_match_up_checks_each_pair_on_the_server(client, db_session, authenticated_learner):
    lesson, _question = _match_lesson(db_session)

    assert _pair(client, lesson, "cat", "DOG").get_json() == {"is_correct": False}
    assert _pair(client, lesson, "cat", "CAT").get_json() == {"is_correct": True}
    assert _pair(client, lesson, "dog", "DOG").get_json() == {"is_correct": True}
    payload = assert_success(client.post(f"/api/lesson/{lesson.id}/completion", json={"correct_count": 4})).get_json()

    # cat missed first time, dog matched first time; the claimed 4 counts for nothing.
    assert payload["xp_earned"] == 1 * 10 + 50


@pytest.mark.parametrize("body", [{}, {"left": "cat"}, {"left": ["cat"], "right": "CAT"}])
def test_a_malformed_pair_is_refused(client, db_session, authenticated_learner, body):
    lesson, _question = _match_lesson(db_session)

    assert client.post(f"/api/match-up/{lesson.id}/pair", json=body).status_code == 400


def test_a_pair_for_a_lesson_that_is_not_match_up_is_refused(client, db_session, authenticated_learner):
    lesson, _questions = _quiz_of(db_session, "multiple_choice")

    assert _pair(client, lesson, "cat", "CAT").status_code == 400
    assert client.post("/api/match-up/999999/pair", json={"left": "a", "right": "b"}).status_code == 404


def test_the_questions_api_does_not_hand_out_answers(client, db_session, authenticated_learner):
    lesson, _questions = _quiz_of(db_session, "multiple_choice", "text_comprehension_fill_blank")
    match_lesson, _match = _match_lesson(db_session)

    questions = assert_success(client.get(f"/api/quiz/{lesson.id}/questions")).get_json()["questions"]
    match = assert_success(client.get(f"/api/quiz/{match_lesson.id}/questions")).get_json()["questions"][0]

    for question in [*questions, match]:
        assert "answer" not in question
        assert "fill_blank_options" not in question
        assert "match_pairs" not in question
    assert match["match_left"] == ["cat", "dog", "sun", "map"]
    assert sorted(match["match_right"]) == ["CAT", "DOG", "MAP", "SUN"]


def test_a_hint_arrives_after_the_third_wrong_try(client, db_session, authenticated_learner):
    lesson, (question,) = _quiz_of(db_session, "text_comprehension_fill_blank")
    question.answer, question.fill_blank_options = None, ["is", "are"]
    db_session.commit()
    body = {"lesson_id": lesson.id, "question_id": question.id, "user_answer": "was"}

    replies = [client.post("/api/quiz/validate-answer", json=body).get_json() for _ in range(3)]

    assert [reply.get("hint") for reply in replies] == [None, None, "is"]


def test_a_multiple_choice_question_never_hints(client, db_session, authenticated_learner):
    lesson, (question,) = _quiz_of(db_session, "multiple_choice")
    body = {"lesson_id": lesson.id, "question_id": question.id, "user_answer": "no"}

    replies = [client.post("/api/quiz/validate-answer", json=body).get_json() for _ in range(4)]

    assert all("hint" not in reply for reply in replies)


@pytest.mark.parametrize("game_type,url", GAMES)
def test_a_game_scores_the_answers_the_server_checked(client, db_session, authenticated_learner, game_type, url):
    if game_type == "match_up":
        pytest.skip("Match Up scores pairs — test_match_up_checks_each_pair_on_the_server")
    lesson, (first, second) = _quiz_of(db_session, "multiple_choice", "multiple_choice")
    lesson.game_type = game_type
    db_session.commit()
    _answer(client, lesson, first, user_answer="no")
    _answer(client, lesson, first)
    _answer(client, lesson, second)

    payload = assert_success(client.post(url.format(lesson_id=lesson.id), json={"correct_count": 99})).get_json()

    assert payload["xp_earned"] == 1 * 10 + 50


@pytest.mark.parametrize("game_type,url", GAMES)
def test_only_a_learner_may_complete_a_game(client, db_session, authenticated_teacher, game_type, url):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type=game_type)

    response = client.post(url.format(lesson_id=lesson.id), json={"correct_count": 1})

    assert response.status_code == 403


def test_a_claimed_score_is_clamped_to_the_real_question_count(
    client, db_session, authenticated_learner
):
    """Anti-cheat: the client may not claim more correct answers than exist."""

    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="rocket")

    client.post(
        f"/api/lesson/{lesson.id}/completion", json={"correct_count": 1}
    ).get_json()
    db_session.expire_all()
    after_honest = authenticated_learner.xp

    client.post(
        f"/api/lesson/{lesson.id}/completion", json={"correct_count": 9_999}
    ).get_json()
    db_session.expire_all()
    gained_from_inflated = authenticated_learner.xp - after_honest

    assert gained_from_inflated <= after_honest


def test_garden_grow_grains_are_capped_by_the_correct_count(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="garden_grow")

    assert_success(
        client.post(
            f"/api/lesson/{lesson.id}/completion",
            json={"correct_count": 1, "grains": 10_000},
        )
    )

    # One correct answer buys at most GARDEN_PLOTS grains at 10 XP each.
    db_session.expire_all()
    assert authenticated_learner.xp <= 1_000


def test_potion_golden_count_is_capped_by_the_recipe_size(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="potion_workshop")

    assert_success(
        client.post(
            f"/api/lesson/{lesson.id}/completion",
            json={"correct_count": 1, "golden_count": 500},
        )
    )

    db_session.expire_all()
    assert authenticated_learner.xp <= 1_000


def test_word_storm_accepts_remaining_hearts(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type="word_storm")

    response = assert_success(
        client.post(
            f"/api/lesson/{lesson.id}/completion",
            json={"correct_count": 1, "hearts_remaining": 3},
        )
    )

    assert response.get_json()


@pytest.mark.parametrize("game_type,url", GAMES)
def test_a_non_numeric_game_score_is_not_a_server_error(
    client, db_session, authenticated_learner, game_type, url
):
    _subject, _topic, lesson, _question = make_learning_content(db_session, game_type=game_type)

    response = client.post(
        url.format(lesson_id=lesson.id),
        json={"correct_count": "abc", "grains": "x", "golden_count": [], "hearts_remaining": None},
    )

    assert response.status_code == 200


# ── quiz ─────────────────────────────────────────────────────────────────────


def test_lesson_questions_are_returned_for_a_learner(client, db_session, authenticated_learner):
    _subject, _topic, lesson, question = make_learning_content(db_session)

    payload = assert_success(client.get(f"/api/quiz/{lesson.id}/questions")).get_json()

    assert [q["id"] for q in payload["questions"]] == [question.id]
    assert payload["progress"]["correct_ids"] == []


def test_a_quiz_question_with_sound_points_at_its_audio(client, db_session, authenticated_learner):
    from helpers import audio_cache

    _subject, _topic, lesson, question = make_learning_content(db_session)
    question.question_sound = True
    db_session.commit()

    payload = assert_success(client.get(f"/api/quiz/{lesson.id}/questions")).get_json()

    assert payload["questions"][0]["question_sound_url"] == audio_cache.audio_url(question.question_text)


def test_a_quiz_question_without_sound_has_no_audio_url(client, db_session, authenticated_learner):
    _subject, _topic, lesson, _question = make_learning_content(db_session)

    payload = assert_success(client.get(f"/api/quiz/{lesson.id}/questions")).get_json()

    assert payload["questions"][0]["question_sound_url"] is None


def _quiz_of(db_session, *content_types):
    """A lesson whose questions have these content types, in this order."""
    subject = make_subject(db_session)
    topic = make_topic(db_session, subject)
    lesson = make_lesson(db_session, topic)
    questions = [make_question(db_session, subject, topic, lesson, content_type=ct) for ct in content_types]
    return lesson, questions


def _answer(client, lesson, question, user_answer="yes"):
    assert_success(
        client.post(
            "/api/quiz/validate-answer",
            json={"question_id": question.id, "user_answer": user_answer, "lesson_id": lesson.id},
        )
    )


def _resume_index(client, lesson):
    return assert_success(client.get(f"/api/quiz/{lesson.id}/questions")).get_json()["progress"]["resume_index"]


def test_a_fresh_quiz_resumes_at_the_first_question(client, db_session, authenticated_learner):
    lesson, _questions = _quiz_of(db_session, "multiple_choice", "multiple_choice")

    assert _resume_index(client, lesson) == 0


def test_a_quiz_resumes_after_the_questions_already_answered(client, db_session, authenticated_learner):
    lesson, (first, _second) = _quiz_of(db_session, "multiple_choice", "multiple_choice")
    _answer(client, lesson, first)

    assert _resume_index(client, lesson) == 1


def test_listening_to_an_opening_audio_question_does_not_skip_it_on_reopening(
    client, db_session, authenticated_learner
):
    lesson, (audio, _question) = _quiz_of(db_session, "vocabulary_audio", "multiple_choice")
    _answer(client, lesson, audio, "listened")

    assert _resume_index(client, lesson) == 0


def test_an_audio_question_the_quiz_resumes_at_is_not_shown_as_done(client, db_session, authenticated_learner):
    lesson, (audio, _question) = _quiz_of(db_session, "vocabulary_audio", "multiple_choice")
    _answer(client, lesson, audio, "listened")

    progress = assert_success(client.get(f"/api/quiz/{lesson.id}/questions")).get_json()["progress"]

    assert progress["correct_ids"] == []


def test_answered_questions_before_the_resume_point_stay_done(client, db_session, authenticated_learner):
    lesson, (first, audio, _third) = _quiz_of(db_session, "multiple_choice", "vocabulary_audio", "multiple_choice")
    _answer(client, lesson, first)
    _answer(client, lesson, audio, "listened")

    progress = assert_success(client.get(f"/api/quiz/{lesson.id}/questions")).get_json()["progress"]

    assert progress["correct_ids"] == [first.id]


def test_a_quiz_resumes_at_the_audio_question_leading_into_the_next_unanswered_one(
    client, db_session, authenticated_learner
):
    lesson, (first, audio, _third) = _quiz_of(db_session, "multiple_choice", "vocabulary_audio", "multiple_choice")
    _answer(client, lesson, first)
    _answer(client, lesson, audio, "listened")

    assert _resume_index(client, lesson) == 1


def test_questions_for_an_unknown_lesson_are_a_404(client, db_session, authenticated_learner):
    assert client.get("/api/quiz/999999/questions").status_code == 404


def test_completing_a_quiz_records_the_lesson(client, db_session, authenticated_learner):
    _subject, _topic, lesson, question = make_learning_content(db_session)
    _answer(client, lesson, question)

    assert_success(client.post(f"/api/lesson/{lesson.id}/completion", json={"correct_count": 1}))

    db_session.expire_all()
    assert lesson.id in (authenticated_learner.completed_lesson_ids or [])


def test_finishing_a_topics_last_lesson_by_quiz_marks_the_topic_complete(client, db_session, authenticated_learner):
    _subject, topic, lesson, question = make_learning_content(db_session)
    _answer(client, lesson, question)

    payload = assert_success(client.post(f"/api/lesson/{lesson.id}/completion", json={})).get_json()

    db_session.expire_all()
    assert authenticated_learner.completed_topic_ids == [topic.id]
    assert payload["xp_earned"] == 50
    assert payload["is_last"] is True


def test_a_quiz_leaves_the_topic_open_while_other_lessons_remain(client, db_session, authenticated_learner):
    _subject, topic, lesson, question = make_learning_content(db_session)
    later = make_lesson(db_session, topic, title="Still To Do")
    db_session.commit()
    _answer(client, lesson, question)

    payload = assert_success(client.post(f"/api/lesson/{lesson.id}/completion", json={})).get_json()

    db_session.expire_all()
    assert not authenticated_learner.completed_topic_ids
    assert payload["next_lesson"] == {"id": later.id, "title": "Still To Do"}


def test_a_quiz_replay_awards_no_xp(client, db_session, authenticated_learner):
    _subject, _topic, lesson, question = make_learning_content(db_session)
    url = f"/api/lesson/{lesson.id}/completion"

    _answer(client, lesson, question)
    first = assert_success(client.post(url, json={})).get_json()
    _answer(client, lesson, question)
    replay = assert_success(client.post(url, json={})).get_json()

    assert (first["xp_earned"], replay["xp_earned"]) == (50, 0)


def test_a_quiz_completion_reports_the_level_up_it_caused(client, db_session, authenticated_learner):
    _subject, _topic, lesson, question = make_learning_content(db_session)
    authenticated_learner.xp = 480
    db_session.commit()
    _answer(client, lesson, question)

    payload = assert_success(client.post(f"/api/lesson/{lesson.id}/completion", json={})).get_json()

    assert (payload["leveled_up"], payload["new_level"], payload["level_name"]) == (True, 2, "Explorer")


def test_a_quiz_completion_reports_every_field_a_game_completion_does(client, db_session, authenticated_learner):
    _subject, _topic, quiz_lesson, quiz_question = make_learning_content(db_session)
    _subject, _topic, game_lesson, _question = make_learning_content(db_session, game_type="rocket")
    _answer(client, quiz_lesson, quiz_question)

    quiz = assert_success(client.post(f"/api/lesson/{quiz_lesson.id}/completion", json={})).get_json()
    game = assert_success(
        client.post(f"/api/lesson/{game_lesson.id}/completion", json={"correct_count": 1, "total_count": 1})
    ).get_json()

    assert set(game) <= set(quiz)


def test_completing_an_unknown_lesson_is_a_404(client, db_session, authenticated_learner):
    assert client.post("/api/quiz/999999/completion", json={}).status_code == 404


def test_a_quiz_cannot_be_completed_before_its_questions_are_answered(client, db_session, authenticated_learner):
    lesson, (first, _second) = _quiz_of(db_session, "multiple_choice", "multiple_choice")
    _answer(client, lesson, first)

    response = client.post(f"/api/lesson/{lesson.id}/completion", json={})

    assert response.status_code == 400
    db_session.expire_all()
    assert (authenticated_learner.xp or 0) == 0
    assert lesson.id not in (authenticated_learner.completed_lesson_ids or [])


def test_a_wrong_answer_does_not_count_toward_finishing_a_quiz(client, db_session, authenticated_learner):
    lesson, (question,) = _quiz_of(db_session, "multiple_choice")
    _answer(client, lesson, question, user_answer="no")

    assert client.post(f"/api/lesson/{lesson.id}/completion", json={}).status_code == 400


def test_an_answer_to_another_lessons_question_is_refused(client, db_session, authenticated_learner):
    from models import LearningSession

    lesson, _questions = _quiz_of(db_session, "multiple_choice")
    _other_lesson, (foreign,) = _quiz_of(db_session, "multiple_choice")

    response = client.post(
        "/api/quiz/validate-answer",
        json={"question_id": foreign.id, "user_answer": "yes", "lesson_id": lesson.id},
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(LearningSession)) == 0


def test_a_correct_answer_is_validated(client, db_session, authenticated_learner):
    _subject, _topic, lesson, question = make_learning_content(db_session)

    payload = assert_success(
        client.post(
            "/api/quiz/validate-answer",
            json={"question_id": question.id, "user_answer": "yes", "lesson_id": lesson.id},
        )
    ).get_json()

    assert payload["is_correct"] is True


def test_a_wrong_answer_is_validated(client, db_session, authenticated_learner):
    _subject, _topic, lesson, question = make_learning_content(db_session)

    payload = assert_success(
        client.post(
            "/api/quiz/validate-answer",
            json={"question_id": question.id, "user_answer": "no", "lesson_id": lesson.id},
        )
    ).get_json()

    assert payload["is_correct"] is False


def test_validating_an_unknown_question_is_refused(client, db_session, authenticated_learner):
    response = client.post(
        "/api/quiz/validate-answer", json={"question_id": 999999, "user_answer": "yes", "lesson_id": 1}
    )

    assert response.status_code in {400, 404}

import pytest
from sqlalchemy import select

from models import LearningSession
from tests.support.auth import login_as
from tests.support.factories import make_learner, make_learning_content

pytestmark = pytest.mark.web


@pytest.fixture(params=["rocket", "word_storm", "match_up"])
def game_setup(request, db_session, school, teacher):
    _, _, lesson, question = make_learning_content(db_session, game_type=request.param)
    if request.param == "match_up":
        # Match Up scores pairs, so its one question is a one-pair match.
        question.content_type, question.options = "match", None
        question.match_pairs = [{"left": "cat", "right": "CAT"}]
    learner = make_learner(db_session, school, teacher, username=f"{request.param}-learner")
    db_session.commit()
    return request.param, lesson, learner


def completion_url(game_type, lesson_id):
    return f"/api/lesson/{lesson_id}/completion"


def answer_right(client, game_type, lesson):
    """Get the lesson's one question right first time, through the API that checks it."""
    if game_type == "match_up":
        reply = client.post(f"/api/match-up/{lesson.id}/pair", json={"left": "cat", "right": "CAT"})
    else:
        question = lesson.questions[0]
        reply = client.post("/api/quiz/validate-answer",
                            json={"lesson_id": lesson.id, "question_id": question.id, "user_answer": "yes"})
    assert reply.get_json()["is_correct"] is True


def test_game_completion_awards_xp_and_persists_a_learning_session(
    client, db_session, game_setup
):
    game_type, lesson, learner = game_setup
    login_as(client, learner)
    answer_right(client, game_type, lesson)

    response = client.post(
        completion_url(game_type, lesson.id),
        json={"correct_count": 1, "total_count": 1},
    )

    assert response.status_code == 200
    assert response.json["xp_earned"] == 60
    assert db_session.scalars(select(LearningSession).filter_by(
        learner_id=learner.id, session_type=game_type, lesson_id=lesson.id
    )).one().correct_count == 1


def test_game_replay_does_not_award_xp_twice(client, db_session, game_setup):
    game_type, lesson, learner = game_setup
    login_as(client, learner)
    url = completion_url(game_type, lesson.id)
    answer_right(client, game_type, lesson)

    first = client.post(url, json={"correct_count": 1, "total_count": 1})
    replay = client.post(url, json={"correct_count": 1, "total_count": 1})

    assert first.json["xp_earned"] == 60
    assert replay.json["xp_earned"] == 0
    assert replay.json["already_completed"] is True


def test_game_completion_rejects_a_teacher(client, db_session, authenticated_teacher, game_setup):
    game_type, lesson, _ = game_setup

    response = client.post(completion_url(game_type, lesson.id), json={"correct_count": 1})

    assert response.status_code == 403


def test_finishing_a_topics_last_lesson_by_game_marks_the_topic_complete(client, db_session, game_setup):
    game_type, lesson, learner = game_setup
    login_as(client, learner)

    client.post(completion_url(game_type, lesson.id), json={"correct_count": 1, "total_count": 1})

    db_session.refresh(learner)
    assert learner.completed_topic_ids == [lesson.topic_id]


def test_a_game_leaves_the_topic_open_while_other_lessons_remain(client, db_session, game_setup):
    from tests.support.factories import make_lesson

    game_type, lesson, learner = game_setup
    make_lesson(db_session, lesson.topic, title="Still To Do")
    db_session.commit()
    login_as(client, learner)

    client.post(completion_url(game_type, lesson.id), json={"correct_count": 1, "total_count": 1})

    db_session.refresh(learner)
    assert not learner.completed_topic_ids

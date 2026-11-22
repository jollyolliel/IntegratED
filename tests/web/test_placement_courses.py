"""The placement test end to end over a course-banded scale, and where its recommendation shows."""

import pytest

from tests.support.factories import (
    make_learner,
    make_lesson,
    make_map_question,
    make_subject,
    make_topic,
)

pytestmark = pytest.mark.web


@pytest.fixture
def english(db_session):
    """A four-level English scale with plenty of questions, split over two courses."""
    scale = make_subject(db_session, name="English", map_test_only=True)
    for level in (1, 2, 3, 4):
        for n in range(12):
            make_map_question(db_session, scale, level=level, question_text=f"L{level} #{n}", persist=False)
    first = make_subject(db_session, name="English: First Steps", placement_scale_id=scale.id,
                         placement_min_level=1, placement_max_level=2)
    everyday = make_subject(db_session, name="English: Everyday", placement_scale_id=scale.id,
                            placement_min_level=3, placement_max_level=4)
    topics = {}
    for course, levels in ((first, (1, 2)), (everyday, (3, 4))):
        for level in levels:
            topic = make_topic(db_session, course, title=f"{course.name} topic {level}", level=level)
            make_lesson(db_session, topic, title=f"{topic.title} lesson")
            topics[level] = topic
    db_session.commit()
    return {"scale": scale, "first": first, "everyday": everyday, "topics": topics}


def _take_the_test(client, answer):
    """Answer every question with `answer`; return (questions asked, completion payload)."""
    payload = client.post("/api/map/question", json={}).get_json()
    asked = 0
    while not payload.get("completed"):
        asked += 1
        assert asked <= 25, "the placement test did not end"
        payload = client.post(
            "/api/map/question", json={"id": payload["id"], "selected_answer": answer}
        ).get_json()
    return asked, payload


def test_a_learner_who_gets_everything_wrong_answers_at_least_ten_and_lands_on_the_first_course(
    client, db_session, authenticated_learner, english
):
    asked, result = _take_the_test(client, "no")

    assert 10 <= asked <= 20
    assert result["recommended_start"]["subject"] == "English: First Steps"
    assert result["recommended_start"]["topic_id"] == english["topics"][1].id
    db_session.expire_all()
    assert authenticated_learner.subject_levels == {"English": 1}


def test_a_learner_who_gets_everything_right_lands_on_the_last_course_within_twenty(
    client, db_session, authenticated_learner, english
):
    asked, result = _take_the_test(client, "yes")

    assert 10 <= asked <= 20
    assert result["recommended_start"]["subject"] == "English: Everyday"
    assert result["recommended_start"]["topic_id"] == english["topics"][4].id
    assert result["recommended_start"]["topic_url"].endswith(f"/learn/topics/{english['topics'][4].id}/lessons")


def test_the_completed_event_records_the_recommended_course_and_the_question_count(
    client, db_session, authenticated_learner, english, monkeypatch
):
    from routes.api import map_test

    events = []
    monkeypatch.setattr(map_test, "capture_event", lambda user, name, props=None: events.append((name, props)))

    asked, _result = _take_the_test(client, "no")

    completed = next(props for name, props in events if name == "map_completed")
    assert completed["recommended_course_id"] == english["first"].id
    assert completed["recommended_course"] == "English: First Steps"
    assert completed["placement_scale"] == "English"
    assert completed["question_count"] == asked


def test_a_reload_mid_test_resumes_rather_than_restarting(client, db_session, authenticated_learner, english):
    from sqlalchemy import select

    from models import LearningSession

    first = client.post("/api/map/question", json={}).get_json()
    client.post("/api/map/question", json={"id": first["id"], "selected_answer": "no"})
    client.post("/api/map/question", json={})  # a reload: no answer attached

    session_row = db_session.scalar(select(LearningSession).filter_by(
        learner_id=authenticated_learner.id, session_type="placement"))
    assert session_row is not None and session_row.count == 1


def test_the_dashboard_names_the_recommended_course(client, db_session, english):
    from tests.support.auth import login_as

    learner = make_learner(db_session, subject_levels={"English": 3})
    login_as(client, learner)

    from tests.support.html import parse

    topic = english["topics"][3]
    page = parse(client.get("/learner/").get_data(as_text=True))

    card = next(a for a in page.find_all("a") if a.attrs.get("href") == f"/learner/learn/topics/{topic.id}/lessons")
    assert topic.title in card.all_text
    assert "English: Everyday" in card.all_text
    assert f"course_id: {english['everyday'].id}" in str(card.attrs.get("onclick"))


def test_the_course_list_marks_the_recommended_course(client, db_session, english):
    from tests.support.auth import login_as
    from tests.support.html import parse

    learner = make_learner(db_session, subject_levels={"English": 1})
    login_as(client, learner)

    page = parse(client.get("/learner/learn/subjects").get_data(as_text=True))

    recommended = page.find_all("a", "subject-card-recommended")
    assert len(recommended) == 1
    assert "English: First Steps" in recommended[0].all_text
    assert "map_recommendation_clicked" in str(recommended[0].attrs.get("onclick"))
    assert "English" not in [card.find("h3").all_text for card in page.find_all("a", "subject-card")]


def test_the_topic_list_of_the_recommended_course_marks_the_starting_topic(client, db_session, english):
    from tests.support.auth import login_as
    from tests.support.html import parse

    learner = make_learner(db_session, subject_levels={"English": 4})
    login_as(client, learner)

    page = parse(client.get(f"/learner/learn/subjects/{english['everyday'].id}/topics").get_data(as_text=True))
    other = parse(client.get(f"/learner/learn/subjects/{english['first'].id}/topics").get_data(as_text=True))

    card = page.find("a", "topic-card-recommended")
    assert english["topics"][4].title in card.all_text
    assert other.find_all(cls="topic-card-recommended") == []

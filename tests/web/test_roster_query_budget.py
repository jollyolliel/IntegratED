"""Teacher roster pages must not scale their query count with roster size.

Dev is SQLite on the same machine, where a stray query per person is invisible;
prod is Neon over the network, where it is a round trip each. These budgets are
deliberately loose — they catch a new N+1, not a query or two of drift.
"""

import pytest
from sqlalchemy import event

pytestmark = pytest.mark.web

N_VOLUNTEERS = 20
N_LEARNERS = 40


@pytest.fixture
def loaded_roster(db_session, school):
    from tests.support.factories import (
        make_learner,
        make_lesson,
        make_subject,
        make_teacher,
        make_topic,
        make_volunteer,
        make_worksheet,
    )

    teacher = make_teacher(db_session, school)
    subject = make_subject(db_session, name="English Grammar")
    topics = [make_topic(db_session, subject, title=f"Topic {i}", level=i) for i in range(1, 5)]
    for topic in topics:
        for j in range(4):
            make_lesson(db_session, topic, title=f"Lesson {topic.id}-{j}")
    for i in range(20):
        make_worksheet(db_session, title=f"Worksheet {i}", subject="English Grammar")

    volunteers = [
        make_volunteer(db_session, school, teacher, name=f"Vol {i}", match_capacity=3)
        for i in range(N_VOLUNTEERS)
    ]
    for i in range(N_LEARNERS):
        make_learner(
            db_session, school, teacher, name=f"Learner {i}",
            is_matched=True, volunteer_id=volunteers[i % N_VOLUNTEERS].id,
            completed_topic_ids=[topics[0].id], completed_lesson_ids=[1, 2, 3],
        )
    db_session.commit()
    return teacher


def _count_queries(client, url):
    from extensions import db

    seen = []

    @event.listens_for(db.engine, "before_cursor_execute")
    def before(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    try:
        response = client.get(url)
    finally:
        event.remove(db.engine, "before_cursor_execute", before)
    return response, len(seen)


@pytest.mark.parametrize("url, budget", [
    ("/teacher/people", 10),
    ("/teacher/", 20),
    ("/teacher/worksheets", 20),
])
def test_roster_pages_stay_within_their_query_budget(client, loaded_roster, url, budget):
    from tests.support.auth import login_as

    login_as(client, loaded_roster)
    client.get(url)  # warm per-process caches, which are not what is measured

    response, queries = _count_queries(client, url)

    assert response.status_code == 200
    assert queries <= budget, (
        f"{url} issued {queries} queries for {N_LEARNERS} learners and "
        f"{N_VOLUNTEERS} volunteers (budget {budget}) — likely a new N+1"
    )

import pytest

from tests.support.factories import make_learner, make_volunteer

pytestmark = pytest.mark.web


@pytest.fixture
def capacity_group(db_session, school, teacher):
    learners = [
        make_learner(db_session, school, teacher, username=f"capacity-{index}")
        for index in range(2)
    ]
    volunteer = make_volunteer(
        db_session, school, teacher, email="capacity@example.com", match_capacity=2
    )
    db_session.commit()
    return learners, volunteer


def test_capacity_properties_report_open_slots_and_full_state(db_session, capacity_group):
    learners, volunteer = capacity_group

    assert volunteer.capacity == 2
    assert volunteer.open_slots == 2
    learners[0].volunteer_match = volunteer
    learners[0].is_matched = True
    volunteer.is_matched = True
    db_session.commit()

    assert volunteer.open_slots == 1
    assert volunteer.is_full is False


def test_teacher_can_set_a_valid_capacity(client, db_session, authenticated_teacher, capacity_group):
    _, volunteer = capacity_group

    response = client.post(f"/teacher/volunteers/{volunteer.id}/capacity", data={"capacity": 3})

    assert response.status_code in {200, 302, 303}
    db_session.refresh(volunteer)
    assert volunteer.capacity == 3


@pytest.mark.parametrize("value", [0, 99, "not-a-number"])
def test_teacher_cannot_set_capacity_outside_the_supported_range(
    client, db_session, authenticated_teacher, capacity_group, value
):
    _, volunteer = capacity_group

    response = client.post(f"/teacher/volunteers/{volunteer.id}/capacity", data={"capacity": value})

    assert response.status_code == 400


def test_manual_matching_respects_capacity(client, db_session, authenticated_teacher, capacity_group):
    learners, volunteer = capacity_group
    volunteer.match_capacity = 1
    db_session.commit()

    first = client.post(
        "/teacher/pairs/match",
        data={"learner_id": learners[0].id, "volunteer_id": volunteer.id},
    )
    second = client.post(
        "/teacher/pairs/match",
        data={"learner_id": learners[1].id, "volunteer_id": volunteer.id},
    )

    assert first.status_code in {200, 302, 303}
    assert second.status_code == 400

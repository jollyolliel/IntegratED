import pytest

from helpers.teacher_ops import (
    update_user_attendance,
    validate_update_user_attendance,
)
from tests.support.factories import make_attendance, make_learner

pytestmark = pytest.mark.unit


def test_updating_attendance_to_absent_zeroes_duration(db_session, school, teacher):
    learner = make_learner(db_session, school, teacher)
    record = make_attendance(db_session, teacher, learner, duration=2.0)

    result = update_user_attendance(teacher, record.id, is_present=False, notes="sick")

    assert result["record"].is_present is False
    assert result["record"].duration == 0.0
    assert result["record"].notes == "sick"


def test_present_attendance_rejects_zero_duration(db_session, school, teacher):
    learner = make_learner(db_session, school, teacher)
    record = make_attendance(db_session, teacher, learner, duration=1.0)

    with pytest.raises(ValueError, match="greater than zero"):
        validate_update_user_attendance(teacher, record.id, is_present=True, duration=0)


def test_teacher_cannot_update_another_teachers_attendance(db_session):
    from tests.support.factories import make_school, make_teacher

    first_school = make_school(db_session, name="First")
    second_school = make_school(db_session, name="Second")
    owner = make_teacher(db_session, first_school, email="owner@example.com")
    stranger = make_teacher(db_session, second_school, email="stranger@example.com")
    learner = make_learner(db_session, first_school, owner)
    record = make_attendance(db_session, owner, learner)

    with pytest.raises(PermissionError):
        validate_update_user_attendance(stranger, record.id, duration=2)

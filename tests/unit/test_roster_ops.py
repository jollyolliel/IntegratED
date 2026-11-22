"""The shared delete cascade, and announcement targeting.

Deleting a person is one invariant reached from three surfaces with three
different ownership checks, so it is tested once here rather than three times
through the routes.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from tests.support.factories import (
    make_admin,
    make_article,
    make_assistant_change,
    make_assistant_conversation,
    make_assistant_message,
    make_attendance,
    make_feature_announcement,
    make_learner,
    make_learning_session,
    make_school,
    make_teacher,
    make_volunteer,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def pair(db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    volunteer = make_volunteer(db_session, school, teacher)
    learner.volunteer_match = volunteer
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()
    return {"school": school, "teacher": teacher, "learner": learner, "volunteer": volunteer}


# ── deleting a learner ───────────────────────────────────────────────────────


def test_deleting_a_learner_removes_their_own_records(db_session, pair):
    from helpers import roster_ops
    from models import Attendance, LearningSession, WorksheetAssignment

    learner, teacher = pair["learner"], pair["teacher"]
    make_attendance(db_session, teacher, learner, duration=1.0)
    make_learning_session(db_session, learner, session_type="quiz")
    make_worksheet_assignment(db_session, teacher, learner, make_worksheet(db_session))
    learner_id = learner.id

    roster_ops.delete_user(learner)

    assert db_session.scalar(select(func.count()).select_from(Attendance).filter_by(user_id=learner_id)) == 0
    assert db_session.scalar(select(func.count()).select_from(LearningSession).filter_by(learner_id=learner_id)) == 0
    assert db_session.scalar(select(func.count()).select_from(WorksheetAssignment).filter_by(learner_id=learner_id)) == 0


def test_deleting_a_learner_keeps_the_partners_own_record(db_session, pair):
    """The volunteer's row survives with `partner_id` nulled, not orphaned."""

    from helpers import roster_ops
    from models import Attendance

    learner, volunteer, teacher = pair["learner"], pair["volunteer"], pair["teacher"]
    volunteer_row = make_attendance(
        db_session, teacher, volunteer, partner=learner, duration=1.0
    )

    roster_ops.delete_user(learner)

    surviving = db_session.get(Attendance, volunteer_row.id)
    assert surviving is not None
    assert surviving.partner_id is None


def test_deleting_a_learner_releases_their_volunteer(db_session, pair):
    from helpers import roster_ops

    volunteer = pair["volunteer"]

    roster_ops.delete_user(pair["learner"])

    db_session.refresh(volunteer)
    assert volunteer.is_matched is False


def test_deleting_a_learner_removes_the_row(db_session, pair):
    from helpers import roster_ops
    from models import Learner

    learner_id = pair["learner"].id

    roster_ops.delete_user(pair["learner"])

    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(id=learner_id)) == 0


# ── deleting a volunteer ─────────────────────────────────────────────────────


def test_deleting_a_volunteer_releases_their_learners(db_session, pair):
    from helpers import roster_ops

    learner = pair["learner"]

    roster_ops.delete_user(pair["volunteer"])

    db_session.refresh(learner)
    assert learner.volunteer_id is None
    assert learner.is_matched is False


def test_deleting_a_volunteer_keeps_the_learners_worksheet(db_session, pair):
    """Only the record of who handed it out is cleared."""

    from helpers import roster_ops
    from models import WorksheetAssignment

    assignment = make_worksheet_assignment(
        db_session,
        pair["teacher"],
        pair["learner"],
        make_worksheet(db_session),
        volunteer=pair["volunteer"],
    )

    roster_ops.delete_user(pair["volunteer"])

    surviving = db_session.get(WorksheetAssignment, assignment.id)
    assert surviving is not None
    assert surviving.volunteer_id is None


def test_deleting_a_volunteer_keeps_the_learners_attendance(db_session, pair):
    from helpers import roster_ops
    from models import Attendance

    learner_row = make_attendance(
        db_session, pair["teacher"], pair["learner"],
        partner=pair["volunteer"], duration=2.0,
    )

    roster_ops.delete_user(pair["volunteer"])

    surviving = db_session.get(Attendance, learner_row.id)
    assert surviving is not None
    assert surviving.partner_id is None
    assert surviving.duration == 2.0


def test_deleting_a_volunteer_removes_their_own_attendance(db_session, pair):
    from helpers import roster_ops
    from models import Attendance

    volunteer_id = pair["volunteer"].id
    make_attendance(db_session, pair["teacher"], pair["volunteer"], duration=1.0)

    roster_ops.delete_user(pair["volunteer"])

    assert db_session.scalar(select(func.count()).select_from(Attendance).filter_by(user_id=volunteer_id)) == 0


def test_deleting_a_volunteer_who_holds_several_learners_frees_them_all(db_session, pair):
    from helpers import roster_ops

    volunteer = pair["volunteer"]
    volunteer.match_capacity = 2
    second = make_learner(db_session, pair["school"], pair["teacher"])
    second.volunteer_match = volunteer
    second.volunteer_id = volunteer.id
    second.is_matched = True
    db_session.commit()

    roster_ops.delete_user(volunteer)

    db_session.refresh(second)
    assert second.volunteer_id is None


# ── deleting a teacher ───────────────────────────────────────────────────────


def test_deleting_a_teacher_unlinks_their_roster(db_session, pair):
    from helpers import roster_ops

    roster_ops.delete_user(pair["teacher"])

    db_session.refresh(pair["learner"])
    db_session.refresh(pair["volunteer"])
    assert pair["learner"].teacher_id is None
    assert pair["volunteer"].teacher_id is None


def test_deleting_a_teacher_keeps_the_hours_they_recorded(db_session, pair):
    from helpers import roster_ops
    from models import Attendance

    make_attendance(db_session, pair["teacher"], pair["volunteer"], partner=pair["learner"], duration=2.0)
    make_attendance(db_session, pair["teacher"], pair["learner"], partner=pair["volunteer"], duration=2.0)

    roster_ops.delete_user(pair["teacher"])

    rows = db_session.scalars(select(Attendance)).all()
    assert [row.teacher_id for row in rows] == [None, None]
    db_session.refresh(pair["volunteer"])
    assert pair["volunteer"].hours_volunteered == 2.0


def test_deleting_a_teacher_keeps_the_learners_worksheets(db_session, pair):
    from helpers import roster_ops
    from models import WorksheetAssignment

    make_worksheet_assignment(db_session, pair["teacher"], pair["learner"], make_worksheet(db_session))

    roster_ops.delete_user(pair["teacher"])

    assignment = db_session.scalars(select(WorksheetAssignment)).one()
    assert assignment.teacher_id is None
    assert assignment.learner_id == pair["learner"].id


def test_deleting_a_teacher_removes_their_assistant_history(db_session, pair):
    from helpers import roster_ops
    from models import AssistantChange, AssistantConversation, AssistantMessage

    conversation = make_assistant_conversation(db_session, pair["teacher"])
    make_assistant_message(db_session, conversation)
    make_assistant_change(db_session, pair["teacher"], conversation=conversation)

    roster_ops.delete_user(pair["teacher"])

    for model in (AssistantConversation, AssistantMessage, AssistantChange):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


# ── deleting an administrator ────────────────────────────────────────────────


def test_deleting_an_administrator_hands_their_articles_to_another(db_session):
    from helpers import roster_ops
    from models import Article

    leaving, staying = make_admin(db_session), make_admin(db_session)
    make_article(db_session, leaving)

    roster_ops.delete_user(leaving, heir=staying)

    assert db_session.scalars(select(Article)).one().author_id == staying.id


def test_an_administrator_with_no_heir_named_hands_articles_to_the_longest_serving_other(db_session):
    from helpers import roster_ops
    from models import Article

    first, second, leaving = make_admin(db_session), make_admin(db_session), make_admin(db_session)
    make_article(db_session, leaving)

    roster_ops.delete_user(leaving)

    assert db_session.scalars(select(Article)).one().author_id == first.id
    assert second.id != first.id


def test_the_last_administrator_cannot_be_deleted(db_session):
    from helpers import roster_ops
    from models import Administrator

    only = make_admin(db_session)

    with pytest.raises(roster_ops.LastAdministratorError):
        roster_ops.delete_user(only)
    assert db_session.get(Administrator, only.id) is not None


def test_deleting_a_school_admin_removes_only_their_row(db_session, school):
    from helpers import roster_ops
    from models import School, SchoolAdmin
    from tests.support.factories import make_school_admin

    admin = make_school_admin(db_session, school)
    admin_id = admin.id

    roster_ops.delete_user(admin)

    assert db_session.get(SchoolAdmin, admin_id) is None
    assert db_session.get(School, school.id) is not None


@pytest.mark.filterwarnings("ignore:Flushing object.*incompatible polymorphic identity")
def test_a_role_with_no_delete_cascade_is_refused(db_session):
    from helpers import roster_ops
    from models import User

    stray = User(user_type="stray")
    db_session.add(stray)
    db_session.commit()

    with pytest.raises(TypeError):
        roster_ops.delete_user(stray)
    assert db_session.get(User, stray.id) is not None


def test_a_failed_delete_changes_nothing(db_session, pair, monkeypatch):
    from extensions import db
    from helpers import roster_ops
    from models import Attendance, Learner

    learner, teacher = pair["learner"], pair["teacher"]
    make_attendance(db_session, teacher, learner, duration=1.0)
    learner_id = learner.id

    def explode(row):
        raise RuntimeError("delete failed")

    monkeypatch.setattr(db.session, "delete", explode)
    with pytest.raises(RuntimeError):
        roster_ops.delete_user(learner)
    monkeypatch.undo()

    db_session.expire_all()
    assert db_session.get(Learner, learner_id) is not None
    assert db_session.scalar(select(func.count()).select_from(Attendance).filter_by(user_id=learner_id)) == 1


# ── announcement targeting ───────────────────────────────────────────────────


def test_an_announcement_is_shown_to_its_target_role(db_session, pair):
    from helpers.announcements import get_pending_announcement

    announcement = make_feature_announcement(db_session, roles=["learner"])

    pending = get_pending_announcement(pair["learner"])
    assert pending is not None
    assert pending.id == announcement.id


def test_an_announcement_for_another_role_is_not_shown(db_session, pair):
    from helpers.announcements import get_pending_announcement

    make_feature_announcement(db_session, roles=["teacher"])

    assert get_pending_announcement(pair["learner"]) is None


def test_only_the_newest_announcement_is_offered(db_session, pair):
    """Dismissing sets a high-water mark, so older ones are never queued."""

    from helpers.announcements import get_pending_announcement

    make_feature_announcement(db_session, roles=["learner"], title="Old")
    newest = make_feature_announcement(db_session, roles=["learner"], title="New")

    pending = get_pending_announcement(pair["learner"])
    assert pending is not None
    assert pending.id == newest.id


def test_an_already_seen_announcement_is_not_repeated(db_session, pair):
    from helpers.announcements import get_pending_announcement

    announcement = make_feature_announcement(db_session, roles=["learner"])
    pair["learner"].last_seen_announcement_id = announcement.id
    db_session.commit()

    assert get_pending_announcement(pair["learner"]) is None


def test_an_anonymous_visitor_gets_no_announcement(db_session):
    from helpers.announcements import get_pending_announcement

    class _Anonymous:
        is_authenticated = False

    assert get_pending_announcement(_Anonymous()) is None
    assert get_pending_announcement(None) is None


def test_a_user_with_no_role_gets_no_announcement(db_session):
    from helpers.announcements import get_pending_announcement

    class _Odd:
        is_authenticated = True
        user_type = None

    assert get_pending_announcement(_Odd()) is None


# ── syncing from the source file ─────────────────────────────────────────────


def test_syncing_inserts_new_announcements(db_session, tmp_path):
    from helpers.announcements import sync_announcements
    from models import FeatureAnnouncement

    source = tmp_path / "announcements.json"
    source.write_text(
        json.dumps([{"uid": "first-thing", "title": "Hello", "roles": ["learner"]}]),
        encoding="utf-8",
    )

    inserted = sync_announcements(str(source))

    assert inserted == ["first-thing"]
    assert db_session.scalar(select(func.count()).select_from(FeatureAnnouncement).filter_by(uid="first-thing")) == 1


def test_syncing_twice_inserts_nothing_the_second_time(db_session, tmp_path):
    from helpers.announcements import sync_announcements
    from models import FeatureAnnouncement

    source = tmp_path / "announcements.json"
    source.write_text(json.dumps([{"uid": "once", "roles": ["learner"]}]), encoding="utf-8")

    sync_announcements(str(source))
    second = sync_announcements(str(source))

    assert second == []
    assert db_session.scalar(select(func.count()).select_from(FeatureAnnouncement).filter_by(uid="once")) == 1


def test_syncing_never_clobbers_an_edited_row(db_session, tmp_path):
    """The file is only ever the seed copy — insert-only, by design."""

    from helpers.announcements import sync_announcements
    from models import FeatureAnnouncement

    source = tmp_path / "announcements.json"
    source.write_text(json.dumps([{"uid": "keep", "title": "From file"}]), encoding="utf-8")
    sync_announcements(str(source))
    row = db_session.scalars(select(FeatureAnnouncement).filter_by(uid="keep")).one()
    row.content = {"title": "Edited in the admin"}
    db_session.commit()

    sync_announcements(str(source))

    db_session.expire_all()
    assert db_session.scalars(select(FeatureAnnouncement).filter_by(uid="keep")).one().content["title"] == (
        "Edited in the admin"
    )


def test_an_entry_without_a_uid_is_skipped(db_session, tmp_path):
    from helpers.announcements import sync_announcements
    from models import FeatureAnnouncement

    source = tmp_path / "announcements.json"
    source.write_text(json.dumps([{"title": "No uid"}]), encoding="utf-8")

    assert sync_announcements(str(source)) == []
    assert db_session.scalar(select(func.count()).select_from(FeatureAnnouncement)) == 0


def test_a_missing_source_file_is_not_an_error(db_session, tmp_path):
    from helpers.announcements import sync_announcements

    assert sync_announcements(str(tmp_path / "absent.json")) == []

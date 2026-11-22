"""Minimal explicit model factories used by web and integration tests."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

#: Per-test counters. The first record of a kind keeps the plain default name
#: ("learner", "teacher@example.com") so tests can log in with a literal; only
#: the second and later ones get a suffix, which is what keeps repeated calls
#: from colliding on the unique constraints. Reset between tests by the
#: ``clean_database`` fixture.
_counters: dict[str, int] = defaultdict(int)


def reset_sequences() -> None:
    _counters.clear()


def _nth(kind: str) -> int:
    _counters[kind] += 1
    return _counters[kind]


def _unique(kind: str, base: str, suffix: str = "") -> str:
    """``base`` for the first call, ``base-2``/``base-3`` after that."""

    n = _nth(kind)
    if n == 1:
        return f"{base}{suffix}"
    return f"{base}-{n}{suffix}"


def _save(session, value, persist):
    session.add(value)
    if persist:
        session.commit()
    else:
        session.flush()
    return value


def make_school(session, *, name=None, persist=True, **overrides):
    from models import School

    fields = {"name": name or _unique("school", "Test School")}
    fields.update(overrides)
    return _save(session, School(**fields), persist)


def make_subject(session, *, name=None, persist=True, **overrides):
    from models import Subject

    fields = {
        "name": name or _unique("subject", "English Grammar"),
        "icon": "fa-book",
        "description": "Test subject",
    }
    fields.update(overrides)
    return _save(session, Subject(**fields), persist)


def make_topic(session, subject, *, title="Test Topic", level=1, persist=True, **overrides):
    from models import Topic

    fields = {
        "subject_id": subject.id,
        "icon": "fa-star",
        "level": level,
        "description": "Test topic",
        "title": title,
        "overview_markdown": "# Topic",
    }
    fields.update(overrides)
    return _save(session, Topic(**fields), persist)


def make_lesson(session, topic, *, title="Test Lesson", game_type=None, persist=True, **overrides):
    from models import Lesson

    fields = {
        "topic_id": topic.id,
        "icon": "fa-book",
        "description": "Test lesson",
        "title": title,
        "overview_markdown": "Lesson overview",
        "game_type": game_type,
    }
    fields.update(overrides)
    return _save(session, Lesson(**fields), persist)


def make_teacher(session, school=None, *, email=None, name="Test Teacher", persist=True, **overrides):
    from models import Teacher

    email = email or _unique("teacher", "teacher", "@example.com")
    fields = {
        "email": email,
        "name": name,
        "google_sub": f"sub-{email}",
        "school_id": school.id if school else None,
        "user_type": "teacher",
    }
    fields.update(overrides)
    return _save(session, Teacher(**fields), persist)


def make_learner(session, school=None, teacher=None, *, username=None, password="Password1!", name="Test Learner", persist=True, **overrides):
    from models import Learner

    fields = {
        "username": username or _unique("learner", "learner"),
        "name": name,
        "school_id": school.id if school else None,
        "teacher_id": teacher.id if teacher else None,
        "completed_survey": True,
        "completed_map_test": True,
        "subject_levels": {"English Grammar": 1},
        "user_type": "learner",
    }
    fields.update(overrides)
    learner = Learner(**fields)
    learner.set_password(password)
    return _save(session, learner, persist)


def make_volunteer(session, school=None, teacher=None, *, email=None, name="Test Volunteer", persist=True, **overrides):
    from models import Volunteer

    email = email or _unique("volunteer", "volunteer", "@example.com")
    fields = {
        "email": email,
        "name": name,
        "google_sub": f"sub-{email}",
        "school_id": school.id if school else None,
        "teacher_id": teacher.id if teacher else None,
        "completed_survey": True,
        "user_type": "volunteer",
    }
    fields.update(overrides)
    return _save(session, Volunteer(**fields), persist)


def make_admin(session, *, username=None, password="Password1!", name="Test Admin", persist=True, **overrides):
    from models import Administrator

    fields = {
        "username": username or _unique("admin", "admin"),
        "name": name,
        "user_type": "administrator",
    }
    fields.update(overrides)
    admin = Administrator(**fields)
    admin.set_password(password)
    return _save(session, admin, persist)


def make_school_admin(session, school, *, username=None, password="Password1!", name="Test School Admin", persist=True, **overrides):
    from models import SchoolAdmin

    fields = {
        "username": username or _unique("school_admin", "schooladmin"),
        "name": name,
        "school_id": school.id,
        "user_type": "school_admin",
    }
    fields.update(overrides)
    school_admin = SchoolAdmin(**fields)
    school_admin.set_password(password)
    return _save(session, school_admin, persist)


def make_question(session, subject, topic, lesson, *, prompt="Choose", answer="yes", persist=True, **overrides):
    from models import Question

    fields = {
        "subject_id": subject.id,
        "topic_id": topic.id,
        "lesson_id": lesson.id,
        "content_type": "multiple_choice",
        "question_prompt": prompt,
        "question_text": "Test question",
        "options": ["yes", "no"],
        "answer": answer,
    }
    fields.update(overrides)
    return _save(session, Question(**fields), persist)


def make_map_question(session, subject, *, level=1, answer="yes", persist=True, **overrides):
    from models import MapQuestion

    fields = {
        "subject_id": subject.id,
        "level": level,
        "content_type": "multiple_choice",
        "question_prompt": "Choose",
        "question_text": f"Placement question at level {level}",
        "options": ["yes", "no"],
        "answer": answer,
    }
    fields.update(overrides)
    return _save(session, MapQuestion(**fields), persist)


def make_attendance(session, teacher, user, *, partner=None, duration=1.0, is_present=True, date=None, notes=None, persist=True, **overrides):
    from models import Attendance

    fields = {
        "teacher_id": teacher.id,
        "user_id": user.id,
        "partner_id": partner.id if partner else None,
        "duration": duration if is_present else 0.0,
        "is_present": is_present,
        "date": date or datetime.now(UTC),
        "notes": notes,
    }
    fields.update(overrides)
    return _save(session, Attendance(**fields), persist)


def make_worksheet(session, *, title=None, subject="English Grammar", persist=True, **overrides):
    from models import Worksheet

    fields = {
        "title": title or _unique("worksheet", "Worksheet"),
        "subject": subject,
        "content": "# Worksheet",
        "file_type": "md",
    }
    fields.update(overrides)
    return _save(session, Worksheet(**fields), persist)


def make_worksheet_assignment(session, teacher, learner, worksheet, *, volunteer=None, completed=False, persist=True, **overrides):
    from models import WorksheetAssignment

    fields = {
        "teacher_id": teacher.id,
        "learner_id": learner.id,
        "volunteer_id": volunteer.id if volunteer else None,
        "worksheet_id": worksheet.id,
        "completed": completed,
        "completed_at": datetime.now(UTC) if completed else None,
    }
    fields.update(overrides)
    return _save(session, WorksheetAssignment(**fields), persist)


def make_learning_session(session, learner, *, session_type="placement", lesson=None, persist=True, **overrides):
    from models import LearningSession

    fields = {
        "learner_id": learner.id,
        "session_type": session_type,
        "lesson_id": lesson.id if lesson else None,
        "subject_state": {},
        "asked_ids": [],
        "history": [],
        "count": 0,
        "responses": [],
        "correct_count": 0,
        "questions_completed": 0,
        "word_selection_attempts": {},
    }
    fields.update(overrides)
    return _save(session, LearningSession(**fields), persist)


def make_donation(session, *, amount=2500, school=None, donor_name="Anonymous", persist=True, **overrides):
    from models import Donation

    fields = {
        "stripe_session_id": _unique("donation", "cs_test"),
        "amount": amount,
        "donor_name": donor_name,
        "donor_email": "donor@example.com",
        "message": "Keep it up",
        "school_id": school.id if school else None,
        "status": "completed",
    }
    fields.update(overrides)
    return _save(session, Donation(**fields), persist)


def make_feature_announcement(session, *, roles=None, title="What's new", persist=True, **overrides):
    from models import FeatureAnnouncement

    fields = {
        "uid": _unique("announcement", "feature"),
        "content": {
            "layout": "standard",
            "title": title,
            "body": "A new thing landed.",
            "roles": list(roles) if roles else ["learner", "volunteer", "teacher"],
        },
    }
    fields.update(overrides)
    return _save(session, FeatureAnnouncement(**fields), persist)


def make_article(session, author, *, title=None, persist=True, **overrides):
    from models import Article

    fields = {
        "title": title or _unique("article", "Test Article"),
        "content_markdown": "# Heading\n\nBody text.",
        "author_id": author.id,
    }
    fields.update(overrides)
    return _save(session, Article(**fields), persist)


def make_site_content(session, *, key=None, value="Some copy", persist=True, **overrides):
    from models import SiteContent

    fields = {"key": key or _unique("site_content", "hero_title"), "value": value}
    fields.update(overrides)
    return _save(session, SiteContent(**fields), persist)


def make_team_member(session, *, name=None, persist=True, **overrides):
    from models import TeamMember

    fields = {
        "name": name or _unique("team_member", "Team Member"),
        "job": "Volunteer coordinator",
        "strengths": "Patience",
        "bio": "Bio text.",
    }
    fields.update(overrides)
    return _save(session, TeamMember(**fields), persist)


def make_assistant_conversation(session, teacher, *, title="Thread", persist=True, **overrides):
    from models import AssistantConversation

    fields = {"teacher_id": teacher.id, "title": title}
    fields.update(overrides)
    return _save(session, AssistantConversation(**fields), persist)


def make_assistant_message(session, conversation, *, role="user", content="Hello", persist=True, **overrides):
    from models import AssistantMessage

    fields = {"conversation_id": conversation.id, "role": role, "content": content}
    fields.update(overrides)
    return _save(session, AssistantMessage(**fields), persist)


def make_assistant_change(session, teacher, *, conversation=None, op="update", entity="Attendance", tool_name="update_attendance", tool_args=None, before=None, after=None, status="pending", persist=True, **overrides):
    from models import AssistantChange

    fields = {
        "teacher_id": teacher.id,
        "conversation_id": conversation.id if conversation else None,
        "op": op,
        "entity": entity,
        "tool_name": tool_name,
        "tool_args": tool_args if tool_args is not None else {},
        "before": before,
        "after": after,
        "status": status,
        "summary": "A proposed change",
    }
    fields.update(overrides)
    return _save(session, AssistantChange(**fields), persist)


def make_learning_content(session, *, game_type=None, persist=True):
    subject = make_subject(session, persist=False)
    topic = make_topic(session, subject, persist=False)
    lesson = make_lesson(session, topic, game_type=game_type, persist=False)
    question = make_question(session, subject, topic, lesson, persist=False)
    if persist:
        session.commit()
    return subject, topic, lesson, question


def record_answers(session, learner, lesson, outcomes, *, persist=True):
    """Log first-try results on the learner's answer log for ``lesson``, as validate-answer would.

    ``outcomes`` is one bool per question in id order: True answered right first time, False
    answered wrong then right. Games score from this log, not from what the browser reports.
    """
    from sqlalchemy import select

    from models import LearningSession, Question

    question_ids = session.scalars(select(Question.id).filter_by(lesson_id=lesson.id).order_by(Question.id)).all()
    responses = []
    for question_id, right_first_time in zip(question_ids, outcomes, strict=False):
        unit = f"q:{question_id}"
        if not right_first_time:
            responses.append({"unit": unit, "question_id": question_id, "is_correct": False,
                              "timestamp": "2026-01-01T00:00:00"})
        responses.append({"unit": unit, "question_id": question_id, "is_correct": True,
                          "timestamp": "2026-01-01T00:00:00"})
    log = session.scalar(select(LearningSession).filter_by(learner_id=learner.id, session_type="answer_log", lesson_id=lesson.id))
    if log is None:
        log = LearningSession(learner_id=learner.id, session_type="answer_log", lesson_id=lesson.id)
        session.add(log)
    log.responses = [*(log.responses or []), *responses]
    return _save(session, log, persist)

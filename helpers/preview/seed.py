"""A preview's database and bucket, rebuilt from nothing: the public sample curriculum from
`seed/files/`, the personas, and generated people around them.

A script rather than a committed database, so it runs after the PR's own migrations and always
matches the PR's schema: a PR that changes the schema updates this in the same diff. The random
choices are fixed, so the same size gives the same people on every preview, including `main`'s,
which is what makes timings comparable. Nothing here runs outside `APP_ENV=preview`.
"""

from __future__ import annotations

import os
import random
import secrets
import shutil
import threading
from datetime import timedelta

from extensions import db
from helpers.preview.personas import PERSONAS, PERSONAS_BY_SLUG
from settings import get_settings

__all__ = ["SIZES", "find_persona", "seed_preview"]

#: The only sizes there are, so reseeding stays bounded in time and memory. `large` is sized for
#: timing the matcher.
SIZES: dict[str, dict[str, int]] = {
    "small": {
        "learners": 40, "volunteers": 24, "assignments": 80,
        "attendance_weeks": 4, "donations": 12, "articles": 3,
    },
    "large": {
        "learners": 1500, "volunteers": 700, "assignments": 3000,
        "attendance_weeks": 3, "donations": 200, "articles": 30,
    },
}
RANDOM_SEED = 13
SCHOOL_NAME = "Preview School"

_LANGUAGES = ("English", "Greek", "Arabic", "French", "Farsi", "Ukrainian", "Somali", "Turkish")
_FLUENCY = ("Beginner", "Intermediate", "Advanced")
_PERSONALITIES = ("introvert", "extrovert", "ambivert")
_TRAITS = ("patient", "funny", "calm", "curious", "organised", "creative")
_HOBBIES = ("football", "drawing", "music", "reading", "cooking", "dancing", "chess")
_TECH = ("games", "video", "coding", "photography")
_ACTIVITIES = ("conversation", "games", "reading", "homework")

_lock = threading.Lock()


def find_persona(slug: str):
    """The seeded account behind a persona slug, or None for an unknown slug or a deleted account."""
    from helpers.auth_utils import find_by_email, find_by_username

    persona = PERSONAS_BY_SLUG.get(slug)
    if persona is None:
        return None
    return find_by_email(persona.login) if "@" in persona.login else find_by_username(persona.login)


def _empty_database_and_bucket() -> None:
    """Delete every row and file, keeping the schema the migrations built."""
    from helpers.storage import LocalBucket, get_bucket

    db.session.remove()
    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())
    db.session.commit()

    bucket = get_bucket()
    assert isinstance(bucket, LocalBucket)  # APP_ENV=preview configures no other kind
    shutil.rmtree(bucket.root, ignore_errors=True)
    os.makedirs(bucket.root, exist_ok=True)


def _load_content() -> None:
    """The sample curriculum, worksheets and announcements. A failure stops the boot: a preview
    that silently lacks its questions would look like the PR broke them."""
    from helpers.announcements import sync_announcements
    from helpers.content import import_questions
    from helpers.content_source import staged_content
    from helpers.seed import FILES_DIR
    from helpers.storage import LocalBucket, get_bucket
    from helpers.worksheet_manifest import sync_worksheet_manifest

    bucket = get_bucket()
    assert isinstance(bucket, LocalBucket)
    bucket.seed_from(FILES_DIR)
    with staged_content(bucket) as folder:
        import_questions(db, os.path.join(folder, "questions.json"))
        sync_worksheet_manifest(bucket, os.path.join(folder, "worksheets"))
        sync_announcements(os.path.join(folder, "announcements.json"))


def _survey(rng: random.Random) -> dict[str, object]:
    return {
        "age": str(rng.randint(13, 18)),
        "languages": [
            {"language": language, "level": rng.choice(_FLUENCY)}
            for language in rng.sample(_LANGUAGES, rng.randint(1, 3))
        ],
        "personality": rng.choice(_PERSONALITIES),
        "traits": rng.sample(_TRAITS, 2),
        "hobbies": rng.sample(_HOBBIES, 3),
        "tech_interest": rng.sample(_TECH, 1),
        "match_activities": rng.sample(_ACTIVITIES, 2),
    }


def _place_part_way(learner) -> None:
    """Give a learner the first topic of the first course, one lesson into the second, and XP."""
    from models import Subject

    course = db.session.scalars(
        db.select(Subject).where(Subject.map_test_only.is_(False)).order_by(Subject.id)
    ).first()
    if course is None:
        return
    first, *rest = sorted(course.topics, key=lambda topic: (topic.level, topic.id))
    lessons = sorted(lesson.id for lesson in first.lessons)
    if rest:
        lessons += sorted(lesson.id for lesson in rest[0].lessons)[:1]
    learner.completed_topic_ids = [first.id]
    learner.completed_lesson_ids = lessons
    learner.xp = 450
    if course.placement_scale is not None:
        learner.subject_levels = {course.placement_scale.name: course.placement_min_level or 1}


def _create_personas():
    """The school and the seven accounts. Passwords are random and told to nobody: the persona
    links are the way in."""
    from models import Administrator, Learner, School, SchoolAdmin, Teacher, Volunteer

    school = School(
        name=SCHOOL_NAME, mission_statement="A made-up school for previews.", location="Nowhere",
        volunteer_domain="preview.test", teacher_domain="preview.test",
    )
    db.session.add(school)
    db.session.flush()

    names = {persona.slug: (persona.login, persona.name) for persona in PERSONAS}

    def with_password(user):
        user.set_password(secrets.token_urlsafe(16))
        return user

    login, name = names["teacher"]
    teacher = Teacher(email=login, name=name, google_sub="preview:teacher", school_id=school.id)
    db.session.add(teacher)
    db.session.flush()

    login, name = names["volunteer"]
    volunteer = Volunteer(
        email=login, name=name, google_sub="preview:volunteer", school_id=school.id,
        teacher_id=teacher.id, completed_survey=True, match_capacity=2,
    )
    db.session.add(volunteer)
    login, name = names["admin"]
    db.session.add(with_password(Administrator(username=login, name=name)))
    login, name = names["school-admin"]
    db.session.add(with_password(SchoolAdmin(username=login, name=name, school_id=school.id)))

    learners = {}
    for slug in ("learner-new", "learner-midpath", "learner-matched"):
        login, name = names[slug]
        learner = with_password(Learner(
            username=login, name=name, school_id=school.id, teacher_id=teacher.id,
            completed_survey=True, completed_map_test=slug != "learner-new",
        ))
        db.session.add(learner)
        learners[slug] = learner
    db.session.flush()

    _place_part_way(learners["learner-midpath"])
    _place_part_way(learners["learner-matched"])
    learners["learner-matched"].volunteer_match = volunteer
    learners["learner-matched"].is_matched = True
    volunteer.is_matched = True
    db.session.commit()
    return school, teacher, volunteer, learners


def _give_the_pair_a_history(teacher, volunteer, learner) -> None:
    from helpers.utils import utcnow_naive
    from models import Attendance, Worksheet, WorksheetAssignment

    sheets = db.session.scalars(db.select(Worksheet).order_by(Worksheet.id).limit(2)).all()
    for index, sheet in enumerate(sheets):
        done = index == 0
        db.session.add(WorksheetAssignment(
            teacher_id=teacher.id, learner_id=learner.id, volunteer_id=volunteer.id, worksheet_id=sheet.id,
            completed=done, completed_at=utcnow_naive() if done else None,
        ))
    for week in range(1, 4):
        for person, partner in ((learner, volunteer), (volunteer, learner)):
            db.session.add(Attendance(
                date=utcnow_naive() - timedelta(weeks=week), duration=1.0, is_present=True,
                teacher_id=teacher.id, user_id=person.id, partner_id=partner.id,
            ))


def seed_preview(size: str = "small") -> list[str]:
    """Replace everything in the preview with a fresh seed of `size`.

    Args:
        size (str): A key of `SIZES`.

    Returns:
        list[str]: Summary lines.

    Raises:
        RuntimeError: The app is not running as a preview; nothing was touched.
        ValueError: `size` is not one of `SIZES`.
    """
    from helpers.flood import flood_database
    from models import Learner, Volunteer

    if not get_settings().is_preview:
        raise RuntimeError("Only an APP_ENV=preview app may be wiped and reseeded.")
    if size not in SIZES:
        raise ValueError(f"size must be one of: {', '.join(SIZES)}")

    with _lock:
        _empty_database_and_bucket()
        _load_content()
        school, teacher, volunteer, learners = _create_personas()
        counts = SIZES[size]
        # Half the volunteers stay free, and learners outnumber the slots taken, so there is
        # always matching left to do. The persona teacher is the only one, so all are theirs.
        summary = flood_database(
            learners=counts["learners"], volunteers=counts["volunteers"], worksheets=0,
            assignments=counts["assignments"], attendance_weeks=counts["attendance_weeks"],
            donations=counts["donations"], articles=counts["articles"], seed=RANDOM_SEED,
            matched_share=0.5,
        )
        rng = random.Random(RANDOM_SEED)
        for model in (Learner, Volunteer):
            for person in db.session.scalars(db.select(model).order_by(model.id)):
                person.survey_data = _survey(rng)
        _give_the_pair_a_history(teacher, volunteer, learners["learner-matched"])
        db.session.commit()
    # The last line is the flooded learners' password; the personas are the way in.
    return [f"Seeded the {size} preview data in {school.name}.", *summary[:-1]]

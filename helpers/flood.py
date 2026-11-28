"""Bulk fake data, for load-testing tables and sizing a PR preview's matching.

Adds learners, volunteers, matches, worksheets, worksheet assignments, attendance history,
donations and articles around the schools and teachers the database already has, and only ever
adds rows. It refuses to run anywhere but development (the dev SQLite file or
`TEST_DATABASE_URL`) and a PR preview. `scripts/flood.py` is its command line.
"""

from __future__ import annotations

import os
import random
import secrets
import uuid
from datetime import UTC, datetime, timedelta

FIRST_NAMES = [
    "Amira", "Yusuf", "Zahra", "Eleni", "Nikos", "Maria", "Giorgos", "Fatima",
    "Ahmad", "Layla", "Omar", "Noor", "Hassan", "Sara", "Ibrahim", "Aisha",
    "Mohamed", "Halima", "Abdullahi", "Asha", "Petra", "Dimitris", "Sofia",
    "Kostas", "Anastasia", "Vasilis", "Katerina", "Andreas", "Elif", "Mehmet",
    "Zeynep", "Emre", "Volodymyr", "Olena", "Dmytro", "Iryna", "Taras",
    "Nadia", "Farid", "Roya", "Aziz", "Meena", "Karim", "Leila", "Bilal",
    "Samira", "Rashid", "Hodan", "Mustafa", "Amina",
]

LAST_NAMES = [
    "Haddad", "Rahimi", "Warsame", "Papadopoulos", "Antoniou", "Bennett",
    "Novak", "Khalil", "Farah", "Osman", "Said", "Popescu", "Ionescu",
    "Georgiou", "Nikolaidis", "Konstantinou", "Okoye", "Adan", "Yusuf",
    "Ahmadi", "Karimi", "Hassan", "Ali", "Ibrahim", "Kovalenko", "Melnyk",
    "Bondar", "Sahin", "Yildiz", "Demir", "Kaya", "Noor", "Farooq", "Malik",
    "Aziz", "Rahman", "Suleiman", "Barre", "Mohamud", "Abdi",
]

ARTICLE_HEADLINES = [
    "A Day in the Classroom", "Meet This Term's New Volunteers",
    "Why Reading Together Matters", "Behind the Scenes at Our School",
    "A Learner's First Milestone", "Notes from the Partnership",
    "Building Confidence One Worksheet at a Time", "Celebrating a Small Win",
    "What We Learned This Term", "Volunteer Spotlight",
]

WORKSHEET_TOPICS = [
    ("Sight Words", "Basics"),
    ("Sight Words", "High Frequency Words"),
    ("English Grammar", "Nouns and Verbs"),
    ("English Grammar", "Sentence Building"),
    ("Phonics for Reading — Second Level", "Blending Sounds"),
    ("Phonics for Reading — Second Level", "Consonant Digraphs"),
    ("Numeracy", "Counting"),
    ("Numeracy", "Addition"),
]

#: Used when a school has no email domain of its own; `.test` can never be a real address.
FALLBACK_DOMAIN = "example.test"


def _unique(base: str, existing: set[str]) -> str:
    """`base` if free, else `base2`, `base3`, ... — adds the winner to `existing`."""
    candidate, n = base, 2
    while candidate in existing:
        candidate = f"{base}{n}"
        n += 1
    existing.add(candidate)
    return candidate


def _unique_email(local: str, domain: str, existing: set[str]) -> str:
    candidate, n = f"{local}@{domain}", 2
    while candidate in existing:
        candidate = f"{local}{n}@{domain}"
        n += 1
    existing.add(candidate)
    return candidate


def flood_database(
    *,
    learners: int = 200,
    volunteers: int = 100,
    teachers: int = 0,
    worksheets: int = 30,
    assignments: int = 400,
    attendance_weeks: int = 8,
    donations: int = 60,
    articles: int = 50,
    school_names: list[str] | None = None,
    seed: int | None = None,
    password: str | None = None,
    dry_run: bool = False,
    matched_share: float = 1.0,
) -> list[str]:
    """Add bulk demo data and commit it (or roll it back on a dry run).

    Matches, assignments and attendance are built only among the people created in this call;
    existing rows are never touched. Articles are authored by existing administrators, the only
role that writes articles in the app (and the only one whose deletion reassigns them).
    Must run inside an app context.

    Args:
        learners (int): Learners to add.
        volunteers (int): Volunteers to add.
        teachers (int): Teachers to add (spread over the chosen schools) before anyone else.
        worksheets (int): Markdown worksheets to add.
        assignments (int): Worksheet assignments among the new learners.
        attendance_weeks (int): Weeks of attendance history per matched pair.
        donations (int): Completed donations to add.
        articles (int): Articles to add.
        school_names (list[str] | None): Only these schools; every school when omitted.
        seed (int | None): Fixes the random choices so a run can be repeated.
        password (str | None): Password for every new learner; random when omitted.
        dry_run (bool): Build everything, report it, save nothing.
        matched_share (float): Share of the new volunteers who are given learners. Below 1, some
            learners and volunteers stay unmatched, so the matcher has work to do.

    Returns:
        list[str]: Summary lines, or a single line saying why nothing was done.
    """
    from flask import current_app

    from extensions import db
    from helpers.paths import get_data_path
    from models import (
        Administrator,
        Article,
        Attendance,
        Donation,
        Learner,
        School,
        Teacher,
        Volunteer,
        Worksheet,
        WorksheetAssignment,
    )
    from settings import get_settings

    settings = get_settings()
    if not (settings.is_development or settings.is_preview):
        return ["Refusing: this app is not running in development. The flood script is development-only."]
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if settings.is_preview:
        allowed = {f"sqlite:///{os.path.join(settings.preview_data_dir, 'site.db')}"}
    else:
        allowed = {f"sqlite:///{get_data_path('site.db')}", settings.test_database_url} - {""}
    if uri not in allowed:
        scheme = uri.split("://")[0]
        return [f"Refusing: {scheme}://... is not the dev SQLite file or TEST_DATABASE_URL. This script is development-only."]

    rng = random.Random(seed)
    password = password or secrets.token_urlsafe(9)

    schools = db.session.scalars(db.select(School).order_by(School.id)).all()
    if school_names:
        unknown = [name for name in school_names if name not in {school.name for school in schools}]
        if unknown:
            return [f"No school named {', '.join(repr(name) for name in unknown)}."]
        schools = [school for school in schools if school.name in school_names]
    if not schools:
        return ["No schools exist — create one first (`uv run flask seed`); this script never creates schools."]
    school_ids = {school.id for school in schools}

    def name() -> tuple[str, str]:
        return rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)

    existing_emails = set(db.session.scalars(db.select(Volunteer.email)).all()) | set(
        db.session.scalars(db.select(Teacher.email)).all()
    )
    existing_subs = set(db.session.scalars(db.select(Volunteer.google_sub)).all()) | set(
        db.session.scalars(db.select(Teacher.google_sub)).all()
    )

    # --- Teachers (only when asked for) ---
    new_teachers = []
    for index in range(teachers):
        first, last = name()
        school = schools[index % len(schools)]
        teacher = Teacher(
            name=f"{first} {last}",
            email=_unique_email(f"{first.lower()}.{last.lower()}", school.teacher_domain or FALLBACK_DOMAIN, existing_emails),
            google_sub=_unique(f"flood-t-{first.lower()}{last.lower()}", existing_subs),
            school_id=school.id,
        )
        new_teachers.append(teacher)
    db.session.add_all(new_teachers)
    db.session.flush()

    all_teachers = [
        teacher for teacher in db.session.scalars(db.select(Teacher)).all() if teacher.school_id in school_ids
    ]
    if not all_teachers:
        return ["No teachers exist in the chosen schools — seed some or pass --teachers N."]

    existing_usernames = set(db.session.scalars(db.select(Learner.username)).all())

    # --- Learners ---
    new_learners = []
    password_hash = ""
    for _ in range(learners):
        first, last = name()
        teacher = rng.choice(all_teachers)
        learner = Learner(
            name=f"{first} {last}", school_id=teacher.school_id, teacher_id=teacher.id,
            completed_survey=True, completed_map_test=True, xp=rng.randint(0, 6000),
        )
        learner.username = _unique(f"{first.lower()}{last.lower()[:3]}", existing_usernames)
        if password_hash:
            learner.password_hash = password_hash
        else:
            learner.set_password(password)
            password_hash = learner.password_hash
        new_learners.append(learner)
    db.session.add_all(new_learners)
    db.session.flush()

    # --- Volunteers ---
    domains = {school.id: school.volunteer_domain or FALLBACK_DOMAIN for school in schools}
    new_volunteers = []
    for _ in range(volunteers):
        first, last = name()
        teacher = rng.choice(all_teachers)
        new_volunteers.append(Volunteer(
            name=f"{first} {last}",
            email=_unique_email(f"{first.lower()}.{last.lower()}", domains[teacher.school_id], existing_emails),
            google_sub=_unique(f"flood-{first.lower()}{last.lower()}", existing_subs),
            school_id=teacher.school_id, teacher_id=teacher.id, completed_survey=True,
            match_capacity=rng.choice([1, 1, 1, 2, 2, 3]),
        ))
    db.session.add_all(new_volunteers)
    db.session.flush()

    # --- Matches (new learners <-> new volunteers only) ---
    unmatched = list(new_learners)
    rng.shuffle(unmatched)
    index = 0
    matched_pairs = 0
    for volunteer in new_volunteers[:round(len(new_volunteers) * matched_share)]:
        for _ in range(volunteer.open_slots):
            if index >= len(unmatched):
                break
            learner = unmatched[index]
            index += 1
            learner.volunteer_match = volunteer
            learner.is_matched = True
            volunteer.is_matched = True
            matched_pairs += 1
    db.session.flush()

    # --- Worksheets ---
    new_worksheets = []
    for number in range(worksheets):
        subject, topic = rng.choice(WORKSHEET_TOPICS)
        title = f"{topic} Practice {number + 1}"
        content = f"# {title}\n\nSubject: {subject} | Topic: {topic}\n\nPractice worksheet content for {topic.lower()}."
        new_worksheets.append(Worksheet(title=title, subject=subject, topic=topic, content=content, file_type="md"))
    db.session.add_all(new_worksheets)
    db.session.flush()

    # --- Worksheet assignments (new learners only) ---
    pool = new_worksheets or db.session.scalars(db.select(Worksheet)).all()
    new_assignments = []
    if new_learners and pool:
        for _ in range(assignments):
            learner = rng.choice(new_learners)
            completed = rng.random() < 0.6
            assigned_at = datetime.now(UTC) - timedelta(days=rng.randint(0, 90))
            new_assignments.append(WorksheetAssignment(
                teacher_id=learner.teacher_id, learner_id=learner.id, volunteer_id=learner.volunteer_id,
                worksheet_id=rng.choice(pool).id, assigned_at=assigned_at, completed=completed,
                completed_at=assigned_at + timedelta(days=rng.randint(0, 5)) if completed else None,
            ))
    db.session.add_all(new_assignments)

    # --- Attendance (matched pairs only, one record per person per week) ---
    new_attendance = []
    for learner in (learner for learner in new_learners if learner.is_matched):
        volunteer = learner.volunteer_match
        if volunteer is None:
            continue
        for week in range(attendance_weeks):
            date = datetime.now(UTC) - timedelta(weeks=week, days=rng.randint(0, 2))
            present = rng.random() > 0.05
            duration = round(rng.uniform(0.5, 2.0), 2) if present else 0.0
            for person, partner in ((learner, volunteer), (volunteer, learner)):
                new_attendance.append(Attendance(
                    date=date, duration=duration, is_present=present,
                    teacher_id=learner.teacher_id, user_id=person.id, partner_id=partner.id,
                ))
    db.session.add_all(new_attendance)

    # --- Donations ---
    new_donations = []
    for _ in range(donations):
        first, last = name()
        new_donations.append(Donation(
            stripe_session_id=f"flood_{uuid.UUID(int=rng.getrandbits(128)).hex}",
            amount=rng.choice([500, 1000, 2500, 5000, 10000, 25000]),
            donor_name=f"{first} {last}", donor_email=f"{first.lower()}.{last.lower()}@{FALLBACK_DOMAIN}",
            school_id=rng.choice(schools).id, status="completed",
            created_at=datetime.now(UTC) - timedelta(days=rng.randint(0, 180)),
        ))
    db.session.add_all(new_donations)

    # --- Articles (authored by existing administrators) ---
    staff = db.session.scalars(db.select(Administrator)).all()
    new_articles = []
    for number in range(articles if staff else 0):
        author = rng.choice(staff)
        headline = rng.choice(ARTICLE_HEADLINES)
        created = datetime.now(UTC) - timedelta(days=rng.randint(0, 365))
        new_articles.append(Article(
            title=f"{headline} #{number + 1}",
            content_markdown=(
                f"# {headline}\n\nWritten by {author.name}.\n\n"
                "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
                "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."
            ),
            author_id=author.id, created_at=created, updated_at=created,
        ))
    db.session.add_all(new_articles)

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    prefix = "Would add (dry run, nothing saved)" if dry_run else "Added"
    return [
        (
            f"{prefix} {len(new_teachers)} teachers, {len(new_learners)} learners, {len(new_volunteers)} volunteers "
            f"({matched_pairs} matched pair(s))."
        ),
        f"{prefix} {len(new_worksheets)} worksheets, {len(new_assignments)} worksheet assignment(s).",
        (
            f"{prefix} {len(new_attendance)} attendance record(s), {len(new_donations)} donation(s), "
            f"{len(new_articles)} article(s)."
        ),
        f"Login: any new learner's username / password {password!r}.",
    ]

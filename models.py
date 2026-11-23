from __future__ import annotations

import hashlib
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any, ClassVar

from flask import g, has_request_context
from flask_login import UserMixin
from sqlalchemy import event
from sqlalchemy.orm import Mapped, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def _attendance_hours_cache() -> dict[int, float] | None:
    """The request's present-hours memo, or None when there is no request."""
    if not has_request_context():
        return None
    cache = getattr(g, "_attendance_hours", None)
    if cache is None:
        cache = {}
        g._attendance_hours = cache
    return cache


def _query_attendance_hours(user_ids: Collection[int]) -> dict[int, float]:
    """Sums present attendance hours for many users in one grouped query.

    Args:
        user_ids (Collection[int]): Users to total.

    Returns:
        dict[int, float]: User id -> hours, absent where the user has no rows.
    """
    if not user_ids:
        return {}
    rows = db.session.execute(
        db.select(Attendance.user_id, db.func.sum(Attendance.duration))
        .where(Attendance.user_id.in_(user_ids), Attendance.is_present)
        .group_by(Attendance.user_id)
    ).all()
    return {user_id: float(total or 0) for user_id, total in rows}


# Batched because every roster page reads this once per person: the first read
# of a request totals everyone already loaded, so a page's worth of people is
# one grouped query instead of one per card.
def attendance_hours(user_id: int) -> float:
    """Present attendance hours for one user, batched across the request.

    Args:
        user_id (int): The user to total.

    Returns:
        float: Hours present, 0.0 when the user has no attendance.
    """
    cache = _attendance_hours_cache()
    if cache is None:
        return _query_attendance_hours([user_id]).get(user_id, 0.0)

    if user_id not in cache:
        loaded = {
            obj.id for obj in list(db.session.identity_map.values())
            if isinstance(obj, User) and obj.id is not None
        }
        wanted = (loaded | {user_id}) - cache.keys()
        totals = _query_attendance_hours(wanted)
        cache.update({uid: totals.get(uid, 0.0) for uid in wanted})

    return cache[user_id]



# ======================
# Base User
# ======================
class User(db.Model, UserMixin):
    """Base of a joined-table-inheritance hierarchy — `Learner`, `Volunteer`,
    `Teacher`, `Administrator`, `SchoolAdmin` each add a child table keyed by
    `id` FK back to `users`, with `user_type` as the polymorphic
    discriminator. A query joining two subclasses must alias each with
    `aliased(Model, flat=True)`, or the shared `users` join gets emitted
    twice."""

    __tablename__ = "users"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    user_type: Mapped[str] = db.Column(db.String(50), nullable=False)
    name: Mapped[str | None] = db.Column(db.String(100), nullable=True)

    # Highest FeatureAnnouncement.id this user has dismissed. Deliberately not a
    # ForeignKey: it is a high-water mark, not a reference — deleting the
    # announcement it names must not cascade or null it, or every user would be
    # re-shown the announcements below it. NULL = has never dismissed one.
    last_seen_announcement_id: Mapped[int | None] = db.Column(db.Integer, nullable=True)

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_on": user_type,
        "polymorphic_identity": "user",
    }

    @property
    def posthog_id(self) -> str:
        """Pseudonymous PostHog distinct_id — never exposes a real user ID."""
        name = getattr(self, "username", None) or getattr(self, "email", None) or str(self.id)
        raw = f"{self.user_type}|{self.id}|{name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ======================
# Users: Learner
# ======================
class Learner(User):
    """A learner account (User subclass via joined-table inheritance). Most
    progress state here — placement results, XP, unlocked items, per-lesson
    completion — lives as JSON blobs (see the field-level comments below for
    each one's shape and empty-state meaning) rather than join tables, so a
    new lesson or game type needs no migration."""

    __tablename__ = "learners"

    id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)

    username: Mapped[str] = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = db.Column(db.String(200), nullable=False)

    completed_survey: Mapped[bool | None] = db.Column(db.Boolean, default=False)
    completed_map_test: Mapped[bool | None] = db.Column(db.Boolean, default=False)

    # "I'll do this later" — the learner deferred the placement test rather than
    # taking it. completed_map_test is still True (it's a gate, not a record: the
    # learner must be able to reach the dashboard), so this second flag is what
    # keeps the deferral distinguishable from a genuine completion. Drives the
    # dashboard reminder banner and re-opens /map-intro. Cleared when the test is
    # actually finished.
    map_test_deferred: Mapped[bool] = db.Column(db.Boolean, default=False, nullable=False, server_default=db.false())

    # Empty dict = "not assessed yet" (no map test taken). Do NOT default to a
    # real level — that makes the unassessed state indistinguishable from a
    # learner genuinely placed at level 1.
    subject_levels: Mapped[dict[str, Any]] = db.Column(db.JSON, default=dict, nullable=False)

    school_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True, index=True)
    school: Mapped[School | None] = relationship("School", back_populates="learners")

    survey_data: Mapped[dict[str, Any] | None] = db.Column(db.JSON, nullable=True)

    # Completed lesson/topic IDs stored as JSON lists. Replaces the old M2M tables
    # and completed_minigame_lessons JSON — all lesson types (quiz + games) use
    # these lists as the single source of completion truth.
    completed_lesson_ids: Mapped[list[int] | None] = db.Column(db.JSON, default=list, nullable=True)
    completed_topic_ids: Mapped[list[int] | None] = db.Column(db.JSON, default=list, nullable=True)

    xp: Mapped[int] = db.Column(db.Integer, default=0, nullable=False)
    unlocked_items: Mapped[list[str] | None] = db.Column(db.JSON, default=list, nullable=True)
    equipped_items: Mapped[dict[str, Any] | None] = db.Column(db.JSON, default=dict, nullable=True)
    # Golden potion XP boost: set by a first-time Potion Workshop completion with a golden potion,
    # spent by the next first-time lesson completion, which earns double XP. One at a time.
    xp_boost_pending: Mapped[bool] = db.Column(db.Boolean, default=False, nullable=False, server_default=db.false())

    # Persistent Garden Grow game state, kept across lessons/replays:
    # {"stages": [0-3] * 8, "colors": ["#RRGGBB" | null] * 8}. Empty dict =
    # garden never touched. Written via POST /api/garden.
    garden_state: Mapped[dict[str, Any] | None] = db.Column(db.JSON, default=dict, nullable=True)

    is_matched: Mapped[bool | None] = db.Column(db.Boolean, default=False)

    # NOT unique: one volunteer may hold several learners, up to
    # Volunteer.match_capacity. A learner still has at most one volunteer.
    volunteer_id: Mapped[int | None] = db.Column(
        db.Integer, db.ForeignKey("volunteers.id"), nullable=True, index=True
    )

    volunteer_match: Mapped[Volunteer | None] = relationship(
        "Volunteer",
        back_populates="learner_matches",
        foreign_keys=[volunteer_id],
    )

    teacher_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("teachers.id"), index=True)
    teacher: Mapped[Teacher | None] = relationship(
        "Teacher", back_populates="managed_learners", foreign_keys=[teacher_id]
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": "learner",
        "inherit_condition": (id == User.id),
    }

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def unmatch(self) -> Volunteer | None:
        """Detach from the current volunteer and re-sync both sides' flags.
        Use wherever a match is dissolved, or `is_matched` goes stale."""
        volunteer = self.volunteer_match
        self.volunteer_match = None
        self.volunteer_id = None
        self.is_matched = False
        if volunteer is not None:
            volunteer.sync_matched_flag(exclude_learner_id=self.id)
        return volunteer

    @property
    def hours_learned(self) -> float:
        """Total hours, computed live from Attendance (not a stale running total)."""
        return attendance_hours(self.id)

    @property
    def onboarding_step(self) -> str | None:
        """The first onboarding step still to do: "survey", then "placement" (taken or deferred
        both count as done), else None."""
        if not self.completed_survey:
            return "survey"
        if not self.completed_map_test:
            return "placement"
        return None

    @property
    def sort_name(self) -> str:
        """The key learner lists sort by: name, else username, case-insensitive."""
        return (self.name or self.username or "").lower()


# ======================
# Users: Volunteer
# ======================
class Volunteer(User):
    """A volunteer account (User subclass via joined-table inheritance),
    matched to one or more learners up to `match_capacity`. Capacity is
    per-volunteer and teacher-set — see `capacity`/`open_slots`/`is_full`,
    and dissolve a match only through `Learner.unmatch()` /
    `release_learners()`, never by editing the FK directly, or the
    `is_matched` flags on both sides drift out of sync."""

    __tablename__ = "volunteers"

    id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)

    google_sub: Mapped[str] = db.Column(db.String(128), unique=True, nullable=False, index=True)
    completed_survey: Mapped[bool | None] = db.Column(db.Boolean, default=False)

    email: Mapped[str] = db.Column(db.String(150), unique=True, nullable=False, index=True)
    user_picture: Mapped[str | None] = db.Column(db.String(250), nullable=True)

    school_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True, index=True)
    school: Mapped[School | None] = relationship("School", back_populates="volunteers")

    survey_data: Mapped[dict[str, Any] | None] = db.Column(db.JSON, nullable=True)
    is_matched: Mapped[bool | None] = db.Column(db.Boolean, default=False)

    # How many learners this volunteer may hold at once. Teacher-controlled;
    # 1 = the classic one-to-one pairing. Never lower than the number of
    # learners already attached — routes reject that instead of auto-unmatching.
    match_capacity: Mapped[int] = db.Column(
        db.Integer, default=1, nullable=False, server_default="1"
    )

    # Eager by batch, not by row: `open_slots` counts this collection and is
    # read for practically every volunteer the app loads (roster cards, the
    # matcher's candidate pool, capacity checks), so lazy loading it costs one
    # query per volunteer on any page showing more than one. Eager loaders run
    # at query time only, so an expired volunteer is back to one query each on
    # access — re-query a roster rather than looping over it after
    # `expire_all()`.
    learner_matches: Mapped[list[Learner]] = relationship(
        "Learner",
        back_populates="volunteer_match",
        foreign_keys="Learner.volunteer_id",
        lazy="selectin",
    )

    teacher_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("teachers.id"), index=True)
    teacher: Mapped[Teacher | None] = relationship(
        "Teacher", back_populates="managed_volunteers", foreign_keys=[teacher_id]
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": "volunteer",
        "inherit_condition": (id == User.id),
    }

    @property
    def learner_match(self) -> Learner | None:
        """First attached learner, or None — for single-partner views."""
        matches = self.learner_matches
        return matches[0] if matches else None

    @property
    def capacity(self) -> int:
        """Effective capacity — never below 1, NULL reads as unbackfilled."""
        return max(1, self.match_capacity or 1)

    @property
    def open_slots(self) -> int:
        return max(0, self.capacity - len(self.learner_matches))

    @property
    def is_full(self) -> bool:
        return self.open_slots == 0

    def sync_matched_flag(self, exclude_learner_id: int | None = None) -> int:
        """Set is_matched from the attached learners; `exclude_learner_id`
        skips one detached this transaction (collection stale until flush)."""
        remaining = [
            l for l in self.learner_matches if l.id != exclude_learner_id
        ]
        self.is_matched = bool(remaining)
        return len(remaining)

    def release_learners(self) -> None:
        """Detach every learner (volunteer deleted / school dissolved)."""
        for learner in list(self.learner_matches):
            learner.volunteer_match = None
            learner.volunteer_id = None
            learner.is_matched = False
        self.is_matched = False

    @property
    def hours_volunteered(self) -> float:
        """Total volunteering hours, computed live from Attendance (same shape as Learner.hours_learned)."""
        return attendance_hours(self.id)

    @property
    def short_name(self) -> str:
        """What lists call the volunteer: their name, else the part of their email before the @."""
        return self.name or self.email.split("@")[0]


# ======================
# Users: Teacher
# ======================
class Teacher(User):
    """A teacher account (User subclass via joined-table inheritance) that
    manages a roster of learners and volunteers within a school."""

    __tablename__ = "teachers"

    id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    google_sub: Mapped[str] = db.Column(db.String(128), unique=True, nullable=False, index=True)

    email: Mapped[str] = db.Column(db.String(150), unique=True, nullable=False, index=True)
    user_picture: Mapped[str | None] = db.Column(db.String(250), nullable=True)

    school_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True, index=True)
    school: Mapped[School | None] = relationship("School", back_populates="teachers")

    managed_learners: Mapped[list[Learner]] = relationship(
        "Learner", back_populates="teacher", foreign_keys="Learner.teacher_id"
    )

    managed_volunteers: Mapped[list[Volunteer]] = relationship(
        "Volunteer", back_populates="teacher", foreign_keys="Volunteer.teacher_id"
    )

    # Learner limit handed to volunteers who join under this teacher. Changing
    # it never rewrites a volunteer already on the roster — their own
    # Volunteer.match_capacity stays authoritative.
    default_match_capacity: Mapped[int] = db.Column(
        db.Integer, default=1, nullable=False, server_default="1"
    )

    # How this teacher wants the matcher to weigh things, as
    # `{"weights": {<factor>: <level>}, "spread": <level>}`. Stores level
    # indices, never multipliers, so retuning the curve moves every roster at
    # once — helpers/matching.normalize_levels resolves them and is what makes
    # a NULL, partial or hand-edited blob read as the balanced defaults.
    match_settings: Mapped[dict[str, Any] | None] = db.Column(
        db.JSON, default=dict, nullable=True
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": "teacher",
        "inherit_condition": (id == User.id),
    }


# ======================
# Users: Administrator
# ======================
class Administrator(User):
    """Site-wide admin account, authenticated by username/password rather
    than Google OAuth, and not scoped to any single school."""

    __tablename__ = "administrators"

    id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)

    username: Mapped[str] = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = db.Column(db.String(200), nullable=False)

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": "administrator",
        "inherit_condition": (id == User.id),
    }

    def set_password(self, password: str) -> None:
        from werkzeug.security import generate_password_hash

        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        from werkzeug.security import check_password_hash

        return check_password_hash(self.password_hash, password)


# ======================
# Users: SchoolAdmin
# ======================
class SchoolAdmin(User):
    """Per-school admin account, authenticated by username/password and
    scoped to exactly one school via a required `school_id`."""

    __tablename__ = "school_admins"

    id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)

    username: Mapped[str] = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = db.Column(db.String(200), nullable=False)

    school_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    school: Mapped[School] = relationship("School", back_populates="school_admin")

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_identity": "school_admin",
        "inherit_condition": (id == User.id),
    }

    def set_password(self, password: str) -> None:
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)


# ======================
# Content: Article
# ======================
class Article(db.Model):
    """A CMS blog-style article authored by a User (any role) and shown on
    the public site."""

    __tablename__ = "articles"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    title: Mapped[str] = db.Column(db.String(255), nullable=False)
    content_markdown: Mapped[str] = db.Column(db.Text, nullable=False)
    # Stored image filename (`helpers/images.IMAGE_FILENAME_RE`), served by `base.article_image`.
    hero_image: Mapped[str | None] = db.Column(db.String(64), nullable=True)
    author_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    author: Mapped[User] = relationship("User", foreign_keys=[author_id])


# ======================
# Content: SiteContent
# ======================
class SiteContent(db.Model):
    """Generic key/value store for editable site copy (mission statement,
    about-page text, etc.) that doesn't warrant its own column or table."""

    __tablename__ = "site_content"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    key: Mapped[str] = db.Column(db.String(100), unique=True, nullable=False)
    value: Mapped[str] = db.Column(db.Text, nullable=False)


# ======================
# Content: TeamMember
# ======================
class TeamMember(db.Model):
    """A person listed on the public "our team" page."""

    __tablename__ = "team_members"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    name: Mapped[str] = db.Column(db.String(150), nullable=False)
    job: Mapped[str | None] = db.Column(db.String(150), nullable=True)
    strengths: Mapped[str | None] = db.Column(db.Text, nullable=True)
    bio: Mapped[str | None] = db.Column(db.Text, nullable=True)
    image_url: Mapped[str | None] = db.Column(db.String(300), nullable=True)


# ======================
# Users: School
# ======================
class School(db.Model):
    """A partner school/organization. `volunteer_domain`/`teacher_domain`
    drive which Google-OAuth email domain routes a new signup into which
    role; `invite_code` lets learners and volunteers join, and stays the same
    until a teacher regenerates it."""

    __tablename__ = "schools"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    name: Mapped[str] = db.Column(db.String(200), nullable=False, unique=True)

    mission_statement: Mapped[str | None] = db.Column(db.Text, nullable=True)
    # Under static/ (e.g. "img/schools/x.jpg"), never a URL — public pages only show our own files.
    image_path: Mapped[str | None] = db.Column(db.String(255), nullable=True)
    # Same rule as image_path; without one, public pages draw the school's initials.
    logo_path: Mapped[str | None] = db.Column(db.String(255), nullable=True)
    location: Mapped[str | None] = db.Column(db.String(120), nullable=True)

    @property
    def initials(self) -> str:
        """Up to two letters standing in for the school's logo: "Harbour View School" -> "HV"."""
        return "".join(word[0] for word in self.name.split() if word[:1].isalpha())[:2].upper()

    volunteer_domain: Mapped[str | None] = db.Column(db.String(100), nullable=True)
    teacher_domain: Mapped[str | None] = db.Column(db.String(100), nullable=True)
    invite_code: Mapped[str | None] = db.Column(db.String(16), nullable=True)

    teachers: Mapped[list[Teacher]] = relationship("Teacher", back_populates="school")
    learners: Mapped[list[Learner]] = relationship("Learner", back_populates="school")
    volunteers: Mapped[list[Volunteer]] = relationship("Volunteer", back_populates="school")
    school_admin: Mapped[SchoolAdmin | None] = relationship("SchoolAdmin", back_populates="school", uselist=False)

    # One code, one school; many schools may have none yet (NULLs do not collide).
    __table_args__ = (db.Index("uq_schools_invite_code", "invite_code", unique=True),)


# ======================
# Attendance
# ======================
class Attendance(db.Model):
    """One person's own account of one session on one day, paired against
    whoever they sat with. A Learner and their Volunteer each hold an
    independent record for the same day — the Volunteer's is seeded from the
    Learner's numbers when the session is first logged, and free to diverge on
    a later edit. See `docs/adr/0001-per-person-attendance-records.md`.
    """
    __tablename__ = "attendance"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    date: Mapped[datetime] = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(UTC))
    duration: Mapped[float] = db.Column(db.Float, nullable=False)

    # "absent" is a recorded no-show, not a missing row — without it there is no
    # way to tell "didn't meet" from "nobody logged it", and attendance rate
    # can't be computed. Absent rows always carry duration 0.0 so the live
    # hours_learned / hours_volunteered sums stay correct. Every record — a
    # learner's or a volunteer's own — carries an explicit mark; there is no
    # "nobody marked it yet" state once the record exists.
    is_present: Mapped[bool] = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    notes: Mapped[str | None] = db.Column(db.Text, nullable=True)

    # Who took the register. None once that teacher's account is deleted — the
    # record stays, since a volunteer's hours are summed live from these rows.
    teacher_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=True, index=True)
    # Whichever person this record belongs to — a Learner or a Volunteer, both
    # User subclasses via joined-table inheritance. Never walk this as if it
    # were the old learner_id/volunteer_id pair on one shared row.
    user_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Who they were paired with that session, if anyone — an unmatched
    # learner's own record carries no partner.
    partner_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    teacher: Mapped[Teacher | None] = relationship("Teacher", foreign_keys=[teacher_id])
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    partner: Mapped[User | None] = relationship("User", foreign_keys=[partner_id])

    __table_args__ = (
        db.Index("ix_attendance_teacher_date", "teacher_id", "date"),
        # Natural key for upsert/dedup — a re-submit for the same person paired
        # with the same partner on the same day corrects that row instead of
        # duplicating it. Matched against a day range (day_bounds), never
        # equality — rows carry a time of day.
        db.Index("ix_attendance_natural_key", "date", "user_id", "partner_id"),
    )

    @staticmethod
    def programme_hours(learner_ids: Collection[int] | None = None) -> float:
        """Total learning hours across the programme, or across `learner_ids`.
        Counts learner-owned rows only — a matched pair's own two rows for
        the same hour would double-count a bare `SUM(duration)` over the table."""
        stmt = (
            db.select(db.func.sum(Attendance.duration))
            .join(Learner, Learner.id == Attendance.user_id)
            .where(Attendance.is_present)
        )
        if learner_ids is not None:
            if not learner_ids:
                return 0.0
            stmt = stmt.where(Attendance.user_id.in_(learner_ids))
        return float(db.session.scalar(stmt) or 0)


# ======================
# Worksheets
# ======================
class Worksheet(db.Model):
    """A worksheet document, either markdown or PDF. `filepath` is a GCS
    key or local path, and is NULL for uploaded markdown whose content is
    stored directly in `content` rather than as a saved blob. A markdown row
    from `seed/files/worksheets/manifest.json` keeps its content inline too, but
    holds `storage.key_for(file)` in `filepath` as its identity."""

    __tablename__ = "worksheets"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    title: Mapped[str] = db.Column(db.String(255), nullable=False)
    subject: Mapped[str] = db.Column(db.String(100), nullable=False)
    topic: Mapped[str | None] = db.Column(db.String(100), nullable=True)
    filepath: Mapped[str | None] = db.Column(db.String(255), nullable=True, unique=True, index=True)
    content: Mapped[str | None] = db.Column(db.Text, nullable=True)
    file_type: Mapped[str] = db.Column(db.String(10), nullable=False, default="md")
    #: A level on the English placement scale (ADR 0016), or None.
    level: Mapped[int | None] = db.Column(db.Integer, nullable=True)
    #: Short lowercase labels the library search matches.
    tags: Mapped[list[str] | None] = db.Column(db.JSON, default=list, nullable=True)


class WorksheetAssignment(db.Model):
    """One worksheet handed to one learner by one teacher (optionally
    co-assigned to a volunteer), tracking completion independently of the
    Worksheet content itself."""

    __tablename__ = "worksheet_assignments"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    assigned_at: Mapped[datetime] = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    completed: Mapped[bool] = db.Column(db.Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = db.Column(db.DateTime, nullable=True)

    # None once the assigning teacher's account is deleted; the learner keeps the worksheet.
    teacher_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=True, index=True)
    learner_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("learners.id"), nullable=False, index=True)
    volunteer_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("volunteers.id"), nullable=True, index=True)
    worksheet_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("worksheets.id"), nullable=False, index=True)

    teacher: Mapped[Teacher | None] = relationship("Teacher", foreign_keys=[teacher_id])
    learner: Mapped[Learner] = relationship("Learner", foreign_keys=[learner_id])
    volunteer: Mapped[Volunteer | None] = relationship("Volunteer", foreign_keys=[volunteer_id])
    worksheet: Mapped[Worksheet] = relationship("Worksheet", foreign_keys=[worksheet_id])

    @property
    def pair_volunteer(self) -> Volunteer | None:
        """The volunteer this sheet is for: the one it was assigned with, else the learner's current match."""
        return self.volunteer or (self.learner.volunteer_match if self.learner else None)


# ======================
# AI Assistant
# ======================
ASSISTANT_CHANGE_STATUSES = ("pending", "applied", "rejected", "stale")


class AssistantConversation(db.Model):
    """One teacher's chat thread with the assistant."""
    __tablename__ = "assistant_conversations"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    teacher_id: Mapped[int] = db.Column(
        db.Integer, db.ForeignKey("teachers.id"), nullable=False, index=True
    )
    title: Mapped[str | None] = db.Column(db.String(200), nullable=True)
    created_at: Mapped[datetime] = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    teacher: Mapped[Teacher] = relationship("Teacher", foreign_keys=[teacher_id])
    messages: Mapped[list[AssistantMessage]] = relationship(
        "AssistantMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.id",
    )


class AssistantMessage(db.Model):
    """One turn in an AssistantConversation. Tool calls the assistant made
    during a turn are not stored as separate messages — they're summarized
    into that turn's `tool_events` so a reopened panel can redraw what the
    assistant did without replaying raw tool traffic."""

    __tablename__ = "assistant_messages"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    conversation_id: Mapped[int] = db.Column(
        db.Integer, db.ForeignKey("assistant_conversations.id"), nullable=False, index=True
    )
    # "user" | "assistant" — tool traffic is not replayed to the panel, it is
    # summarized into tool_events on the assistant turn that made the calls.
    role: Mapped[str] = db.Column(db.String(20), nullable=False)
    content: Mapped[str | None] = db.Column(db.Text, nullable=True)
    # [{"tool": name, "label": human label, "ms": int, "ok": bool}] — the step
    # list, so a reopened panel redraws what the assistant actually did instead
    # of showing a bare answer with no working.
    tool_events: Mapped[list[dict[str, Any]] | None] = db.Column(db.JSON, nullable=True)
    created_at: Mapped[datetime] = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    conversation: Mapped[AssistantConversation] = relationship("AssistantConversation", back_populates="messages")


class AssistantChange(db.Model):
    """A write the assistant proposed and a teacher has not applied yet.

    Carries **both** a field diff and the tool call that produced it. The diff
    drives the review card and is what the teacher edits; the tool call is what
    replays through `helpers/teacher_ops.py` on apply, so applying can never
    sidestep the validation the real routes run. Edited `after` values are
    merged into the replayed arguments.
    """
    __tablename__ = "assistant_changes"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    conversation_id: Mapped[int | None] = db.Column(
        db.Integer, db.ForeignKey("assistant_conversations.id"), nullable=True, index=True
    )
    teacher_id: Mapped[int] = db.Column(
        db.Integer, db.ForeignKey("teachers.id"), nullable=False, index=True
    )
    # Apply order within a conversation. A change whose parent was rejected is
    # skipped rather than applied against state that never happened.
    seq: Mapped[int] = db.Column(db.Integer, nullable=False, default=0)
    depends_on_id: Mapped[int | None] = db.Column(
        db.Integer, db.ForeignKey("assistant_changes.id"), nullable=True
    )

    op: Mapped[str] = db.Column(db.String(10), nullable=False)  # create | update | delete
    entity: Mapped[str] = db.Column(db.String(60), nullable=False)  # mapped model name
    pk: Mapped[dict[str, Any] | None] = db.Column(db.JSON, nullable=True)  # null until a staged create is applied
    before: Mapped[dict[str, Any] | None] = db.Column(db.JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = db.Column(db.JSON, nullable=True)

    tool_name: Mapped[str] = db.Column(db.String(60), nullable=False)
    tool_args: Mapped[dict[str, Any]] = db.Column(db.JSON, nullable=False, default=dict)
    summary: Mapped[str | None] = db.Column(db.String(300), nullable=True)

    status: Mapped[str] = db.Column(
        db.String(10), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    applied_at: Mapped[datetime | None] = db.Column(db.DateTime, nullable=True)
    error: Mapped[str | None] = db.Column(db.Text, nullable=True)

    conversation: Mapped[AssistantConversation | None] = relationship("AssistantConversation", foreign_keys=[conversation_id])
    teacher: Mapped[Teacher] = relationship("Teacher", foreign_keys=[teacher_id])
    depends_on: Mapped[AssistantChange | None] = relationship("AssistantChange", remote_side=[id])

    __table_args__ = (
        db.Index("ix_assistant_changes_teacher_status", "teacher_id", "status"),
    )


# ======================
# Donations
# ======================
class Donation(db.Model):
    """A completed Stripe donation. Written only by
    `routes/base.py:record_donation_from_session()` — the Stripe webhook,
    plus `/donation-success` for local dev — and idempotent on
    `stripe_session_id` so a webhook replay never duplicates a row."""

    __tablename__ = "donations"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    stripe_session_id: Mapped[str] = db.Column(db.String(200), unique=True, nullable=False)
    amount: Mapped[int] = db.Column(db.Integer, nullable=False)  # cents
    donor_name: Mapped[str | None] = db.Column(db.String(150), nullable=True)
    donor_email: Mapped[str | None] = db.Column(db.String(150), nullable=True)
    message: Mapped[str | None] = db.Column(db.Text, nullable=True)
    # No denormalized school_name copy — join via school_id → School.name at read
    # time so a renamed school is never shown stale.
    school_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True)
    school: Mapped[School | None] = relationship("School")
    status: Mapped[str] = db.Column(db.String(50), nullable=False, default="completed")
    created_at: Mapped[datetime] = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(UTC))


# ======================
# Feature announcements
# ======================
class FeatureAnnouncement(db.Model):
    """A "what's new" popup shown once per user on their role's dashboard.

    Authored in `seed/announcements.json` and synced into this table on boot
    (`helpers/announcements.py`). `id` is the ordering/high-water key compared
    against `User.last_seen_announcement_id`; `uid` is the stable author-chosen
    key the sync matches on, so re-authoring the file never duplicates a row.
    """

    __tablename__ = "feature_announcements"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = db.Column(db.String(100), unique=True, nullable=False, index=True)

    # The whole authored payload — layout, badge, title, body, image_url,
    # cta_*, secondary_label, roles. Kept as one JSON blob rather than columns
    # so a new layout's fields need no migration. English only; announcement
    # copy does not go through t() (see docs/development/translations.md).
    content: Mapped[dict[str, Any]] = db.Column(db.JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


# Re-export learning-content models so `from models import Subject` (etc.)
# keeps working unchanged across the codebase — the content hierarchy lives
# in models_learning.py, split out from the user/school/donations/CMS models
# above it. See docs/learning/content.md.
from models_learning import (
    LearningSession,
    Lesson,
    MapQuestion,
    Question,
    Subject,
    Topic,
)

# Lists the re-exports above, so linters and CodeQL read them as this module's API, not unused.
__all__ = [
    "ASSISTANT_CHANGE_STATUSES",
    "Administrator",
    "Article",
    "AssistantChange",
    "AssistantConversation",
    "AssistantMessage",
    "Attendance",
    "Donation",
    "FeatureAnnouncement",
    "Learner",
    "LearningSession",
    "Lesson",
    "MapQuestion",
    "Question",
    "School",
    "SchoolAdmin",
    "SiteContent",
    "Subject",
    "Teacher",
    "TeamMember",
    "Topic",
    "User",
    "Volunteer",
    "Worksheet",
    "WorksheetAssignment",
    "attendance_hours",
]


@event.listens_for(db.session, "after_commit")
def _drop_attendance_hours_cache(session) -> None:
    """Drops the request's attendance-hours memo."""
    # Any commit may have changed attendance, so a route that records it and
    # then renders the roster must not read the totals it just replaced.
    if has_request_context():
        g.pop("_attendance_hours", None)

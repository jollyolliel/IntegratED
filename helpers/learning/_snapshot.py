from typing import TypedDict

from sqlalchemy.orm import selectinload

from extensions import db
from helpers.learning._course_placement import (
    assessed_level,
    courses_by_scale,
    placed_course,
    starting_topic,
)
from helpers.utils import normalize_subject_bucket, tokenize_text
from models import Learner, Lesson, Subject, Teacher, Topic, Volunteer, Worksheet


class SnapshotContext(TypedDict):
    """Shared per-request lookups, built once and reused across learners."""
    first_learning_subject: str
    total_subs: int | None
    # The whole topic catalogue, keyed by id, with its Subject already loaded.
    # Resolving a learner's last completed topic one `session.get` at a time is
    # two round trips per learner on a cold session — invisible on dev SQLite,
    # a page's worth of latency on a networked Postgres.
    topics_by_id: dict[int, Topic]
    subjects_by_name: dict[str, Subject]
    # Placement scale name -> the courses banded on it.
    courses_by_scale: dict[str, list[Subject]]
    # Subject id -> its topics in learning-path order (level, then id); a course missing here has none.
    topics_by_subject: dict[int, list[Topic]]
    # The first course in the catalogue: where a learner with no placement and no progress is.
    first_course: Subject | None


class PairLearningSnapshot(TypedDict):
    """Backward-looking summary — where the learner has already been."""
    subject: str
    # Last completed topic's title, else "Foundations" — which is a state, not
    # a real Topic. Never look one up by that name.
    topic: str
    progress: int
    # The learner's level on the placement scale of a banded course, else None.
    level: int | None


class CurrentTopicProgress(TypedDict):
    """Lessons finished in the topic the learner is on now; `topic` is None when there isn't one."""
    topic: str | None
    done: int
    total: int
    progress: int


class LearnerProgressPosition(TypedDict):
    """Forward-looking counterpart to `PairLearningSnapshot`.

    `topic`/`lesson` are None once the subject has nothing incomplete left,
    and every field but `started` is None when the learner has not begun.
    """
    subject: str | None
    topic: str | None
    lesson: str | None
    started: bool


class RecommendedStart(TypedDict):
    """A placement-test result translated into a starting course and Topic.

    `subject`/`subject_id` are the recommended course; `placement_scale` is
    the `subject_levels` key the level came from — the course itself when it
    is its own placement subject.
    """
    subject: str
    subject_id: int
    placement_scale: str
    topic_id: int
    topic_title: str
    topic_level: int
    assessed_level: int


class LearnerJourney(TypedDict):
    """Everything the learner dashboard says about where the learner is, from one resolution."""
    snapshot: PairLearningSnapshot
    topic_progress: CurrentTopicProgress
    first_step: RecommendedStart | None


class TeacherPairSummary(TypedDict):
    """One matched learner/volunteer pair on a teacher dashboard."""
    learner: Learner
    volunteer: Volunteer
    subject: str
    topic: str
    progress: int
    worksheets: list[Worksheet]


# Loaded once per request and reused across learners, so summarizing a
# teacher's whole roster doesn't re-query Subject/Lesson once per pair.
def _build_snapshot_context() -> SnapshotContext:
    """Shared per-request lookups for get_pair_learning_snapshot."""
    subjects = db.session.scalars(db.select(Subject).order_by(Subject.id)).all()
    first_learning = next((s for s in subjects if not s.map_test_only), None)
    topics = db.session.scalars(
        db.select(Topic).options(selectinload(Topic.subject))
    ).all()
    topics_by_subject: dict[int, list[Topic]] = {}
    for topic in sorted(topics, key=lambda t: (t.level, t.id)):
        topics_by_subject.setdefault(topic.subject_id, []).append(topic)
    total_subs = db.session.scalar(
        db.select(db.func.count())
        .select_from(Lesson)
        .join(Topic, Lesson.topic_id == Topic.id)
        .join(Subject, Topic.subject_id == Subject.id)
        .where(Subject.map_test_only == False)
    )
    return {
        "first_learning_subject": first_learning.name if first_learning else "Learning",
        "total_subs": total_subs,
        "topics_by_id": {t.id: t for t in topics},
        "subjects_by_name": {s.name: s for s in subjects},
        "courses_by_scale": courses_by_scale(subjects),
        "topics_by_subject": topics_by_subject,
        "first_course": first_learning,
    }


def _first_placement(learner: Learner, ctx: SnapshotContext) -> tuple[str, Subject, int] | None:
    """Where a placement result puts a learner — (scale, course, level) of the first scale whose
    course has topics — the one rule every reader uses."""
    for name, raw in (learner.subject_levels or {}).items():
        level = assessed_level(raw)
        course = placed_course(ctx["subjects_by_name"].get(name), level, ctx["courses_by_scale"].get(name, []))
        if course is not None and ctx["topics_by_subject"].get(course.id):
            return name, course, level
    return None


def get_pair_learning_snapshot(learner: Learner, context: SnapshotContext | None = None) -> PairLearningSnapshot:
    """Provides a percentage-based snapshot of the partner's learning progress.

    Args:
        learner (Learner): The learner to snapshot.
        context (SnapshotContext | None): Shared lookups from `_build_snapshot_context()`.

    Returns:
        PairLearningSnapshot: Subject/topic reached, and percent of lessons done.
    """
    ctx = context or _build_snapshot_context()
    completed_topic_ids = list(learner.completed_topic_ids or [])
    last_topic = None
    if completed_topic_ids:
        last_topic = ctx["topics_by_id"].get(completed_topic_ids[-1])

    level = None
    if last_topic and last_topic.subject:
        subject_name = last_topic.subject.name
        topic_name = last_topic.title
        if last_topic.subject.placement_scale_id is not None:
            level = last_topic.level
    else:
        # Fall back to the course the placement result points at.
        placement = _first_placement(learner, ctx)
        subject_name = placement[1].name if placement else ctx["first_learning_subject"]
        topic_name = "Foundations"
        if placement and placement[1].placement_scale_id is not None:
            level = placement[2]

    completed_subs_count = len(learner.completed_lesson_ids or [])

    total_subs = ctx["total_subs"]
    progress_percent = min(int((completed_subs_count / total_subs) * 100), 100) if total_subs else 0

    return {
        "subject": subject_name,
        "topic": topic_name,
        "progress": progress_percent,
        "level": level,
    }


def _current_learning_subject(learner: Learner, ctx: SnapshotContext) -> Subject | None:
    """The Subject the learner is working through — never a map-test-only one.

    Args:
        learner (Learner): The learner to resolve a subject for.
        ctx (SnapshotContext): Shared lookups from `_build_snapshot_context()`.

    Returns:
        Subject | None: The learner's current subject, or None if none resolves.
    """
    # Same resolution order as get_pair_learning_snapshot: last completed
    # topic's subject, then the placed course, then first catalogue subject.
    # Order matters — reversed, the teacher page and volunteer dashboard can
    # name different subjects for one learner off the same rows.
    for topic_id in reversed(list(learner.completed_topic_ids or [])):
        topic = ctx["topics_by_id"].get(topic_id)
        if topic and topic.subject and not topic.subject.map_test_only:
            return topic.subject

    placement = _first_placement(learner, ctx)
    return placement[1] if placement else ctx["first_course"]


def get_learner_progress_position(learner: Learner, context: SnapshotContext | None = None) -> LearnerProgressPosition:
    """Where the learner is **now** — the first lesson they haven't finished. Forward-looking counterpart to `get_pair_learning_snapshot`.

    Args:
        learner (Learner): The learner to locate.
        context (SnapshotContext | None): Shared lookups from `_build_snapshot_context()`.

    Returns:
        LearnerProgressPosition: The first unfinished lesson and its ancestry.
    """
    ctx = context or _build_snapshot_context()
    completed_lesson_ids = set(learner.completed_lesson_ids or [])
    levels = learner.subject_levels or {}

    # "Not started" is a state, not a topic named "Foundations" (no real Topic
    # carries that title) — started=False leaves every other field None.
    if not completed_lesson_ids and not levels:
        return {"subject": None, "topic": None, "lesson": None, "started": False}

    subject, topic, lesson = _first_unfinished(learner, ctx)
    if subject is None:
        return {
            "subject": ctx["first_learning_subject"],
            "topic": None,
            "lesson": None,
            "started": True,
        }
    return {
        "subject": subject.name,
        "topic": topic.title if topic else None,
        "lesson": lesson.title if lesson else None,
        "started": True,
    }


def _first_unfinished(learner: Learner, ctx: SnapshotContext) -> tuple[Subject | None, Topic | None, Lesson | None]:
    """The learner's current subject with its first topic and lesson they haven't finished."""
    subject = _current_learning_subject(learner, ctx)
    if subject is None:
        return None, None, None
    completed_lesson_ids = set(learner.completed_lesson_ids or [])
    for topic in ctx["topics_by_subject"].get(subject.id, []):
        lesson = next(
            (
                candidate
                for candidate in sorted(topic.lessons, key=lambda item: item.id)
                if candidate.id not in completed_lesson_ids
            ),
            None,
        )
        if lesson is not None:
            return subject, topic, lesson
    return subject, None, None


def get_current_topic_progress(learner: Learner, context: SnapshotContext | None = None) -> CurrentTopicProgress:
    """How far through the topic they are working on now the learner is.

    Args:
        learner (Learner): The learner to measure.
        context (SnapshotContext | None): Shared lookups from `_build_snapshot_context()`.

    Returns:
        CurrentTopicProgress: The topic title, lessons done and total, and the percentage.
            `topic` is None when the learner hasn't started or has finished the subject.
    """
    ctx = context or _build_snapshot_context()
    completed_lesson_ids = set(learner.completed_lesson_ids or [])
    if not completed_lesson_ids and not (learner.subject_levels or {}):
        return {"topic": None, "done": 0, "total": 0, "progress": 0}
    _subject, topic, _lesson = _first_unfinished(learner, ctx)
    return _topic_progress(topic, completed_lesson_ids)


def _topic_progress(topic: Topic | None, completed_lesson_ids: set[int]) -> CurrentTopicProgress:
    if topic is None:
        return {"topic": None, "done": 0, "total": 0, "progress": 0}
    total = len(topic.lessons)
    done = sum(1 for lesson in topic.lessons if lesson.id in completed_lesson_ids)
    return {"topic": topic.title, "done": done, "total": total, "progress": int(done / total * 100) if total else 0}


def get_recommended_start(learner: Learner, context: SnapshotContext | None = None) -> RecommendedStart | None:
    """Translate a placement result into a starting course and Topic.

    The course is the one `_first_placement` picks — the same rule the snapshot uses, so the
    dashboard's subject and its recommendation always agree; the topic is the first one at the
    highest topic level at or below the assessed level, clamped into the course's range.

    Args:
        learner (Learner): The learner to recommend a starting point for.
        context (SnapshotContext | None): Shared lookups from `_build_snapshot_context()`.

    Returns:
        RecommendedStart | None: None if nothing to recommend (test skipped,
            levels empty, or no matching content).
    """
    if not learner.subject_levels:
        return None
    ctx = context or _build_snapshot_context()
    placement = _first_placement(learner, ctx)
    if placement is None:
        return None
    scale_name, course, assessed = placement
    target = starting_topic(ctx["topics_by_subject"][course.id], assessed)
    return {
        "subject": course.name,
        "subject_id": course.id,
        "placement_scale": scale_name,
        "topic_id": target.id,
        "topic_title": target.title,
        "topic_level": target.level,
        "assessed_level": assessed,
    }


#: Worksheet id -> (fingerprint, subject bucket, tokens). The catalogue is
#: small and static between edits, but every teacher page rescans it once per
#: matched pair, so tokenizing it per pair dominates those requests. Keyed on
#: the very fields that feed the tokens, so an edited worksheet re-tokenizes
#: instead of serving stale terms.
_worksheet_terms: dict[int, tuple[tuple[str | None, str | None, str | None], str, frozenset[str]]] = {}


def _worksheet_search_terms(worksheet: Worksheet) -> tuple[str, frozenset[str]]:
    """The subject bucket and keyword tokens a worksheet is scored on.

    Args:
        worksheet (Worksheet): The worksheet to describe.

    Returns:
        tuple[str, frozenset[str]]: Its normalized subject bucket and tokens.
    """
    fingerprint = (worksheet.title, worksheet.topic, worksheet.subject)
    cached = _worksheet_terms.get(worksheet.id)
    if cached is not None and cached[0] == fingerprint:
        return cached[1], cached[2]

    bucket = normalize_subject_bucket(worksheet.subject)
    tokens = frozenset(tokenize_text(f"{worksheet.title or ''} {worksheet.topic or ''}"))
    _worksheet_terms[worksheet.id] = (fingerprint, bucket, tokens)
    return bucket, tokens


def get_recommended_worksheets(subject_name: str | None, topic_name: str | None, limit: int = 4,
                               worksheet_pool: list[Worksheet] | None = None, level: int | None = None) -> list[Worksheet]:
    """Finds worksheets with the strongest topical/keyword overlap with the partner's current progress.

    Args:
        subject_name (str | None): Subject to match against.
        topic_name (str | None): Topic to match against.
        limit (int): Max worksheets to return.
        worksheet_pool (list[Worksheet] | None): Pre-fetched worksheet catalog; queried if None.
        level (int | None): The learner's placement-scale level; a worksheet at it ranks higher.

    Returns:
        list[Worksheet]: Up to `limit` worksheets, best match first.
    """
    catalog = worksheet_pool or db.session.scalars(
        db.select(Worksheet).order_by(Worksheet.subject.asc(), Worksheet.title.asc())
    ).all()
    if not catalog:
        return []

    target_subject = normalize_subject_bucket(subject_name)
    topic_tokens = set(tokenize_text(topic_name))
    scored = []

    lowered_topic = topic_name.lower() if topic_name else None

    for worksheet in catalog:
        score = 0
        worksheet_subject, worksheet_tokens = _worksheet_search_terms(worksheet)

        if worksheet_subject == target_subject:
            score += 60

        topic_overlap = len(topic_tokens & worksheet_tokens)
        score += topic_overlap * 12

        if lowered_topic and worksheet.topic and lowered_topic in worksheet.topic.lower():
            score += 18

        if level is not None and worksheet.level == level:
            score += 30

        scored.append((score, (worksheet.title or "").lower(), worksheet))

    scored.sort(key=lambda item: (-item[0], item[1]))

    recommended = []
    used_ids = set()

    for score, _, worksheet in scored:
        if score <= 0 and recommended:
            continue
        if worksheet.id in used_ids:
            continue
        recommended.append(worksheet)
        used_ids.add(worksheet.id)
        if len(recommended) == limit:
            return recommended

    for worksheet in catalog:
        if worksheet.id in used_ids:
            continue
        recommended.append(worksheet)
        if len(recommended) == limit:
            break

    return recommended


def build_teacher_pair_summaries(teacher: Teacher, recommendation_limit: int = 3) -> list[TeacherPairSummary]:
    """Context builder for teacher dashboards to summarize current activity across all pairs.

    Args:
        teacher (Teacher): The teacher whose matched pairs to summarize.
        recommendation_limit (int): Max worksheets to recommend per pair.

    Returns:
        list[TeacherPairSummary]: One entry per matched **learner** — a volunteer
            with more than one learner appears once per pair, not once total.
            (Rendering that without it reading as duplicate cards: docs/features/matching.md.)
    """
    worksheet_pool = list(db.session.scalars(
        db.select(Worksheet).order_by(Worksheet.subject.asc(), Worksheet.title.asc())
    ).all())
    snapshot_context = _build_snapshot_context()
    matched_pairs: list[TeacherPairSummary] = []
    # A roster's learners cluster on a handful of subject/topic/level positions,
    # and the recommendation depends on nothing else — so the catalogue is scanned once
    # per distinct position rather than once per learner.
    recommendations: dict[tuple[str, str, int | None], list[Worksheet]] = {}

    for learner in teacher.managed_learners:
        # Check relationship instead of redundant flag if preferred, but is_matched is still useful
        if learner.is_matched and learner.volunteer_match:
            snapshot = get_pair_learning_snapshot(learner, context=snapshot_context)
            # Pairs at the same place share one lookup — computed only on a miss.
            key = (snapshot["subject"], snapshot["topic"], snapshot["level"])
            if key not in recommendations:
                recommendations[key] = get_recommended_worksheets(
                    snapshot["subject"],
                    snapshot["topic"],
                    limit=recommendation_limit,
                    worksheet_pool=worksheet_pool,
                    level=snapshot["level"],
                )
            matched_pairs.append(
                {
                    "learner": learner,
                    "volunteer": learner.volunteer_match,
                    "subject": snapshot["subject"],
                    "topic": snapshot["topic"],
                    "progress": snapshot["progress"],
                    "worksheets": recommendations[key],
                }
            )

    matched_pairs.sort(
        key=lambda pair: (
            (pair["learner"].name or pair["learner"].username or "").lower(),
            (pair["volunteer"].name or pair["volunteer"].email or "").lower(),
        )
    )
    return matched_pairs


def get_teacher_pair_or_404(teacher: Teacher, learner_id: int) -> tuple[Learner, Volunteer]:
    """Retrieves learner/volunteer tuple ONLY if they belong to the specific teacher's group.

    Args:
        teacher (Teacher): The teacher who must own this learner.
        learner_id (int): Learner id to look up.

    Returns:
        tuple[Learner, Volunteer]: The learner and their matched volunteer.
    """
    from flask import abort
    learner = db.session.get(Learner, learner_id)
    if not learner: abort(404)
    if learner.teacher_id != teacher.id:
        abort(403)
    if not learner.is_matched or not learner.volunteer_match:
        abort(404)
    return learner, learner.volunteer_match


def learner_journey(learner: Learner) -> LearnerJourney:
    """The learner dashboard's view of where the learner is: the snapshot, the topic they are on
    and, before any lesson is finished, their first step — all from one set of lookups.

    Args:
        learner (Learner): The learner.

    Returns:
        LearnerJourney: The three, consistent with each other.
    """
    ctx = _build_snapshot_context()
    return LearnerJourney(
        snapshot=get_pair_learning_snapshot(learner, ctx),
        topic_progress=get_current_topic_progress(learner, ctx),
        first_step=None if learner.completed_lesson_ids else get_recommended_start(learner, ctx),
    )


def get_first_step(learner: Learner) -> RecommendedStart | None:
    """`get_recommended_start` until the learner finishes any lesson, then None."""
    # The map test's completion screen calls get_recommended_start directly: a deferred learner
    # who has already done lessons still gets a starting point there.
    return None if learner.completed_lesson_ids else get_recommended_start(learner)

"""`helpers/content/`: courses on a placement scale, validation, and pruning.

Every test writes its own small curriculum; none reads `data/questions.json`
except the one that checks the shipped file still validates.
"""

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from extensions import db

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _mc(text, answer="yes", **extra):
    return {"content_type": "multiple_choice", "question_prompt": "Choose", "question_text": text,
            "options": ["yes", "no"], "answer": answer, **extra}


def _lesson(title, questions=None, game_type=None):
    return {"title": title, "icon": "leaf", "description": title, "game_type": game_type,
            "questions": questions if questions is not None else [_mc(f"{title} q1")]}


def _topic(title, level, lessons=None):
    return {"title": title, "icon": "star", "description": title, "overview_markdown": f"# {title}",
            "level": level, "lessons": lessons or [_lesson(f"{title} lesson")]}


def _course(name, band, topics):
    course = {"name": name, "icon": "book", "description": name, "topics": topics}
    if band is not None:
        course["placement"] = {"scale": "English", "min_level": band[0], "max_level": band[1]}
    return course


def _placement(levels=(1, 2, 3, 4), per_level=3, scale="English"):
    return {"name": "Map Test", "questions": [
        {"subject_name": scale, "level": level, **_mc(f"{scale} placement L{level} #{n}")}
        for level in levels for n in range(per_level)
    ]}


def _curriculum():
    """Two courses splitting a four-level English scale, placement questions first on purpose."""
    return [
        _placement(),
        _course("English: First Steps", (1, 2), [_topic("Sounds", 1), _topic("Letters", 2)]),
        _course("English: Everyday", (3, 4), [_topic("Greetings", 3), _topic("Shopping", 4)]),
    ]


class _ContentFile:
    """Call with a curriculum to (re)write the file; `path` is what the importer reads."""

    def __init__(self, source, storage=None):
        self.source = source
        self.path = str(source)
        self.storage = storage

    def __call__(self, data):
        self.source.write_text(json.dumps(data), encoding="utf-8")
        if self.storage is not None:
            self.storage.write_key("content/questions.json", json.dumps(data))
        return data


@pytest.fixture
def content_file(app, tmp_path, monkeypatch):
    """A temp `questions.json` (`.path`) mirrored into the app's storage `content/` for the CLI;
    call the returned function to (re)write both."""
    from tests.support.storage import FakeBucket

    source = tmp_path / "questions.json"
    storage = FakeBucket()
    monkeypatch.setitem(app.config, "BUCKET", storage)

    return _ContentFile(source, storage)


def _subject(db_session, name):
    from models import Subject

    return db_session.scalar(select(Subject).filter_by(name=name))


def _count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


# ── courses and bands ────────────────────────────────────────────────────────


def test_courses_import_with_their_band_on_the_placement_scale(db_session, content_file):
    from helpers.content import import_questions

    content_file(_curriculum())
    import_questions(db, content_file.path)

    scale = _subject(db_session, "English")
    first, everyday = _subject(db_session, "English: First Steps"), _subject(db_session, "English: Everyday")
    assert scale.map_test_only is True
    assert (first.placement_scale_id, first.placement_min_level, first.placement_max_level) == (scale.id, 1, 2)
    assert (everyday.placement_min_level, everyday.placement_max_level) == (3, 4)
    assert first.map_test_only is False


def test_a_course_without_a_band_imports_as_before(db_session, content_file):
    from helpers.content import import_questions

    data = _curriculum() + [_course("Phonics", None, [_topic("Long A", 1), _topic("Long E", 2)])]
    content_file(data)
    import_questions(db, content_file.path)

    phonics = _subject(db_session, "Phonics")
    assert phonics.placement_scale_id is None
    assert phonics.placement_min_level is None
    assert phonics.map_test_only is False


def test_a_course_that_is_also_its_own_placement_subject_stays_on_the_learning_path(db_session, content_file):
    """The legacy shape: placement questions name a real course, and it must
    stay visible even though the Map Test entry comes first in the file."""
    from helpers.content import import_questions

    content_file([
        _placement(levels=(1, 2), scale="English Grammar"),
        _course("English Grammar", None, [_topic("Nouns", 1), _topic("Verbs", 2)]),
    ])
    import_questions(db, content_file.path)

    assert _subject(db_session, "English Grammar").map_test_only is False


def test_reimporting_refreshes_a_band_and_a_placement_answer(db_session, content_file):
    from helpers.content import import_questions
    from models import MapQuestion

    data = content_file(_curriculum())
    import_questions(db, content_file.path)

    data = copy.deepcopy(data)
    data[0]["questions"] = [
        {**q, "options": ["yes", "no", "maybe"], "answer": "maybe"} for q in data[0]["questions"]
    ]
    data[0]["questions"] += [{"subject_name": "English", "level": 5, **_mc(f"L5 #{n}")} for n in range(3)]
    data[2]["placement"]["max_level"] = 5
    content_file(data)
    import_questions(db, content_file.path)

    db_session.expire_all()
    assert _subject(db_session, "English: Everyday").placement_max_level == 5
    answers = set(db_session.scalars(select(MapQuestion.answer).where(MapQuestion.level < 5)))
    assert answers == {"maybe"}


def test_reimporting_moves_a_band(db_session, content_file):
    from helpers.content import import_questions

    data = content_file(_curriculum())
    import_questions(db, content_file.path)
    data = copy.deepcopy(data)
    data[1]["placement"]["max_level"] = 3
    data[2]["placement"]["min_level"] = 4
    data[1]["topics"].append(_topic("Words", 3))
    data[2]["topics"][0]["level"] = 4
    content_file(data)
    import_questions(db, content_file.path)

    db_session.expire_all()
    assert _subject(db_session, "English: First Steps").placement_max_level == 3
    assert _subject(db_session, "English: Everyday").placement_min_level == 4


def test_dropping_a_band_from_the_file_takes_the_course_off_the_scale(db_session, content_file):
    from helpers.content import import_questions

    data = content_file(_curriculum())
    import_questions(db, content_file.path)
    data = copy.deepcopy(data)
    data[1]["placement"]["max_level"] = 4
    del data[2]["placement"]
    content_file(data)
    import_questions(db, content_file.path)

    db_session.expire_all()
    everyday = _subject(db_session, "English: Everyday")
    assert everyday.placement_scale_id is None
    assert everyday.placement_min_level is None
    assert everyday.placement_max_level is None


# ── validation ───────────────────────────────────────────────────────────────


def _broken(mutate):
    data = _curriculum()
    mutate(data)
    return data


BROKEN = {
    "unknown content_type": (
        lambda d: d[1]["topics"][0]["lessons"][0]["questions"].append(
            {"content_type": "fill_the_gap", "question_prompt": "x", "question_text": "x"}),
        "unknown content_type 'fill_the_gap'",
    ),
    "unknown game_type": (
        lambda d: d[1]["topics"][0]["lessons"].append(_lesson("Racing", game_type="race_car")),
        "unknown game_type 'race_car'",
    ),
    "text_group inside a text_group": (
        lambda d: d[1]["topics"][0]["lessons"][0]["questions"].append(
            {"content_type": "text_group", "context_text": "a",
             "questions": [{"content_type": "text_group", "questions": []}]}),
        "text_group cannot contain another text_group",
    ),
    "multiple choice answer missing from its options": (
        lambda d: d[1]["topics"][0]["lessons"][0]["questions"].append(_mc("odd", answer="perhaps")),
        "answer 'perhaps' is not one of its options",
    ),
    "match question without pairs": (
        lambda d: d[1]["topics"][0]["lessons"].append(
            _lesson("Pairs", [{"content_type": "match", "question_prompt": "Match"}], game_type="match_up")),
        "match_pairs",
    ),
    "placement question of a type the placement test cannot show": (
        lambda d: d[0]["questions"].append(
            {"subject_name": "English", "level": 1, "content_type": "text_comprehension_drag_drop",
             "question_prompt": "x", "question_text": "x", "answer": "x"}),
        "placement questions must be multiple_choice or open_answer",
    ),
    "audio-only placement question with no sound to play": (
        lambda d: d[0]["questions"].append(
            {"subject_name": "English", "level": 1, **_mc("Find the book"), "audio_only": True}),
        "audio_only needs question_sound",
    ),
    "audio-only placement question that is not multiple choice": (
        lambda d: d[0]["questions"].append(
            {"subject_name": "English", "level": 1, "content_type": "open_answer", "question_prompt": "x",
             "question_text": "Say it", "answer": "x", "question_sound": True, "audio_only": True}),
        "audio_only only works on multiple_choice",
    ),
    "placement levels with a gap": (
        lambda d: d[0].update(questions=[q for q in d[0]["questions"] if q["level"] != 2]),
        "no placement questions at level 2",
    ),
    "bands that overlap": (
        lambda d: d[2]["placement"].update(min_level=2),
        "overlap",
    ),
    "bands that leave a level uncovered": (
        lambda d: d[2]["placement"].update(min_level=4),
        "level 3 of placement scale 'English' is in no course's band",
    ),
    "a band above the scale's highest level": (
        lambda d: d[2]["placement"].update(max_level=6),
        "placement scale 'English' only goes up to level 4",
    ),
    "a band on a scale with no placement questions": (
        lambda d: d[2]["placement"].update(scale="Maths"),
        "no placement questions for scale 'Maths'",
    ),
    "a band whose min is above its max": (
        lambda d: d[2]["placement"].update(min_level=4, max_level=3),
        "min_level 4 is above max_level 3",
    ),
    "a topic outside its course's band": (
        lambda d: d[1]["topics"].append(_topic("Too hard", 3)),
        "topic level 3 is outside the course's band 1-2",
    ),
    "a banded course's topic without an explicit level": (
        lambda d: d[1]["topics"][0].pop("level"),
        "needs an explicit level",
    ),
    "a banded course with no topics": (
        lambda d: d[2].update(topics=[]),
        "has a placement band but no topics",
    ),
    "a scale that is also a course": (
        lambda d: d.append(_course("English", None, [_topic("Odd", 1)])),
        "is a placement scale with courses on it, so it cannot also be a course",
    ),
    "a missing required key": (
        lambda d: d[1]["topics"][0].pop("overview_markdown"),
        "missing 'overview_markdown'",
    ),
    "the retired gamified flag": (
        lambda d: d[1]["topics"][0]["lessons"][0].update(gamified=True),
        "'gamified' is no longer read",
    ),
}


@pytest.mark.parametrize("case", list(BROKEN), ids=list(BROKEN))
def test_an_invalid_file_fails_the_import_loudly_and_writes_nothing(db_session, content_file, case):
    from helpers.content import ContentError, import_questions
    from models import Subject

    mutate, expected = BROKEN[case]
    content_file(_broken(mutate))

    with pytest.raises(ContentError) as raised:
        import_questions(db, content_file.path)

    assert expected in str(raised.value)
    assert _count(db_session, Subject) == 0


def test_a_validation_error_names_where_in_the_file_it_is(db_session, content_file):
    from helpers.content import ContentError, import_questions

    content_file(_broken(BROKEN["unknown content_type"][0]))

    with pytest.raises(ContentError) as raised:
        import_questions(db, content_file.path)

    assert "English: First Steps > Sounds > Sounds lesson > question 2" in str(raised.value)


def test_the_shipped_questions_file_validates():
    from helpers.content import validate_content

    data = json.loads((ROOT / "seed" / "files" / "content" / "questions.json").read_text(encoding="utf-8"))

    assert validate_content(data) == []


# ── counts ───────────────────────────────────────────────────────────────────
# `_curriculum()` holds 12 placement questions and 4 lesson questions.


def test_a_first_import_counts_every_question_it_adds(db_session, content_file):
    from helpers.content import import_questions

    content_file(_curriculum())
    result = import_questions(db, content_file.path)

    assert (result.added, result.updated) == (16, 0)


def test_a_repeat_import_counts_nothing(db_session, content_file):
    from helpers.content import import_questions

    content_file(_curriculum())
    import_questions(db, content_file.path)
    result = import_questions(db, content_file.path)

    assert (result.added, result.updated) == (0, 0)


def test_an_edited_question_counts_as_one_update(db_session, content_file):
    from helpers.content import import_questions

    data = content_file(_curriculum())
    import_questions(db, content_file.path)
    data[1]["topics"][0]["lessons"][0]["questions"][0]["options"] = ["yes", "no", "maybe"]
    data[0]["questions"][0]["answer"] = "no"
    content_file(data)
    result = import_questions(db, content_file.path)

    assert (result.added, result.updated) == (0, 2)


def test_an_edit_above_the_questions_counts_no_question(db_session, content_file):
    from helpers.content import import_questions

    data = content_file(_curriculum())
    import_questions(db, content_file.path)
    data[1]["topics"][0]["level"] = 2
    content_file(data)
    result = import_questions(db, content_file.path)

    assert (result.added, result.updated) == (0, 0)


# ── pruning ──────────────────────────────────────────────────────────────────


def _retired_curriculum():
    """`_curriculum()` minus the Everyday course, the Letters topic, one lesson's
    question and the level-4 placement questions — with First Steps now covering 1-3."""
    data = _curriculum()
    data[0]["questions"] = [q for q in data[0]["questions"] if q["level"] != 4]
    first = data[1]
    first["placement"]["max_level"] = 3
    first["topics"] = [_topic("Sounds", 1, [_lesson("Sounds lesson", [_mc("a brand new question")])])]
    return data[:2]


@pytest.fixture
def retired_world(db_session, content_file):
    """The full curriculum imported, a learner part-way through it, then the file rewritten."""
    from helpers.content import import_questions
    from models import LearningSession, Lesson, Topic
    from tests.support.factories import make_learner

    content_file(_curriculum())
    import_questions(db, content_file.path)
    lessons = {lesson.title: lesson for lesson in db_session.scalars(select(Lesson))}
    topics = {topic.title: topic for topic in db_session.scalars(select(Topic))}
    kept, retired = lessons["Sounds lesson"], lessons["Greetings lesson"]
    learner = make_learner(
        db_session,
        completed_lesson_ids=[kept.id, retired.id],
        completed_topic_ids=[topics["Sounds"].id, topics["Greetings"].id],
        subject_levels={"English": 3},
        xp=120,
    )
    for lesson in (kept, retired):
        db_session.add(LearningSession(learner_id=learner.id, session_type="answer_log", lesson_id=lesson.id,
                                       responses=[], subject_state={}, asked_ids=[], history=[]))
    db_session.add(LearningSession(learner_id=learner.id, session_type="placement",
                                   subject_state={"English": {"level": 4}}, asked_ids=[], history=[]))
    db_session.commit()
    content_file(_retired_curriculum())
    return {"learner": learner, "kept": kept, "retired": retired, "topics": topics}


def test_a_prune_plan_lists_what_is_no_longer_in_the_file(db_session, retired_world, content_file):
    from helpers.content import load_content, plan_prune

    plan = plan_prune(db, load_content(content_file.path))
    text = "\n".join(plan.lines())

    assert "English: Everyday" in text
    assert "Letters" in text
    assert "Sounds lesson q1" in text
    assert "English placement L4" in text
    assert "1 learner" in text


def test_planning_a_prune_changes_nothing(db_session, retired_world, content_file):
    from helpers.content import load_content, plan_prune
    from models import LearningSession, Subject

    plan_prune(db, load_content(content_file.path))
    db_session.commit()
    db_session.expire_all()

    assert _subject(db_session, "English: Everyday") is not None
    assert _count(db_session, Subject) == 3
    assert _count(db_session, LearningSession) == 3


def test_applying_a_prune_removes_retired_content_and_cleans_up_learners(db_session, retired_world, content_file):
    from helpers.content import import_questions
    from models import LearningSession, Lesson, MapQuestion, Question, Topic

    import_questions(db, content_file.path, prune=True)
    db_session.expire_all()
    learner = retired_world["learner"]

    assert _subject(db_session, "English: Everyday") is None
    assert {t.title for t in db_session.scalars(select(Topic))} == {"Sounds"}
    assert {lesson.title for lesson in db_session.scalars(select(Lesson))} == {"Sounds lesson"}
    assert set(db_session.scalars(select(Question.question_text))) == {"a brand new question"}
    assert set(db_session.scalars(select(MapQuestion.level))) == {1, 2, 3}
    assert _subject(db_session, "English: First Steps").placement_max_level == 3

    assert learner.completed_lesson_ids == [retired_world["kept"].id]
    assert learner.completed_topic_ids == [retired_world["topics"]["Sounds"].id]
    assert learner.xp == 120
    # Its question set changed, so the in-progress quiz on the kept lesson restarts; the
    # placement session was built from placement questions that are gone.
    assert _count(db_session, LearningSession) == 0


def test_a_learner_placed_only_on_a_removed_scale_is_asked_to_take_the_new_test(db_session, content_file):
    from helpers.content import import_questions
    from tests.support.factories import make_learner

    content_file([_placement(levels=(1, 2), scale="English Grammar"),
                  _course("English Grammar", None, [_topic("Nouns", 1)])])
    import_questions(db, content_file.path)
    learner = make_learner(db_session, subject_levels={"English Grammar": 2},
                           completed_map_test=True, map_test_deferred=False)
    content_file(_curriculum())

    import_questions(db, content_file.path, prune=True)
    db_session.expire_all()

    assert learner.subject_levels == {}
    assert learner.completed_map_test is True
    assert learner.map_test_deferred is True


def test_pruning_twice_removes_nothing_the_second_time(db_session, retired_world, content_file):
    from helpers.content import import_questions, load_content, plan_prune

    import_questions(db, content_file.path, prune=True)

    assert plan_prune(db, load_content(content_file.path)).is_empty


def test_the_cli_prune_is_a_dry_run_unless_applied(app, db_session, retired_world, content_file):
    runner = app.test_cli_runner()

    dry = runner.invoke(args=["import-questions", "--prune"])
    db_session.expire_all()

    assert dry.exit_code == 0, dry.output
    assert "Would remove" in dry.output
    assert "Dry run" in dry.output
    assert _subject(db_session, "English: Everyday") is not None

    applied = runner.invoke(args=["import-questions", "--prune", "--apply"])
    db_session.expire_all()

    assert applied.exit_code == 0, applied.output
    assert "Removed" in applied.output
    assert _subject(db_session, "English: Everyday") is None


def test_the_cli_refuses_apply_without_prune(app, db_session, content_file):
    content_file(_curriculum())

    result = app.test_cli_runner().invoke(args=["import-questions", "--apply"])

    assert result.exit_code != 0
    assert "--apply only works with --prune" in result.output


def test_the_cli_reports_validation_problems_and_exits_non_zero(app, db_session, content_file):
    content_file(_broken(BROKEN["unknown game_type"][0]))

    result = app.test_cli_runner().invoke(args=["import-questions"])

    assert result.exit_code == 1
    assert "unknown game_type 'race_car'" in result.output

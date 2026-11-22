import pytest

pytestmark = pytest.mark.unit


def _finish(learner, lesson, game_type, payload):
    """Record ``payload["correct_count"]`` first-try answers as the server would, then complete."""
    from extensions import db
    from helpers.learning import complete_lesson
    from tests.support.factories import record_answers

    claimed = payload.get("correct_count", 0) if isinstance(payload, dict) else 0
    if isinstance(claimed, int) and not isinstance(claimed, bool) and claimed > 0:
        record_answers(db.session, learner, lesson, [True] * claimed)
    return complete_lesson(learner, lesson, payload)


@pytest.fixture
def play(app, db_session, school, teacher):
    """Complete a one-question lesson of ``game_type`` with ``payload`` as a fresh learner."""
    from tests.support.factories import make_learner, make_learning_content

    def _play(game_type, payload):
        _, _, lesson, _ = make_learning_content(db_session, game_type=game_type)
        learner = make_learner(db_session, school, teacher, username=f"{game_type}-learner")
        db_session.commit()
        return _finish(learner, lesson, game_type, payload), learner, lesson

    return _play


def test_a_claimed_score_is_clamped_to_the_lessons_question_count(play):
    result, _, _ = play("rocket", {"correct_count": 9_999})

    assert result["xp_earned"] == 60  # 1 real question: 10 + the flat 50


@pytest.mark.parametrize("junk", [-5, "abc", None, [], {}, True, float("nan")])
def test_a_malformed_score_counts_as_zero_instead_of_crashing(play, junk):
    result, _, _ = play("rocket", {"correct_count": junk})

    assert result["xp_earned"] == 50


@pytest.mark.parametrize("payload", [None, [], "x", 7])
def test_a_payload_that_is_not_an_object_counts_as_empty(play, payload):
    result, _, _ = play("rocket", payload)

    assert result["xp_earned"] == 50


def test_garden_grain_bonus_is_capped_at_one_storm_per_correct_answer(play):
    from helpers.learning import GARDEN_PLOTS

    result, _, _ = play("garden_grow", {"correct_count": 1, "grains": 10_000})

    assert result["xp_earned"] == 60 + GARDEN_PLOTS * 10


def test_garden_grains_cannot_be_negative_or_junk(play):
    negative, _, _ = play("garden_grow", {"correct_count": 1, "grains": -50})
    assert negative["xp_earned"] == 60


def test_garden_grains_need_a_correct_answer_to_count(play):
    result, _, _ = play("garden_grow", {"correct_count": 0, "grains": 50})

    assert result["xp_earned"] == 50


def test_potion_golden_bonus_is_capped_at_half_the_questions_rounded_up(play):
    result, _, _ = play("potion_workshop", {"correct_count": 1, "golden_count": 500})

    assert result["xp_earned"] == 60 + 10  # one question -> at most one golden potion


def test_potion_golden_count_ignores_junk(play):
    result, _, _ = play("potion_workshop", {"correct_count": 1, "golden_count": "lots"})

    assert result["xp_earned"] == 60


def test_the_bonus_key_of_another_game_earns_nothing(play):
    result, _, _ = play("rocket", {"correct_count": 1, "grains": 100, "golden_count": 100})

    assert result["xp_earned"] == 60


def test_each_game_records_its_own_learning_session(play, db_session):
    from sqlalchemy import select

    from models import LearningSession

    _, learner, lesson = play("word_storm", {"correct_count": 1, "hearts_remaining": "junk"})

    session = db_session.scalars(select(LearningSession).filter_by(
        learner_id=learner.id, session_type="word_storm", lesson_id=lesson.id
    )).one()
    assert session.correct_count == 1
    assert session.questions_completed == 1


@pytest.mark.parametrize(("game_type", "clears_quiz_resume"), [
    ("rocket", True), ("word_storm", True), ("garden_grow", True), ("potion_workshop", True),
    ("match_up", True),
])
def test_every_game_clears_the_quiz_row_it_scored_from(
    app, db_session, school, teacher, game_type, clears_quiz_resume
):
    from sqlalchemy import select

    from models import LearningSession
    from tests.support.factories import make_learner, make_learning_content

    _, _, lesson, _ = make_learning_content(db_session, game_type=game_type)
    learner = make_learner(db_session, school, teacher)
    db_session.add(LearningSession(
        learner_id=learner.id, session_type="answer_log", lesson_id=lesson.id, responses=[],
    ))
    db_session.commit()

    _finish(learner, lesson, game_type, {"correct_count": 1})

    left = db_session.scalars(select(LearningSession).filter_by(
        learner_id=learner.id, session_type="answer_log", lesson_id=lesson.id
    )).all()
    assert (not left) is clears_quiz_resume


def test_a_claimed_score_with_no_recorded_answers_earns_nothing(app, db_session, school, teacher):
    from helpers.learning import complete_lesson
    from tests.support.factories import make_learner, make_learning_content

    _, _, lesson, _ = make_learning_content(db_session, game_type="rocket")
    learner = make_learner(db_session, school, teacher)

    result = complete_lesson(learner, lesson, {"correct_count": 1})

    assert result["xp_earned"] == 50


def test_a_question_answered_wrong_first_does_not_score(app, db_session, school, teacher):
    from helpers.learning import complete_lesson
    from tests.support.factories import (
        make_learner,
        make_learning_content,
        make_question,
        record_answers,
    )

    subject, topic, lesson, _ = make_learning_content(db_session, game_type="rocket")
    make_question(db_session, subject, topic, lesson)
    learner = make_learner(db_session, school, teacher)
    record_answers(db_session, learner, lesson, [True, False])

    result = complete_lesson(learner, lesson, {"correct_count": 2})

    assert result["xp_earned"] == 1 * 10 + 50


def test_a_game_that_does_not_exist_is_refused(play):
    with pytest.raises(ValueError, match="bogus"):
        play("bogus", {})


def test_the_completion_reports_the_score_the_server_graded(play):
    result, _, _ = play("rocket", {"correct_count": 1})

    assert (result["correct_count"], result["total_count"]) == (1, 1)


@pytest.mark.parametrize(("game_type", "result_type", "first_xp"), [
    (None, "quiz", 50), ("rocket", "rocket", 60), ("word_storm", "word_storm", 60),
    ("garden_grow", "garden_grow", 60), ("potion_workshop", "potion_workshop", 60),
])
def test_a_repeat_of_a_completion_changes_nothing(app, db_session, school, teacher, game_type, result_type, first_xp):
    """A double submit (or a retry after a lost response): the second finds the log already
    cleared, must not zero the record, and reports the score the first one earned."""
    from sqlalchemy import select

    from helpers.learning import complete_lesson
    from models import LearningSession
    from tests.support.factories import (
        make_learner,
        make_learning_content,
        record_answers,
    )

    _, _, lesson, _ = make_learning_content(db_session, game_type=game_type)
    learner = make_learner(db_session, school, teacher)
    record_answers(db_session, learner, lesson, [True])

    first = complete_lesson(learner, lesson, {})
    second = complete_lesson(learner, lesson, {})

    record = db_session.scalars(select(LearningSession).filter_by(
        learner_id=learner.id, session_type=result_type, lesson_id=lesson.id)).one()
    assert first["xp_earned"] == first_xp
    assert second["already_completed"] is True and second["xp_earned"] == 0
    assert record.correct_count == 1
    assert (second["correct_count"], second["total_count"]) == (1, 1)


def test_a_choice_game_deals_only_questions_with_options(app, db_session):
    from helpers.learning import deal
    from tests.support.factories import make_learning_content, make_question

    subject, topic, lesson, with_options = make_learning_content(db_session, game_type="rocket")
    make_question(db_session, subject, topic, lesson, content_type="open_answer", options=None,
                  question_text="Type it")

    assert [unit.question.id for unit in deal(lesson)] == [with_options.id]


def test_one_right_match_up_pair_does_not_mark_the_whole_question(app, db_session, school, teacher):
    from helpers.learning import answer_log, check_match_pair, deal
    from tests.support.factories import (
        make_learner,
        make_learning_content,
        make_question,
    )

    subject, topic, lesson, first = make_learning_content(db_session, game_type="match_up")
    make_question(db_session, subject, topic, lesson, content_type="match", question_text="pairs",
                  match_pairs=[{"left": "cat", "right": "gata"}, {"left": "dog", "right": "skylos"}])
    learner = make_learner(db_session, school, teacher)

    assert len(deal(lesson)) == 2
    assert check_match_pair(learner, lesson, "cat", "gata") is True

    log = answer_log.find(learner.id, lesson.id)
    assert answer_log.first_try_correct(log, {u.key for u in deal(lesson)}) == 1
    assert answer_log.question_unit(first.id) not in answer_log.correct_units(log)


# ── Golden potion XP boost ────────────────────────────────────────────────────────────────────
# A Potion Workshop lesson finished for the first time with a golden potion stores one boost;
# the learner's next first-time lesson completion (any type) earns double XP and spends it.


@pytest.fixture
def lesson_for(db_session):
    from tests.support.factories import make_learning_content

    def _lesson(game_type=None):
        return make_learning_content(db_session, game_type=game_type)[2]

    return _lesson


@pytest.fixture
def learner(db_session, school, teacher):
    from tests.support.factories import make_learner

    made = make_learner(db_session, school, teacher)
    db_session.commit()
    return made


def test_a_golden_potion_stores_a_boost_that_doubles_the_next_lessons_xp(learner, lesson_for):

    potion = _finish(learner, lesson_for("potion_workshop"), "potion_workshop",
                           {"correct_count": 1, "golden_count": 1})
    assert potion["boost_earned"] is True
    assert potion["xp_boosted"] is False
    assert learner.xp_boost_pending is True

    rocket = _finish(learner, lesson_for("rocket"), "rocket", {"correct_count": 1})

    assert rocket["xp_boosted"] is True
    assert rocket["xp_earned"] == 2 * 60
    assert learner.xp_boost_pending is False


def test_the_boost_is_spent_once(learner, lesson_for):

    learner.xp_boost_pending = True
    _finish(learner, lesson_for("rocket"), "rocket", {"correct_count": 1})
    second = _finish(learner, lesson_for("rocket"), "rocket", {"correct_count": 1})

    assert second["xp_boosted"] is False
    assert second["xp_earned"] == 60


def test_a_potion_lesson_with_no_golden_potion_stores_no_boost(learner, lesson_for):

    result = _finish(learner, lesson_for("potion_workshop"), "potion_workshop",
                           {"correct_count": 1, "golden_count": 0})

    assert result["boost_earned"] is False
    assert learner.xp_boost_pending is False


def test_a_golden_potion_claimed_with_no_correct_answer_stores_no_boost(learner, lesson_for):

    result = _finish(learner, lesson_for("potion_workshop"), "potion_workshop",
                           {"correct_count": 0, "golden_count": 1})

    assert result["boost_earned"] is False
    assert learner.xp_boost_pending is False


def test_replaying_a_potion_lesson_stores_no_boost(learner, lesson_for):

    lesson = lesson_for("potion_workshop")
    _finish(learner, lesson, "potion_workshop", {"correct_count": 1, "golden_count": 0})
    replay = _finish(learner, lesson, "potion_workshop", {"correct_count": 1, "golden_count": 1})

    assert replay["boost_earned"] is False
    assert learner.xp_boost_pending is False


def test_a_replay_that_earns_no_xp_keeps_the_boost_for_later(learner, lesson_for):

    lesson = lesson_for("rocket")
    _finish(learner, lesson, "rocket", {"correct_count": 1})
    learner.xp_boost_pending = True

    replay = _finish(learner, lesson, "rocket", {"correct_count": 1})

    assert replay["xp_earned"] == 0
    assert replay["xp_boosted"] is False
    assert learner.xp_boost_pending is True


def test_a_quiz_lesson_spends_the_boost_too(learner, lesson_for):
    from helpers.learning import record_lesson_completion

    learner.xp_boost_pending = True
    done = record_lesson_completion(learner, lesson_for(), xp=50, correct_count=1, total_count=1)

    assert done.payload["xp_boosted"] is True
    assert done.payload["xp_earned"] == 100
    assert learner.xp_boost_pending is False


def test_a_boosted_potion_lesson_spends_the_old_boost_and_stores_a_new_one(learner, lesson_for):

    learner.xp_boost_pending = True
    result = _finish(learner, lesson_for("potion_workshop"), "potion_workshop",
                           {"correct_count": 1, "golden_count": 1})

    assert result["xp_boosted"] is True
    assert result["xp_earned"] == 2 * (60 + 10)
    assert result["boost_earned"] is True
    assert learner.xp_boost_pending is True

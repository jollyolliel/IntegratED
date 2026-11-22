"""The placement staircase (helpers/learning/_placement.py) as a pure state machine.

`_run` drives one scale the way the route does — ask at the state's target level,
apply the answer — against a learner described by `knows(level) -> bool`, so a
whole test can be played out without a database.
"""

import pytest

from helpers.learning import apply_map_answer, new_scale_state, placement_estimate

pytestmark = pytest.mark.unit

MAX_LEVEL = 10


def _run(knows, *, start=2, max_level=MAX_LEVEL, min_answers=10, cap=20):
    state = new_scale_state(start, min_answers)
    asked = []
    while not state["settled"] and len(asked) < cap:
        level = state["level"]
        asked.append(level)
        apply_map_answer(state, level, knows(level), max_level)
    return state, asked


def test_a_learner_who_knows_nothing_is_asked_the_minimum_and_lands_on_the_floor():
    state, asked = _run(lambda level: False)

    assert len(asked) == 10
    assert state["settled_level"] == 1


def test_a_learner_who_knows_everything_climbs_to_the_ceiling_within_the_cap():
    state, asked = _run(lambda level: True)

    assert 10 <= len(asked) <= 20
    assert state["settled_level"] == MAX_LEVEL


@pytest.mark.parametrize("true_level", [1, 2, 3, 5, 7, 9])
def test_a_consistent_learner_settles_at_their_level_after_ten_to_twenty_questions(true_level):
    state, asked = _run(lambda level: level <= true_level)

    assert 10 <= len(asked) <= 20
    assert state["settled_level"] == true_level


def test_two_consecutive_correct_answers_climb_one_level():
    state = new_scale_state(1, 10)

    apply_map_answer(state, 1, True, 4)
    assert state["level"] == 1
    apply_map_answer(state, 1, True, 4)

    assert state["level"] == 2
    assert state["settled"] is False


def test_one_wrong_answer_at_the_floor_does_not_settle():
    state = new_scale_state(1, 0)

    apply_map_answer(state, 1, False, 4)

    assert state["settled"] is False
    assert state["level"] == 1


def test_a_second_miss_at_the_floor_settles_once_the_minimum_is_met():
    state = new_scale_state(1, 0)

    apply_map_answer(state, 1, False, 4)
    apply_map_answer(state, 1, False, 4)

    assert state["settled"] is True
    assert state["settled_level"] == 1


def test_before_the_minimum_a_bracket_keeps_probing_instead_of_settling():
    state = new_scale_state(2, 10)
    apply_map_answer(state, 2, True, 4)
    apply_map_answer(state, 2, True, 4)   # climbs to 3
    apply_map_answer(state, 3, False, 4)  # bracketed: passed 2, failed 3

    assert state["settled"] is False
    assert state["level"] == 2


def test_after_a_bracket_a_correct_answer_retests_the_failed_level_above():
    state = new_scale_state(2, 10)
    for level, correct in [(2, True), (2, True), (3, False), (2, True)]:
        apply_map_answer(state, level, correct, 4)

    assert state["settled"] is False
    assert state["level"] == 3


def test_confirming_a_failed_level_lets_the_estimate_climb_past_it():
    state = new_scale_state(2, 10)
    for level, correct in [(2, True), (2, True), (3, False), (2, True), (3, True), (3, True)]:
        apply_map_answer(state, level, correct, 4)

    assert state["level"] == 4
    assert placement_estimate(state) == 3


def test_a_lucky_guess_at_a_failed_level_does_not_raise_the_estimate():
    state = new_scale_state(2, 10)
    for level, correct in [(2, True), (2, True), (3, False), (2, True), (3, True)]:
        apply_map_answer(state, level, correct, 4)

    assert placement_estimate(state) == 2


def test_a_wrong_answer_cancels_an_unconfirmed_pass_at_that_level():
    state = new_scale_state(2, 10)
    apply_map_answer(state, 2, True, 4)
    apply_map_answer(state, 2, False, 4)

    assert placement_estimate(state) == 1


def test_the_estimate_of_a_learner_who_got_nothing_right_is_the_floor():
    state = new_scale_state(2, 10)
    apply_map_answer(state, 2, False, 4)

    assert placement_estimate(state) == 1


def test_a_settled_scale_reports_its_settled_level():
    state = new_scale_state(1, 0)
    apply_map_answer(state, 1, False, 4)
    apply_map_answer(state, 1, False, 4)

    assert placement_estimate(state) == 1


def _placement_session(scale_name, state, asked_ids=()):
    from types import SimpleNamespace

    return SimpleNamespace(subject_state={scale_name: state}, asked_ids=list(asked_ids))


def test_a_level_that_ran_dry_borrows_a_question_from_the_level_next_to_it(db_session):
    from helpers.learning import next_placement_question_for_subject
    from tests.support.factories import make_map_question, make_subject

    scale = make_subject(db_session, name="English", map_test_only=True)
    asked = make_map_question(db_session, scale, level=1, question_text="floor")
    neighbour = make_map_question(db_session, scale, level=2, question_text="above")
    state = new_scale_state(1, 10)
    session = _placement_session("English", state, [asked.id])

    question = next_placement_question_for_subject(session, "English", scale.id, 2)

    assert question is not None and question.id == neighbour.id
    assert state["settled"] is False


def test_a_scale_with_nothing_left_to_ask_settles_at_its_estimate_instead_of_looping(db_session):
    from helpers.learning import next_placement_question_for_subject
    from tests.support.factories import make_map_question, make_subject

    scale = make_subject(db_session, name="English", map_test_only=True)
    only = make_map_question(db_session, scale, level=1)
    state = new_scale_state(1, 10)
    apply_map_answer(state, 1, True, 3)
    session = _placement_session("English", state, [only.id])

    question = next_placement_question_for_subject(session, "English", scale.id, 3)

    assert question is None
    assert state["settled"] is True
    assert state["settled_level"] == 1



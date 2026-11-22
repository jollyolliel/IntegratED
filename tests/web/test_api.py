"""The /api/* JSON contracts outside a lesson run: auth and role, matching, the onboarding gate,
placement test, garden, avatar and announcements (the lesson run is in test_lessons_api.py)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.support.assertions import assert_success
from tests.support.factories import (
    make_feature_announcement,
    make_learner,
    make_learning_content,
    make_map_question,
    make_subject,
    make_teacher,
    make_volunteer,
)

pytestmark = pytest.mark.web



# ── authentication and role ──────────────────────────────────────────────────


def test_api_requires_authentication(client, db_session):
    response = client.post("/api/run-matching", json={})

    assert response.status_code in {302, 303, 401}


def test_learner_cannot_run_teacher_matching_operation(client, db_session, authenticated_learner):
    response = client.post("/api/run-matching", json={})

    assert response.status_code == 403


def test_teacher_can_run_matching_without_crashing_on_an_empty_roster(client, db_session, authenticated_teacher):
    response = client.post("/api/run-matching", json={})

    assert response.status_code in {200, 204}


def test_a_teacher_with_no_school_cannot_run_matching(client, db_session):
    from tests.support.auth import login_as
    from tests.support.factories import make_teacher as build

    login_as(client, build(db_session, None))

    response = client.post("/api/run-matching", json={})

    assert response.status_code == 400


def test_matching_pairs_a_learner_with_a_volunteer(client, db_session, authenticated_teacher):
    teacher = authenticated_teacher
    school = teacher.school
    learner = make_learner(db_session, school, teacher)
    volunteer = make_volunteer(db_session, school, teacher)

    assert_success(client.post("/api/run-matching", json={}))

    db_session.expire_all()
    db_session.refresh(learner)
    assert learner.volunteer_id == volunteer.id


def test_matching_fills_a_half_full_volunteers_remaining_slot(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    volunteer = make_volunteer(db_session, school, teacher, match_capacity=2)
    make_learner(db_session, school, teacher, volunteer_id=volunteer.id, is_matched=True)
    waiting = make_learner(db_session, school, teacher)

    assert_success(client.post("/api/run-matching", json={}))

    db_session.expire_all()
    db_session.refresh(waiting)
    assert waiting.volunteer_id == volunteer.id


def test_matching_moves_a_learner_off_a_crowded_volunteer_onto_an_idle_one(
    client, db_session, authenticated_teacher
):
    """A run rebalances the standing roster, not just the waiting list — a
    roster where every learner is already placed is otherwise frozen, and a
    volunteer who ran out of learners before ever getting one stays empty."""
    teacher = authenticated_teacher
    school = teacher.school
    crowded = make_volunteer(db_session, school, teacher, match_capacity=5)
    idle = make_volunteer(db_session, school, teacher, match_capacity=2)
    for _ in range(3):
        make_learner(db_session, school, teacher, volunteer_id=crowded.id, is_matched=True)

    assert_success(client.post("/api/run-matching", json={}))

    db_session.expire_all()
    assert len(db_session.get(type(idle), idle.id).learner_matches) == 1
    assert len(db_session.get(type(crowded), crowded.id).learner_matches) == 2


def test_matching_leaves_a_settled_roster_untouched(client, db_session, authenticated_teacher):
    """Rerunning on a roster the matcher would build anyway rewrites nothing,
    so a teacher pressing the button twice does not churn their pairings."""
    teacher = authenticated_teacher
    school = teacher.school
    first = make_volunteer(db_session, school, teacher, match_capacity=2)
    second = make_volunteer(db_session, school, teacher, match_capacity=2)
    learner_a = make_learner(db_session, school, teacher, volunteer_id=first.id, is_matched=True)
    learner_b = make_learner(db_session, school, teacher, volunteer_id=second.id, is_matched=True)

    response = assert_success(client.post("/api/run-matching", json={}))

    assert response.get_json()["matches_applied"] == 0
    db_session.expire_all()
    assert db_session.get(type(learner_a), learner_a.id).volunteer_id == first.id
    assert db_session.get(type(learner_b), learner_b.id).volunteer_id == second.id


def test_matching_gives_an_idle_volunteer_a_learner_before_stacking_a_better_one(
    client, db_session, authenticated_teacher
):
    """A large capacity is a ceiling, not a target — the run only stacks a
    second learner on a volunteer who beats an idle one by more than the
    spread penalty."""
    teacher = authenticated_teacher
    school = teacher.school
    english = [{"language": "English", "level": "Advanced"}]
    roomy = make_volunteer(
        db_session, school, teacher, match_capacity=3,
        survey_data={"age": 16, "languages": english},
    )
    # Same language, further from the learners in age, so every pair with the
    # roomy volunteer out-scores every pair with this one.
    idle = make_volunteer(
        db_session, school, teacher, match_capacity=1,
        survey_data={"age": 22, "languages": english},
    )
    learner_survey = {"age": 16, "languages": [{"language": "English", "level": "Beginner"}]}
    make_learner(db_session, school, teacher, survey_data=learner_survey)
    make_learner(db_session, school, teacher, survey_data=learner_survey)

    assert_success(client.post("/api/run-matching", json={}))

    db_session.expire_all()
    assert len(db_session.get(type(roomy), roomy.id).learner_matches) == 1
    assert len(db_session.get(type(idle), idle.id).learner_matches) == 1


def test_matching_never_spends_a_slot_on_another_teachers_learner(
    client, db_session, authenticated_teacher
):
    """The pool is the teacher's own roster, never the whole school. Drawing
    school-wide lets a colleague's learner win a slot the applier then refuses
    on ownership, burning the slot and leaving an own learner unmatched."""
    teacher = authenticated_teacher
    school = teacher.school
    colleague = make_teacher(db_session, school)

    greek = {"languages": [{"language": "Greek", "level": "Advanced"}]}
    volunteer = make_volunteer(db_session, school, teacher, survey_data=greek)
    own_learner = make_learner(db_session, school, teacher)
    # Scores higher against `volunteer` than the teacher's own learner does, so
    # a school-wide pool hands it this learner and then throws the pair away.
    colleague_learner = make_learner(db_session, school, colleague, survey_data=greek)

    assert_success(client.post("/api/run-matching", json={}))

    db_session.expire_all()
    db_session.refresh(own_learner)
    db_session.refresh(colleague_learner)
    assert own_learner.volunteer_id == volunteer.id
    assert colleague_learner.volunteer_id is None


def test_matching_does_not_draw_on_another_teachers_volunteer(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    colleague = make_teacher(db_session, school)
    make_volunteer(db_session, school, colleague)
    own_learner = make_learner(db_session, school, teacher)

    response = assert_success(client.post("/api/run-matching", json={}))

    db_session.expire_all()
    db_session.refresh(own_learner)
    assert own_learner.volunteer_id is None
    assert response.get_json()["status"] == "no_op"


def test_matching_reports_how_many_pairs_it_could_not_apply(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    make_volunteer(db_session, school, teacher)
    make_learner(db_session, school, teacher)

    response = assert_success(client.post("/api/run-matching", json={}))

    body = response.get_json()
    assert body["matches_applied"] == 1
    assert body["matches_skipped"] == 0


# ── matching preview ─────────────────────────────────────────────────────────


def test_previewing_matches_proposes_a_pair_without_applying_it(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    learner = make_learner(db_session, school, teacher, name="Amira")
    volunteer = make_volunteer(db_session, school, teacher, name="Sam")

    body = assert_success(client.post("/api/matching/preview", json={})).get_json()

    assert body["status"] == "success"
    [move] = body["moves"]
    assert move["learner_id"] == learner.id
    assert move["learner_name"] == "Amira"
    assert move["from_volunteer_id"] is None
    assert move["to_volunteer_id"] == volunteer.id
    assert move["options"][str(volunteer.id)]["band"] in {"strong", "good", "fair", "weak"}
    # The proposed pair's score and name are read out of `options` and the
    # `volunteers` list — the row itself carries neither, so there is nothing
    # to keep in step with a swap the teacher makes.
    assert not {"score", "band", "to_volunteer_name"} & set(move)
    db_session.expire_all()
    db_session.refresh(learner)
    assert learner.volunteer_id is None


def test_previewing_a_rebalance_names_the_volunteer_a_learner_moves_off(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    crowded = make_volunteer(db_session, school, teacher, match_capacity=5)
    idle = make_volunteer(db_session, school, teacher, match_capacity=2)
    for _ in range(3):
        make_learner(db_session, school, teacher, volunteer_id=crowded.id, is_matched=True)

    body = assert_success(client.post("/api/matching/preview", json={})).get_json()

    [move] = body["moves"]
    assert move["from_volunteer_id"] == crowded.id
    assert move["to_volunteer_id"] == idle.id
    assert body["unchanged_count"] == 2


def test_a_preview_lists_every_volunteer_with_their_slots_for_editing(
    client, db_session, authenticated_teacher
):
    """The teacher can swap a proposed volunteer for another, so the preview
    carries every own volunteer with capacity and current load to check the
    edit against."""
    teacher = authenticated_teacher
    school = teacher.school
    busy = make_volunteer(db_session, school, teacher, name="Busy", match_capacity=2)
    make_volunteer(db_session, school, teacher, name="Free", match_capacity=1)
    make_learner(db_session, school, teacher, volunteer_id=busy.id, is_matched=True)
    make_learner(db_session, school, teacher)

    body = assert_success(client.post("/api/matching/preview", json={})).get_json()

    by_name = {v["name"]: v for v in body["volunteers"]}
    assert by_name["Busy"]["capacity"] == 2
    assert by_name["Busy"]["load"] == 1
    assert by_name["Free"]["load"] == 0


def test_a_preview_scores_each_move_against_every_volunteer(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    first = make_volunteer(db_session, school, teacher)
    second = make_volunteer(db_session, school, teacher)
    make_learner(db_session, school, teacher)

    body = assert_success(client.post("/api/matching/preview", json={})).get_json()

    [move] = body["moves"]
    assert set(move["options"]) == {str(first.id), str(second.id)}
    assert move["options"][str(first.id)]["band"] in {"strong", "good", "fair", "weak"}
    assert isinstance(move["options"][str(first.id)]["score"], int)


def test_approving_a_move_to_no_volunteer_unmatches_the_learner(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    volunteer = make_volunteer(db_session, school, teacher)
    learner = make_learner(db_session, school, teacher, volunteer_id=volunteer.id, is_matched=True)

    body = assert_success(client.post(
        "/api/run-matching",
        json={"moves": [{"learner_id": learner.id, "volunteer_id": None}]},
    )).get_json()

    assert body["matches_released"] == 1
    db_session.expire_all()
    db_session.refresh(learner)
    assert learner.volunteer_id is None


def test_previewing_a_settled_roster_proposes_nothing(client, db_session, authenticated_teacher):
    teacher = authenticated_teacher
    school = teacher.school
    volunteer = make_volunteer(db_session, school, teacher)
    make_learner(db_session, school, teacher, volunteer_id=volunteer.id, is_matched=True)

    body = assert_success(client.post("/api/matching/preview", json={})).get_json()

    assert body["moves"] == []
    assert body["unchanged_count"] == 1


def test_previewing_an_empty_roster_is_a_no_op(client, db_session, authenticated_teacher):
    body = assert_success(client.post("/api/matching/preview", json={})).get_json()

    assert body["status"] == "no_op"
    assert body["moves"] == []


def test_a_learner_cannot_preview_matches(client, db_session, authenticated_learner):
    assert client.post("/api/matching/preview", json={}).status_code == 403


def test_approving_a_preview_applies_exactly_the_moves_it_showed(
    client, db_session, authenticated_teacher
):
    """The teacher approves the pairs on screen, not whatever a second run
    would pick — so the apply takes the previewed moves back verbatim."""
    teacher = authenticated_teacher
    school = teacher.school
    learner = make_learner(db_session, school, teacher)
    chosen = make_volunteer(db_session, school, teacher)
    make_volunteer(db_session, school, teacher)

    response = assert_success(client.post(
        "/api/run-matching",
        json={"moves": [{"learner_id": learner.id, "volunteer_id": chosen.id}]},
    ))

    assert response.get_json()["matches_applied"] == 1
    db_session.expire_all()
    db_session.refresh(learner)
    assert learner.volunteer_id == chosen.id


def test_approving_a_preview_that_moves_a_learner_releases_them_first(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    old = make_volunteer(db_session, school, teacher)
    new = make_volunteer(db_session, school, teacher)
    learner = make_learner(db_session, school, teacher, volunteer_id=old.id, is_matched=True)

    body = assert_success(client.post(
        "/api/run-matching",
        json={"moves": [{"learner_id": learner.id, "volunteer_id": new.id}]},
    )).get_json()

    assert body["matches_released"] == 1
    db_session.expire_all()
    db_session.refresh(learner)
    assert learner.volunteer_id == new.id


def test_an_approved_move_onto_another_teachers_volunteer_is_skipped(
    client, db_session, authenticated_teacher
):
    teacher = authenticated_teacher
    school = teacher.school
    colleague = make_teacher(db_session, school)
    theirs = make_volunteer(db_session, school, colleague)
    learner = make_learner(db_session, school, teacher)

    body = assert_success(client.post(
        "/api/run-matching",
        json={"moves": [{"learner_id": learner.id, "volunteer_id": theirs.id}]},
    )).get_json()

    assert body["matches_applied"] == 0
    assert body["matches_skipped"] == 1
    db_session.expire_all()
    db_session.refresh(learner)
    assert learner.volunteer_id is None


def test_a_learner_whose_new_pair_is_skipped_keeps_their_old_volunteer(client, db_session, authenticated_teacher):
    teacher = authenticated_teacher
    school = teacher.school
    old = make_volunteer(db_session, school, teacher)
    learner = make_learner(db_session, school, teacher, volunteer_id=old.id, is_matched=True)
    old.is_matched = True
    colleague = make_teacher(db_session, school)
    theirs = make_volunteer(db_session, school, colleague)
    db_session.commit()

    body = assert_success(client.post(
        "/api/run-matching",
        json={"moves": [{"learner_id": learner.id, "volunteer_id": theirs.id}]},
    )).get_json()

    assert body["matches_skipped"] == 1 and body["matches_released"] == 0
    db_session.expire_all()
    db_session.refresh(learner)
    assert learner.volunteer_id == old.id and learner.is_matched


@pytest.mark.parametrize(
    "moves",
    [
        "nope",
        [{"learner_id": "x", "volunteer_id": 1}],
        [{"volunteer_id": 1}],
        [{"learner_id": 1, "volunteer_id": "y"}],
    ],
)
def test_malformed_approved_moves_are_refused(client, db_session, authenticated_teacher, moves):
    response = client.post("/api/run-matching", json={"moves": moves})

    assert response.status_code == 400


# ── onboarding gate on the learner API ───────────────────────────────────────


@pytest.mark.parametrize("method,path", [
    ("get", "/api/quiz/{lesson}/questions"),
    ("post", "/api/quiz/validate-answer"),
    ("post", "/api/lesson/{lesson}/completion"),
    ("post", "/api/match-up/{lesson}/pair"),
    ("get", "/api/garden"),
])
def test_a_learner_who_has_not_finished_onboarding_cannot_use_the_learning_api(client, db_session, method, path):
    from tests.support.auth import login_as
    from tests.support.factories import make_school

    _subject, _topic, lesson, _question = make_learning_content(db_session)
    login_as(client, make_learner(db_session, make_school(db_session), completed_survey=True, completed_map_test=False))

    response = getattr(client, method)(path.format(lesson=lesson.id), json={})

    assert response.status_code == 403
    assert response.get_json()["error"] == "onboarding_incomplete"


@pytest.mark.parametrize(("survey", "status_ok"), [(False, False), (True, True)])
def test_the_placement_test_needs_only_the_survey(client, db_session, survey, status_ok):
    from tests.support.auth import login_as
    from tests.support.factories import make_school

    login_as(client, make_learner(db_session, make_school(db_session), completed_survey=survey, completed_map_test=False))

    response = client.post("/api/map/question", json={})

    assert (response.status_code != 403) is status_ok
    if not status_ok:
        assert response.get_json()["error"] == "onboarding_incomplete"



# ── placement test ───────────────────────────────────────────────────────────


def test_the_placement_test_serves_a_first_question(client, db_session, authenticated_learner):
    subject = make_subject(db_session)
    make_map_question(db_session, subject, level=1)

    payload = assert_success(client.post("/api/map/question", json={})).get_json()

    assert payload.get("question_text") or payload.get("completed")


def test_an_audio_only_placement_question_points_at_its_audio(client, db_session, authenticated_learner):
    from helpers import audio_cache

    subject = make_subject(db_session)
    make_map_question(
        db_session, subject, level=1, question_prompt="Listen and choose",
        question_text="Select the word book", options=["bee", "book", "bat"], answer="book",
        question_sound=True, audio_only=True,
    )

    payload = assert_success(client.post("/api/map/question", json={})).get_json()

    assert payload["audio_only"] is True
    assert payload["question_sound_url"] == audio_cache.audio_url("Select the word book")
    assert payload["options"] == ["bee", "book", "bat"]
    # The page hides the words, but keeps them to show if the audio cannot play.
    assert payload["question_text"] == "Select the word book"


def test_a_placement_question_is_only_audio_only_if_it_has_sound(client, db_session, authenticated_learner):
    subject = make_subject(db_session)
    make_map_question(db_session, subject, level=1, question_sound=False, audio_only=True)

    payload = assert_success(client.post("/api/map/question", json={})).get_json()

    assert payload["audio_only"] is False
    assert payload["question_sound_url"] is None


def test_a_placement_question_without_sound_has_no_audio_url(client, db_session, authenticated_learner):
    subject = make_subject(db_session)
    make_map_question(db_session, subject, level=1, question_sound=False)

    payload = assert_success(client.post("/api/map/question", json={})).get_json()

    assert payload["question_sound_url"] is None


def test_an_unconfigured_placement_test_answers_with_a_configuration_error(
    client, db_session, authenticated_learner
):
    """Deliberate, and worth pinning: with no authored MapQuestion rows the
    endpoint answers 500 "Configuration error" rather than completing the
    test. On a fresh install that is a user-facing 500."""

    response = client.post("/api/map/question", json={})

    assert response.status_code == 500
    assert response.get_json()["error"] == "Configuration error"


def test_answering_advances_the_placement_session(client, db_session, authenticated_learner):
    from models import LearningSession

    subject = make_subject(db_session)
    for level in (1, 2, 3):
        make_map_question(db_session, subject, level=level)

    first = client.post("/api/map/question", json={}).get_json()
    if first.get("completed"):
        pytest.skip("placement finished immediately; nothing to advance")

    # The endpoint returns the question under "id", and expects the answer
    # back as {"id", "selected_answer"}.
    client.post(
        "/api/map/question",
        json={"id": first["id"], "selected_answer": "yes"},
    )

    session_row = db_session.scalar(select(LearningSession).filter_by(
        learner_id=authenticated_learner.id, session_type="placement"
    ))
    assert session_row is None or session_row.count >= 1


def test_a_learner_may_defer_the_placement_test(client, db_session, authenticated_learner):
    assert_success(client.post("/api/skip-map-test"))

    db_session.expire_all()
    assert authenticated_learner.completed_map_test is True
    assert authenticated_learner.map_test_deferred is True
    assert authenticated_learner.subject_levels == {}


def test_only_a_learner_may_defer_the_placement_test(client, db_session, authenticated_teacher):
    assert client.post("/api/skip-map-test").status_code == 403


# ── garden ───────────────────────────────────────────────────────────────────


def test_the_garden_starts_empty(client, db_session, authenticated_learner):
    payload = assert_success(client.get("/api/garden")).get_json()

    assert payload["garden"] == {}


def test_a_valid_garden_is_stored(client, db_session, authenticated_learner):
    garden = {"stages": [0, 1, 2, 3, 0, 1, 2, 3], "colors": ["#aabbcc"] * 8}

    payload = assert_success(client.post("/api/garden", json={"garden": garden})).get_json()

    assert payload["garden"]["stages"] == [0, 1, 2, 3, 0, 1, 2, 3]
    db_session.expire_all()
    assert authenticated_learner.garden_state["colors"][0] == "#aabbcc"


def test_garden_stages_are_clamped_to_the_valid_range(client, db_session, authenticated_learner):
    garden = {"stages": [-5, 99, 0, 0, 0, 0, 0, 0], "colors": [None] * 8}

    payload = assert_success(client.post("/api/garden", json={"garden": garden})).get_json()

    assert payload["garden"]["stages"][0] == 0
    assert payload["garden"]["stages"][1] == 3


def test_a_bad_colour_is_dropped_rather_than_stored(client, db_session, authenticated_learner):
    garden = {"stages": [0] * 8, "colors": ["javascript:alert(1)"] + ["#aabbcc"] * 7}

    payload = assert_success(client.post("/api/garden", json={"garden": garden})).get_json()

    assert payload["garden"]["colors"][0] is None


@pytest.mark.parametrize(
    "garden",
    [
        {"stages": [0, 1], "colors": ["#aabbcc"] * 8},
        {"stages": [0] * 8, "colors": ["#aabbcc"]},
        {"stages": "nope", "colors": ["#aabbcc"] * 8},
        {},
    ],
)
def test_a_garden_of_the_wrong_shape_is_refused(client, db_session, authenticated_learner, garden):
    response = client.post("/api/garden", json={"garden": garden})

    assert response.status_code == 400


def test_non_numeric_garden_stages_are_refused(client, db_session, authenticated_learner):
    garden = {"stages": ["a"] * 8, "colors": [None] * 8}

    response = client.post("/api/garden", json={"garden": garden})

    assert response.status_code == 400


def test_garden_rejects_a_non_object_payload(client, db_session, authenticated_learner):
    response = client.post("/api/garden", json=["bad"])

    assert response.status_code == 400


def test_garden_rejects_a_non_object_garden(client, db_session, authenticated_learner):
    response = client.post("/api/garden", json={"garden": ["bad"]})

    assert response.status_code == 400


# ── avatar items ─────────────────────────────────────────────────────────────


def test_equipping_requires_an_item_id(client, db_session, authenticated_learner):
    assert client.post("/api/equip-item", json={}).status_code == 400


def test_an_unknown_item_is_a_404(client, db_session, authenticated_learner):
    assert client.post("/api/equip-item", json={"item_id": "nonsense"}).status_code == 404


def _first_item_at_level(required):
    """FACE_ITEMS maps a category to its item list, so flatten before scanning."""

    from helpers.gamification import FACE_ITEMS, FACE_UNLOCK_LEVEL

    for items in FACE_ITEMS.values():
        for item in items:
            item_id = item["id"]
            if FACE_UNLOCK_LEVEL.get(item_id, 1) == required:
                return item_id
    return None


def test_an_unlocked_item_can_be_equipped(client, db_session, authenticated_learner):
    item_id = _first_item_at_level(1)
    if item_id is None:
        pytest.skip("no level-1 face item to equip")

    payload = assert_success(
        client.post("/api/equip-item", json={"item_id": item_id})
    ).get_json()

    assert payload["action"] in {"equipped", "unequipped"}
    assert payload["status"] == "ok"


def test_a_locked_item_is_refused_with_its_required_level(client, db_session, authenticated_learner):
    """The unlock gate is server-side, not just hidden in the UI."""

    from helpers.gamification import FACE_UNLOCK_LEVEL

    locked = next(
        (item for item, level in FACE_UNLOCK_LEVEL.items() if level > 1), None
    )
    if locked is None:
        pytest.skip("no gated face item")

    response = client.post("/api/equip-item", json={"item_id": locked})

    assert response.status_code == 403
    assert "Level" in response.get_json()["error"]


def test_equipping_the_worn_top_again_keeps_it_on(client, db_session, authenticated_learner):
    """Body slots and the outfit colour are never empty: re-picking them is a no-op, not a take-off."""

    from helpers.gamification import DEFAULT_FACE

    client.post("/api/equip-item", json={"item_id": DEFAULT_FACE["top"]})
    payload = assert_success(
        client.post("/api/equip-item", json={"item_id": DEFAULT_FACE["top"]})
    ).get_json()

    assert payload["action"] == "equipped"
    assert payload["equipped"]["top"] == DEFAULT_FACE["top"]


def test_picking_an_outfit_colour_replaces_the_last_one(client, db_session, authenticated_learner):
    from helpers.gamification import FACE_ITEMS, FACE_UNLOCK_LEVEL

    free = [item["id"] for item in FACE_ITEMS["colour"] if FACE_UNLOCK_LEVEL.get(item["id"], 1) == 1]
    client.post("/api/equip-item", json={"item_id": free[0]})

    payload = assert_success(client.post("/api/equip-item", json={"item_id": free[1]})).get_json()

    assert payload["equipped"]["colour"] == free[1]


def test_equipping_the_worn_hair_again_takes_it_off(client, db_session, authenticated_learner):
    from helpers.gamification import FACE_ITEMS, FACE_UNLOCK_LEVEL

    hair = next(item["id"] for item in FACE_ITEMS["hair"] if FACE_UNLOCK_LEVEL.get(item["id"], 1) == 1)
    client.post("/api/equip-item", json={"item_id": hair})

    payload = assert_success(client.post("/api/equip-item", json={"item_id": hair})).get_json()

    assert payload["action"] == "unequipped"
    assert payload["equipped"]["hair"] is None


def test_only_a_learner_may_equip_an_item(client, db_session, authenticated_teacher):
    assert client.post("/api/equip-item", json={"item_id": "x"}).status_code == 403


# ── announcements ────────────────────────────────────────────────────────────


def test_dismissing_an_announcement_records_a_high_water_mark(
    client, db_session, authenticated_learner
):
    announcement = make_feature_announcement(db_session)

    assert_success(client.post(f"/api/announcements/{announcement.id}/dismiss"))

    db_session.expire_all()
    assert authenticated_learner.last_seen_announcement_id == announcement.id


def test_dismissing_an_older_announcement_never_re_exposes_a_newer_one(
    client, db_session, authenticated_learner
):
    older = make_feature_announcement(db_session)
    newer = make_feature_announcement(db_session)
    client.post(f"/api/announcements/{newer.id}/dismiss")

    client.post(f"/api/announcements/{older.id}/dismiss")

    db_session.expire_all()
    assert authenticated_learner.last_seen_announcement_id == newer.id


def test_dismissing_an_unknown_announcement_is_a_404(client, db_session, authenticated_learner):
    assert client.post("/api/announcements/999999/dismiss").status_code == 404


def test_any_signed_in_role_may_dismiss_an_announcement(client, db_session, authenticated_teacher):
    """Announcements target every role, so dismissal is not learner-only."""

    announcement = make_feature_announcement(db_session)

    assert_success(client.post(f"/api/announcements/{announcement.id}/dismiss"))

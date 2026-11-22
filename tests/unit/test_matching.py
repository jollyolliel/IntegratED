import pytest

from helpers.matching import (
    DEFAULT_WEIGHTS,
    SPREAD_PENALTY,
    MatchEntity,
    Scorer,
    ScoringTraits,
    match_band,
    score_match,
)

pytestmark = pytest.mark.unit


def score_pair(learner, volunteer, weights=None) -> int:
    """One pair's score through `Scorer`, with these weights (default: every factor at 1.0)."""
    return Scorer({"weights": weights or DEFAULT_WEIGHTS, "spread": SPREAD_PENALTY}).pair(learner, volunteer)


def match_all(learners, volunteers, *, weights=None, spread=SPREAD_PENALTY, **kwargs):
    """A matching run through `Scorer`, with these weights and spread; just the pairs."""
    matches, _board = Scorer({"weights": weights or DEFAULT_WEIGHTS, "spread": spread}).match_all(
        learners, volunteers, **kwargs)
    return matches


def test_score_match_rewards_shared_language_and_similar_age():
    learner: ScoringTraits = {"languages": {"English": "Intermediate", "Arabic": "Beginner"}, "age": 16,
               "personality": "", "traits": set(), "hobbies": set(), "tech_interest": set(), "match_activities": set()}
    volunteer: ScoringTraits = {"languages": {"English": "Advanced"}, "age": 17,
                 "personality": "", "traits": set(), "hobbies": set(), "tech_interest": set(), "match_activities": set()}

    assert score_match(learner, volunteer) > score_match(
        {"languages": {"French": "Beginner"}, "age": 30,
         "personality": "", "traits": set(), "hobbies": set(), "tech_interest": set(), "match_activities": set()}, volunteer
    )


def test_match_all_assigns_each_learner_at_most_once():
    learners: list[MatchEntity] = [
        {"id": 1, "survey_data": {"languages": [{"language": "English", "level": "Intermediate"}], "age": 16}},
        {"id": 2, "survey_data": {"languages": [{"language": "English", "level": "Intermediate"}], "age": 17}},
    ]
    volunteers: list[MatchEntity] = [
        {"id": 9, "survey_data": {"languages": [{"language": "English", "level": "Advanced"}], "age": 17}},
        {"id": 10, "survey_data": {"languages": [{"language": "French", "level": "Beginner"}], "age": 40}},
    ]

    matches = match_all(learners, volunteers)

    assert {learner["id"] for learner, _ in matches} == {1, 2}
    assert len({learner["id"] for learner, _ in matches}) == len(matches)


@pytest.mark.parametrize("capacity", [0, -1])
def test_match_all_excludes_non_positive_capacity(capacity):
    matches = match_all(
        [{"id": 1, "survey_data": {"languages": [{"language": "English"}]}}],
        [{"id": 2, "survey_data": {"languages": [{"language": "English"}]}}],
        capacities={2: capacity},
    )

    assert matches == [({"id": 1, "survey_data": {"languages": [{"language": "English"}]}}, None)]


def test_score_pair_scores_raw_survey_data_without_preprocessing():
    learner: MatchEntity = {"id": 1, "survey_data": {"age": 16, "languages": [{"language": "English", "level": "Beginner"}]}}
    volunteer: MatchEntity = {"id": 2, "survey_data": {"age": 16, "languages": [{"language": "English", "level": "Advanced"}]}}

    # 15 (same age) + 40 (language, volunteer at or above the learner's level)
    # + 30 (exclusivity bonus, the learner's only language)
    assert score_pair(learner, volunteer) == 85


def test_score_pair_survives_missing_survey_data():
    assert score_pair({"id": 1, "survey_data": {}}, {"id": 2, "survey_data": {}}) == 15


@pytest.mark.parametrize(
    ("score", "band"),
    [(0, "weak"), (39, "weak"), (40, "fair"), (79, "fair"), (80, "good"), (119, "good"), (120, "strong"), (500, "strong")],
)
def test_match_band_labels_the_score(score, band):
    assert match_band(score) == band


def _speaker(entity_id: int, age: int, level: str = "Advanced") -> MatchEntity:
    """An English speaker of a given age — age distance is the only thing that
    separates two of these, so a test can tune one pair's score precisely."""
    return {"id": entity_id, "survey_data": {"age": age, "languages": [{"language": "English", "level": level}]}}


def test_match_all_spreads_learners_before_filling_one_volunteer():
    learners = [_speaker(1, 16, "Beginner"), _speaker(2, 16, "Beginner")]
    # 85 against the 16-year-old, 77 against the 22-year-old: filling the
    # first volunteer twice out-scores the split on raw score alone.
    roomy, narrow = _speaker(9, 16), _speaker(10, 22)

    matches = match_all(learners, [roomy, narrow], capacities={9: 2, 10: 1})

    assert sorted(v["id"] for _, v in matches if v is not None) == [9, 10]


def test_match_all_priced_spread_lets_a_strong_pair_outbid_a_second_slot():
    """Handed a number instead of the absolute default, the tier becomes a
    price — a pair worth more than the penalty stacks rather than fan out."""
    learners = [_speaker(1, 16, "Beginner"), _speaker(2, 16, "Beginner")]
    roomy = _speaker(9, 16)
    # No shared language and a 44-year age gap, so this pair scores 0 — far
    # more than 25 points worse than a second learner on `roomy`.
    stranger: MatchEntity = {"id": 10, "survey_data": {"age": 60, "languages": [{"language": "French", "level": "Advanced"}]}}

    matches = match_all(learners, [roomy, stranger], capacities={9: 2, 10: 1}, spread=25)

    assert [v["id"] for _, v in matches if v is not None] == [9, 9]


def test_match_all_counts_learners_a_volunteer_already_holds():
    learners = [_speaker(1, 16, "Beginner")]
    held, empty = _speaker(9, 16), _speaker(10, 22)

    matches = match_all(learners, [held, empty], capacities={9: 1, 10: 1}, loads={9: 1})

    assert [v["id"] for _, v in matches if v is not None] == [10]


def test_match_all_spread_of_zero_restores_pure_score_ranking():
    learners = [_speaker(1, 16, "Beginner"), _speaker(2, 16, "Beginner")]
    roomy, narrow = _speaker(9, 16), _speaker(10, 22)

    matches = match_all(learners, [roomy, narrow], capacities={9: 2, 10: 1}, spread=0)

    assert [v["id"] for _, v in matches if v is not None] == [9, 9]


def test_match_all_gives_out_every_first_slot_before_any_second_slot():
    """The pyramid is absolute by default: no score gap, however wide, buys a
    volunteer a second learner while a colleague still has none."""
    rich = {
        "age": 16,
        "languages": [{"language": "English", "level": "Beginner"}, {"language": "Arabic", "level": "Beginner"}],
        "match_activities": ["reading", "football", "music"],
    }
    learners: list[MatchEntity] = [{"id": i, "survey_data": rich} for i in (1, 2, 3)]
    # Both languages and every activity in common — roughly 200 against the
    # learners where the idle pair score 55, a gap no fixed points-per-tier
    # penalty survives.
    star: MatchEntity = {"id": 9, "survey_data": {
        "age": 16,
        "languages": [{"language": "English", "level": "Advanced"}, {"language": "Arabic", "level": "Advanced"}],
        "match_activities": ["reading", "football", "music"],
    }}
    idle = [_speaker(10, 40), _speaker(11, 45)]

    matches = match_all(learners, [star, *idle], capacities={9: 3, 10: 1, 11: 1})

    assert sorted(v["id"] for _, v in matches if v is not None) == [9, 10, 11]


def test_match_all_fills_deep_tiers_rather_than_leave_a_learner_unpaired():
    learners = [_speaker(i, 16, "Beginner") for i in (1, 2, 3)]
    only = _speaker(9, 16)

    matches = match_all(learners, [only], capacities={9: 3})

    assert [v["id"] for _, v in matches if v is not None] == [9, 9, 9]


def test_match_all_keeps_an_existing_pair_when_the_alternative_only_ties():
    learners = [_speaker(1, 16, "Beginner")]
    # Identical surveys, so the two volunteers score the same against the
    # learner and only the standing pairing separates them.
    incumbent, rival = _speaker(9, 16), _speaker(10, 16)

    matches = match_all(learners, [incumbent, rival], capacities={9: 1, 10: 1}, keep={1: 10})

    assert [v["id"] for _, v in matches if v is not None] == [10]




# ---------------------------------------------------------------------------
# Teacher-tunable factor importance
# ---------------------------------------------------------------------------

def _person(entity_id: int, **survey) -> MatchEntity:
    """One entity whose survey is spelled out inline, for weighting tests."""
    return {"id": entity_id, "survey_data": survey}


def test_resolve_settings_defaults_leave_every_factor_at_one():
    from helpers.matching import FACTORS, resolve_settings

    settings = resolve_settings(None)

    assert settings["weights"] == dict.fromkeys(FACTORS, 1.0)
    assert settings["spread"] is None


def test_default_weights_score_exactly_as_no_weights_at_all():
    from helpers.matching import resolve_settings

    learner = _person(1, age=16, personality="quiet",
                      languages=[{"language": "English", "level": "Beginner"}],
                      hobbies=["reading"], match_activities=["football"])
    volunteer = _person(2, age=18, personality="quiet",
                        languages=[{"language": "English", "level": "Advanced"}],
                        hobbies=["reading"], match_activities=["football"])

    assert score_pair(learner, volunteer,
                      resolve_settings({})["weights"]) == score_pair(learner, volunteer)


def test_weights_are_relative_so_raising_every_factor_changes_nothing():
    """Importance is a share of the total, not a volume knob — a teacher who
    drags every factor to the top lands back on the balanced weighting."""
    from helpers.matching import FACTORS, resolve_settings

    everything_up = resolve_settings({"weights": dict.fromkeys(FACTORS, 4)})
    balanced = resolve_settings({"weights": dict.fromkeys(FACTORS, 2)})

    assert everything_up["weights"] == balanced["weights"]


def test_weighting_a_factor_up_pulls_the_others_down():
    from helpers.matching import resolve_settings

    weights = resolve_settings({"weights": {"language": 4}})["weights"]

    assert weights["language"] > 1.0
    assert weights["hobbies"] < 1.0
    # Rescaled, not inflated: the importance still averages out to 1.0, which
    # is what keeps a score comparable to MATCH_BANDS under any weighting.
    assert sum(weights.values()) == pytest.approx(len(weights))


def test_weighting_language_up_beats_a_hobbies_only_volunteer():
    """The whole point of the feature: the same two candidates swap places
    when the teacher says which factor they care about."""
    from helpers.matching import resolve_settings

    learner = _person(1, age=16,
                      languages=[{"language": "Arabic", "level": "Beginner"}],
                      hobbies=["reading", "football", "music", "art"])
    linguist = _person(9, age=40,
                       languages=[{"language": "Arabic", "level": "Advanced"}])
    companion = _person(10, age=40, languages=[],
                        hobbies=["reading", "football", "music", "art"])

    language_first = resolve_settings({"weights": {"language": 4, "hobbies": 1}})["weights"]
    hobbies_first = resolve_settings({"weights": {"language": 1, "hobbies": 4}})["weights"]

    assert score_pair(learner, linguist, language_first) > score_pair(learner, companion, language_first)
    assert score_pair(learner, companion, hobbies_first) > score_pair(learner, linguist, hobbies_first)


def test_a_factor_turned_off_stops_counting():
    from helpers.matching import resolve_settings

    learner = _person(1, age=16, hobbies=["reading"])
    volunteer = _person(2, age=16, hobbies=["reading"])
    hobbies_off = resolve_settings({"weights": {"hobbies": 0}})["weights"]

    # Nothing but age is left to score on, so the pair scores what a pair
    # sharing nothing but their age scores.
    assert score_pair(learner, volunteer, hobbies_off) == score_pair(
        _person(1, age=16), _person(2, age=16), hobbies_off
    )


def test_every_factor_off_falls_back_to_the_balanced_weighting():
    # A board of zeroes would score every pair identically, leaving the
    # matcher nothing to rank on, so it reads as "no preference expressed".
    from helpers.matching import FACTORS, resolve_settings

    weights = resolve_settings({"weights": dict.fromkeys(FACTORS, 0)})["weights"]

    assert weights == dict.fromkeys(FACTORS, 1.0)


@pytest.mark.parametrize(
    "raw",
    [None, {}, "not a dict", 7, {"weights": "not a dict"}, {"weights": {"language": "loads"}},
     {"weights": {"nonsense": 3}}, {"spread": "lots"}, {"weights": {"language": 99}, "spread": -4}],
)
def test_normalize_levels_survives_whatever_is_in_the_column(raw):
    """`match_settings` is authored JSON like `survey_data` — a half-written or
    hand-edited blob has to read as defaults, never raise mid-render."""
    from helpers.matching import (
        FACTORS,
        SPREAD_PENALTIES,
        WEIGHT_MULTIPLIERS,
        normalize_levels,
    )

    levels = normalize_levels(raw)

    assert set(levels["weights"]) == set(FACTORS)
    assert all(0 <= level < len(WEIGHT_MULTIPLIERS) for level in levels["weights"].values())
    assert 0 <= levels["spread"] < len(SPREAD_PENALTIES)


def test_normalize_levels_clamps_rather_than_wrapping():
    from helpers.matching import WEIGHT_MULTIPLIERS, normalize_levels

    levels = normalize_levels({"weights": {"language": 99, "hobbies": -3}})

    assert levels["weights"]["language"] == len(WEIGHT_MULTIPLIERS) - 1
    assert levels["weights"]["hobbies"] == 0


def test_normalize_levels_keeps_what_the_teacher_actually_set():
    from helpers.matching import normalize_levels

    levels = normalize_levels({"weights": {"language": 4, "age": 0}, "spread": 3})

    assert levels["weights"]["language"] == 4
    assert levels["weights"]["age"] == 0
    assert levels["spread"] == 3


def test_spread_levels_run_from_absolute_layering_to_pure_score():
    from helpers.matching import SPREAD_PENALTIES, resolve_settings

    assert resolve_settings({"spread": 0})["spread"] is None
    assert resolve_settings({"spread": len(SPREAD_PENALTIES) - 1})["spread"] == 0
    # Every level above the first is a price, falling as strong matches matter
    # more — absolute layering is level 0 alone.
    priced = [penalty for penalty in SPREAD_PENALTIES[1:] if penalty is not None]
    assert len(priced) == len(SPREAD_PENALTIES) - 1
    assert priced == sorted(priced, reverse=True)


def test_top_spread_level_lets_one_volunteer_take_both_learners():
    """End to end through `match_all`: the stored level, not a hand-passed
    number, is what turns the layering off."""
    from helpers.matching import SPREAD_PENALTIES, resolve_settings

    learners = [_speaker(1, 16, "Beginner"), _speaker(2, 16, "Beginner")]
    roomy, narrow = _speaker(9, 16), _speaker(10, 22)
    top = len(SPREAD_PENALTIES) - 1

    spread_out = match_all(learners, [roomy, narrow], capacities={9: 2, 10: 1},
                           spread=resolve_settings({"spread": 0})["spread"])
    best_wins = match_all(learners, [roomy, narrow], capacities={9: 2, 10: 1},
                          spread=resolve_settings({"spread": top})["spread"])

    assert sorted(v["id"] for _, v in spread_out if v is not None) == [9, 10]
    assert [v["id"] for _, v in best_wins if v is not None] == [9, 9]


def test_match_all_assignment_follows_the_weighting():
    from helpers.matching import resolve_settings

    learners = [_person(1, age=16, languages=[{"language": "Arabic", "level": "Beginner"}],
                        hobbies=["reading", "football", "music", "art"])]
    linguist = _person(9, age=40, languages=[{"language": "Arabic", "level": "Advanced"}])
    companion = _person(10, age=40, languages=[],
                        hobbies=["reading", "football", "music", "art"])

    language_first = match_all(
        learners, [linguist, companion], capacities={9: 1, 10: 1},
        weights=resolve_settings({"weights": {"language": 4, "hobbies": 1}})["weights"])
    hobbies_first = match_all(
        learners, [linguist, companion], capacities={9: 1, 10: 1},
        weights=resolve_settings({"weights": {"language": 1, "hobbies": 4}})["weights"])

    assert [v["id"] for _, v in language_first if v is not None] == [9]
    assert [v["id"] for _, v in hobbies_first if v is not None] == [10]


# ── Scorer — the boundary object app code holds instead of loose weights ─────


def test_scorer_pair_scores_on_the_teachers_saved_weights():
    """A `Scorer` is built from stored settings once; nothing downstream can
    forget to pass them."""
    from helpers.matching import Scorer, resolve_settings

    stored = {"weights": {"language": 4, "hobbies": 0}, "spread": 2}
    learner = _person(1, age=16, languages=[{"language": "Arabic", "level": "Beginner"}],
                      hobbies=["reading"])
    volunteer = _person(9, age=18, languages=[{"language": "Arabic", "level": "Advanced"}],
                        hobbies=["reading"])

    scorer = Scorer.for_teacher(stored)

    assert scorer.pair(learner, volunteer) == score_pair(
        learner, volunteer, resolve_settings(stored)["weights"]
    )


def test_scorer_matrix_answers_by_id_not_by_position():
    from helpers.matching import Scorer

    learners = [_person(5, age=16, hobbies=["reading"]), _person(3, age=40)]
    volunteers = [_person(90, age=16, hobbies=["reading"]), _person(70, age=41)]

    scorer = Scorer.for_teacher(None)
    matrix = scorer.matrix(learners, volunteers)

    for learner in learners:
        for volunteer in volunteers:
            assert matrix.of(learner["id"], volunteer["id"]) == scorer.pair(learner, volunteer)


def test_scorer_match_all_hands_back_the_matrix_it_matched_on():
    """The preview shows the scores the run optimised — same numbers, one
    computation, so the two cannot drift apart."""
    from helpers.matching import Scorer

    learners = [_person(1, age=16, languages=[{"language": "Arabic", "level": "Beginner"}]),
                _person(2, age=17, hobbies=["football"])]
    volunteers = [_person(9, age=18, languages=[{"language": "Arabic", "level": "Advanced"}]),
                  _person(10, age=17, hobbies=["football"])]

    scorer = Scorer.for_teacher({"weights": {"language": 4}})
    matches, matrix = scorer.match_all(learners, volunteers, capacities={9: 1, 10: 1})

    assert sorted(v["id"] for _, v in matches if v is not None) == [9, 10]
    assert matrix.of(1, 9) == scorer.pair(learners[0], volunteers[0])
    assert matrix.of(2, 10) == scorer.pair(learners[1], volunteers[1])


def test_scorer_match_all_runs_on_the_bound_spread():
    """Spread rides the same object as the weights, so a caller cannot take
    one and drop the other."""
    from helpers.matching import SPREAD_PENALTIES, Scorer

    learners = [_person(1, age=16), _person(2, age=16)]
    roomy, narrow = _person(9, age=16), _person(10, age=40)

    spread_out, _ = Scorer.for_teacher({"spread": 0}).match_all(
        learners, [roomy, narrow], capacities={9: 2, 10: 1})
    best_wins, _ = Scorer.for_teacher({"spread": len(SPREAD_PENALTIES) - 1}).match_all(
        learners, [roomy, narrow], capacities={9: 2, 10: 1})

    assert sorted(v["id"] for _, v in spread_out if v is not None) == [9, 10]
    assert [v["id"] for _, v in best_wins if v is not None] == [9, 9]


def test_scorer_match_all_scores_identically_to_a_loose_weights_call():
    """`Scorer.match_all` feeds `match_all` a precomputed matrix — it has to
    reach the same assignment the un-precomputed call reaches."""
    from helpers.matching import Scorer, resolve_settings

    stored = {"weights": {"language": 4, "hobbies": 1}}
    learners = [_person(1, age=16, languages=[{"language": "Arabic", "level": "Beginner"}],
                        hobbies=["reading", "football", "music", "art"])]
    linguist = _person(9, age=40, languages=[{"language": "Arabic", "level": "Advanced"}])
    companion = _person(10, age=40, hobbies=["reading", "football", "music", "art"])
    settings = resolve_settings(stored)

    bound, _ = Scorer.for_teacher(stored).match_all(
        learners, [linguist, companion], capacities={9: 1, 10: 1})
    loose = match_all(learners, [linguist, companion], capacities={9: 1, 10: 1},
                      weights=settings["weights"], spread=settings["spread"])

    assert [v["id"] for _, v in bound if v] == [v["id"] for _, v in loose if v]

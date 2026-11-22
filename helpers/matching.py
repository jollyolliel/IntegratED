from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, TypedDict

from helpers.assignment import linear_sum_assignment

__all__ = [
    "FACTORS",
    "SPREAD_PENALTIES",
    "WEIGHT_MULTIPLIERS",
    "ScoreMatrix",
    "Scorer",
    "match_all",
    "match_band",
    "normalize_levels",
    "resolve_settings",
    "score_match",
]

#: Score thresholds a pair must reach to earn each label, richest first. The
#: cut-offs are read off the base weights in `score_match`: a single
#: well-levelled shared language alone is worth 70, so "fair" starts below
#: that and "strong" needs a language plus real overlap on top of it. They
#: survive a teacher's re-weighting because `resolve_settings` rescales
#: importance rather than amplifying it — see there.
MATCH_BANDS: tuple[tuple[int, str], ...] = ((120, "strong"), (80, "good"), (40, "fair"), (0, "weak"))

#: The factors a pair is scored on, in the order `score_match` sums them —
#: also the key set of a teacher's stored weighting, so anything else in that
#: JSON is dropped on read.
FACTORS: tuple[str, ...] = (
    "age", "language", "personality", "traits", "hobbies",
    "tech_interest", "match_activities",
)

#: Raw multiplier behind each importance level a teacher can pick, least
#: important first. A teacher's stored setting is the *index*, never the
#: multiplier: that way re-tuning the curve moves every roster at once
#: instead of freezing each teacher on the numbers their browser saw.
WEIGHT_MULTIPLIERS: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 3.0)

#: Level every factor starts on — the 1.0 multiplier, so an untouched teacher
#: scores exactly as they did before weighting existed.
DEFAULT_WEIGHT_LEVEL = 2

#: Points knocked off a pair's score for each learner the volunteer already
#: holds — their standing roster plus anything `match_all` handed them earlier
#: in the same run — one entry per spread level the teacher can pick, from
#: "always spread evenly" to "best match wins". `None` makes the tier order
#: absolute: every volunteer's first learner is placed before anyone's second,
#: whatever the scores say, and score only ranks candidates *within* a tier. A
#: number softens that into a bribe a good enough pair can outbid, and 0 turns
#: spreading off entirely.
#:
#: Deliberately not a linear scale. The gaps being priced are wide — one
#: shared language is worth 55-70 points and pairs sharing two languages and a
#: few activities clear 200 — so the useful range sits high and coarse, and
#: any penalty small enough to read as a gentle nudge is one a real roster
#: ignores completely.
SPREAD_PENALTIES: tuple[int | None, ...] = (None, 150, 80, 30, 0)

#: Spread level a teacher starts on — the absolute tier order.
DEFAULT_SPREAD_LEVEL = 0

#: The default `match_all` falls back to, kept as the module-level name the
#: spread levels are expressed against.
SPREAD_PENALTY: int | None = SPREAD_PENALTIES[DEFAULT_SPREAD_LEVEL]

#: Points added to the pair a learner is already in, so a rebalance that has
#: a free choice between equal candidates leaves the roster alone. Deliberately
#: far below a single language overlap: it breaks ties, it never defends a
#: pairing the matcher has a real reason to move.
KEEP_BONUS = 5

#: Fluency ranks, lowest first. An unrecognised or missing level reads as the
#: bottom rank, so an unlabelled language still counts as spoken.
_LEVELS = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}


class Matchable(Protocol):
    """Anything the matcher can score: a Learner or Volunteer row, or a `MatchEntity`-shaped object."""

    @property
    def id(self) -> int: ...

    @property
    def survey_data(self) -> Any: ...


class MatchEntity(TypedDict):
    """One person as the matcher sees them — identity plus raw survey answers.

    `survey_data` is untrusted authored JSON, so every read below goes through
    a coercion rather than trusting a key's presence or type.
    """
    id: int
    survey_data: dict[str, Any]


class ScoringTraits(TypedDict):
    """Everything `score_match` actually compares — identity deliberately absent,
    so a score can never depend on who the person is."""
    age: int
    languages: dict[str, str]
    personality: str
    traits: set[str]
    hobbies: set[str]
    tech_interest: set[str]
    match_activities: set[str]


class EntityTraits(ScoringTraits):
    """A `MatchEntity` normalized once, so scoring never re-parses survey data."""
    id: int


class MatchLevels(TypedDict):
    """A teacher's matching preferences as they are stored and as the form
    redraws them — level indices, not multipliers."""
    weights: dict[str, int]
    spread: int


class MatchSettings(TypedDict):
    """The same preferences resolved into the numbers `score_match` and
    `match_all` actually take."""
    weights: dict[str, float]
    spread: int | None


#: Every factor at `DEFAULT_WEIGHT_LEVEL`, already rescaled — what
#: `score_match` uses when a caller passes no weighting at all.
DEFAULT_WEIGHTS: dict[str, float] = dict.fromkeys(FACTORS, 1.0)


def _clamped_level(value: Any, top: int, default: int) -> int:
    """Coerces one stored level into range.

    Args:
        value (Any): The raw stored value.
        top (int): Highest level that exists.
        default (int): Level to fall back to when `value` is not a number.

    Returns:
        int: A level between 0 and `top`.
    """
    try:
        level = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(top, level))


def normalize_levels(raw: Any) -> MatchLevels:
    """Reads a teacher's stored `match_settings` blob into a complete, in-range
    set of levels.

    Args:
        raw (Any): Whatever `Teacher.match_settings` holds.

    Returns:
        MatchLevels: A level for every factor, plus the spread level.
    """
    # Lenient on purpose: the column is authored JSON like `survey_data`, so an
    # unknown factor, a missing key, a string where a number belongs or a level
    # that no longer exists reads as the default instead of raising mid-render.
    # `teacher_ops.validate_set_match_settings` is the strict twin guarding
    # what goes in.
    blob = raw if isinstance(raw, dict) else {}
    stored = blob.get("weights")
    if not isinstance(stored, dict):
        stored = {}
    return {
        "weights": {
            factor: _clamped_level(
                stored.get(factor, DEFAULT_WEIGHT_LEVEL),
                len(WEIGHT_MULTIPLIERS) - 1,
                DEFAULT_WEIGHT_LEVEL,
            )
            for factor in FACTORS
        },
        "spread": _clamped_level(
            blob.get("spread", DEFAULT_SPREAD_LEVEL),
            len(SPREAD_PENALTIES) - 1,
            DEFAULT_SPREAD_LEVEL,
        ),
    }


def resolve_settings(raw: Any) -> MatchSettings:
    """Turns a teacher's stored levels into the weights and spread penalty the
    matcher consumes.

    Args:
        raw (Any): Whatever `Teacher.match_settings` holds.

    Returns:
        MatchSettings: Rescaled per-factor multipliers and the tier penalty.
    """
    # Weights are relative: the picked multipliers are rescaled to average 1.0,
    # so raising every factor to the top lands back on the balanced weighting —
    # importance is a share of the total, not a volume knob. That also keeps a
    # score comparable to MATCH_BANDS and keeps SPREAD_PENALTIES calibrated,
    # both of which are fixed point values weighed against a score.
    levels = normalize_levels(raw)
    picked = {f: WEIGHT_MULTIPLIERS[levels["weights"][f]] for f in FACTORS}
    total = sum(picked.values())
    if total <= 0:
        # Every factor off scores every pair identically, leaving the matcher
        # nothing to rank on — read it as "no preference expressed".
        return {"weights": dict(DEFAULT_WEIGHTS), "spread": SPREAD_PENALTIES[levels["spread"]]}

    scale = len(FACTORS) / total
    return {
        "weights": {factor: value * scale for factor, value in picked.items()},
        "spread": SPREAD_PENALTIES[levels["spread"]],
    }

def _norm_items(items: list[Any] | None) -> set[str]:
    """Normalizes list items for fuzzy matching once per entity.

    Args:
        items (list[Any] | None): Raw values to normalize.

    Returns:
        set[str]: Lowercased values with spaces/dashes stripped.
    """
    if not items:
        return set()
    return {str(i).lower().replace(" ", "").replace("-", "").strip() for i in items if i}

def _preprocess_entity(entity: MatchEntity) -> EntityTraits:
    """Extracts and normalizes all matchable traits from survey data once.

    Args:
        entity (MatchEntity): Raw learner/volunteer dict with `id` and `survey_data`.

    Returns:
        EntityTraits: The normalized, comparable traits.
    """
    survey = entity.get("survey_data", {})
    if not isinstance(survey, dict):
        survey = {}

    # Language mapping
    languages = survey.get("languages", []) or []
    lang_lvls = {
        l.get("language"): l.get("level") for l in languages
        if isinstance(l, dict) and l.get("language")
    }

    return {
        "id": entity.get("id"),
        "age": int(survey.get("age", 0)) if str(survey.get("age")).isdigit() else 0,
        "languages": lang_lvls,
        "personality": str(survey.get("personality", "")).lower().strip(),
        "traits": _norm_items(survey.get("traits", [])),
        "hobbies": _norm_items(survey.get("hobbies", [])),
        "tech_interest": _norm_items(survey.get("tech_interest", [])),
        "match_activities": _norm_items(survey.get("match_activities", [])),
    }

def score_match(
    l_data: ScoringTraits, v_data: ScoringTraits, weights: dict[str, float] | None = None
) -> int:
    """Compatibility score between a preprocessed learner and volunteer: one cell of `_score_matrix`,
    which defines every factor (age, languages, personality, traits, hobbies, tech, activities).

    Args:
        l_data (ScoringTraits): Preprocessed learner traits (see `_preprocess_entity`).
        v_data (ScoringTraits): Preprocessed volunteer traits (see `_preprocess_entity`).
        weights (dict[str, float] | None): Per-factor multipliers from
            `resolve_settings`; `None` scores every factor at 1.0.

    Returns:
        int: Compatibility score.
    """
    return _score_matrix([l_data], [v_data], weights)[0][0]


def _score_matrix(
    p_learners: Sequence[ScoringTraits],
    p_volunteers: Sequence[ScoringTraits],
    weights: dict[str, float] | None = None,
) -> list[list[int]]:
    """Every compatibility score at once, as a learner-by-volunteer matrix — the one definition of a score.

    Each factor is an exact integer weighted by a single multiplication and summed in a fixed order,
    then rounded: AGE (max 15), LANGUAGE (40 per shared language the volunteer speaks at least as
    well, else 15, plus a bonus that grows as the learner has fewer languages, so language-scarce
    learners are placed first), PERSONALITY (12), and set overlaps on traits (5 each), hobbies (8),
    tech interest (10) and match activities (25).

    Args:
        p_learners (Sequence[ScoringTraits]): Preprocessed learner traits — a
            `Sequence`, not a `list`, so a list of `EntityTraits` is accepted
            (`list` is invariant, and every caller here has the `id` on it).
        p_volunteers (Sequence[ScoringTraits]): Preprocessed volunteer traits.
        weights (dict[str, float] | None): Per-factor multipliers from
            `resolve_settings`; `None` scores every factor at 1.0.

    Returns:
        list[list[int]]: Integer scores, learners down, volunteers across.
    """
    # Everything that depends on only one side is hoisted out of the per-cell
    # loop: each volunteer is unpacked once, each learner once per row, and the
    # weights live in locals.
    w = weights or DEFAULT_WEIGHTS
    w_age, w_language, w_personality = w["age"], w["language"], w["personality"]
    w_traits, w_hobbies = w["traits"], w["hobbies"]
    w_tech, w_activities = w["tech_interest"], w["match_activities"]
    levels = _LEVELS

    volunteers = [
        (
            v["age"],
            {lang: levels.get(level, 1) for lang, level in v["languages"].items()},
            v["personality"],
            v["traits"], v["hobbies"], v["tech_interest"], v["match_activities"],
        )
        for v in p_volunteers
    ]

    board: list[list[int]] = []
    for l in p_learners:
        l_age = l["age"]
        l_languages = [(lang, levels.get(level, 1)) for lang, level in l["languages"].items()]
        exclusivity_bonus = int(30.0 / max(1, len(l["languages"])))
        l_personality = l["personality"]
        l_traits, l_hobbies = l["traits"], l["hobbies"]
        l_tech, l_activities = l["tech_interest"], l["match_activities"]

        row: list[int] = []
        for v_age, v_languages, v_personality, v_traits, v_hobbies, v_tech, v_activities in volunteers:
            # AGE (Max 15 points)
            age = max(0, 15 - max(0, abs(l_age - v_age) - 2) * 2)

            # LANGUAGE (40 points per compatible overlap, weighted by learner exclusivity)
            language = 0
            for lang, l_level in l_languages:
                v_level = v_languages.get(lang)
                if v_level is not None:
                    language += (40 if v_level >= l_level else 15) + exclusivity_bonus

            # PERSONALITY (12 points)
            personality = 12 if l_personality and l_personality == v_personality else 0

            # SET Overlaps (Traits: 5, Hobbies: 8, Tech: 10, Activities: 25)
            row.append(round(
                age * w_age
                + language * w_language
                + personality * w_personality
                + 5 * len(l_traits & v_traits) * w_traits
                + 8 * len(l_hobbies & v_hobbies) * w_hobbies
                + 10 * len(l_tech & v_tech) * w_tech
                + 25 * len(l_activities & v_activities) * w_activities
            ))
        board.append(row)
    return board


def match_band(score: int) -> str:
    """Buckets a raw score into a label, so a bare number gets a meaning.

    Args:
        score (int): A `score_match` / `score_pair` result.

    Returns:
        str: One of "strong", "good", "fair", "weak".
    """
    for threshold, band in MATCH_BANDS:
        if score >= threshold:
            return band
    return "weak"


def match_all(
    learners: list[MatchEntity],
    volunteers: list[MatchEntity],
    scores: Sequence[Sequence[int]],
    *,
    capacities: dict[int, int] | None = None,
    loads: dict[int, int] | None = None,
    spread: int | None = SPREAD_PENALTY,
    keep: dict[int, int] | None = None,
) -> list[tuple[MatchEntity, MatchEntity | None]]:
    """Matches learners to volunteers by linear sum assignment (the
    Hungarian problem, solved by `helpers.assignment`). Capacity is modeled by expanding each volunteer
    into one matrix column per open slot — the assignment itself stays
    one-to-one (columns, not volunteers), so optimality still holds. A
    volunteer missing from `capacities` gets 1 slot; explicitly mapped to 0,
    they're excluded entirely.

    Each of a volunteer's columns sits one tier deeper than the last, starting
    at whatever they already hold (`loads`), and a tier costs `spread` points
    (see `SPREAD_PENALTIES`), so learners fan out across volunteers rather
    than filling the best-scoring one to its limit. Capacity reads as a
    ceiling, not a target.

    Every learner still gets a slot while one exists: the assignment pairs off
    whichever side is shorter, so a learner goes unmatched only when the slots
    ran out, never because their remaining slot sat at an expensive tier.

    Args:
        learners (list[MatchEntity]): Learners to place.
        volunteers (list[MatchEntity]): Volunteers to place them with.
        scores (Sequence[Sequence[int]]): The learner-by-volunteer board, in the order of
            `learners` and `volunteers` (`Scorer.matrix`), so a caller can read single cells back
            out of the same numbers the run optimised.
        capacities (dict[int, int] | None): Volunteer id -> free slot count.
        loads (dict[int, int] | None): Volunteer id -> learners already held, which
            the tier penalty starts from. Absent ids are treated as empty.
        spread (int | None): Points charged per tier; `None` makes tier order
            absolute, 0 ranks on raw score alone.
        keep (dict[int, int] | None): Learner id -> the volunteer they are already
            paired with, worth `KEEP_BONUS` as a tie-break.

    Returns:
        list[tuple[MatchEntity, MatchEntity | None]]: One entry per learner,
            paired with its matched volunteer or None.
    """
    if not learners:
        return []
    if not volunteers:
        return [(l, None) for l in learners]

    board = [[float(score) for score in row] for row in scores]

    # Expand each volunteer into one column per open slot, remembering which
    # volunteer the column belongs to (so its score is computed once, not once
    # per slot) and how deep the slot sits.
    columns: list[tuple[int, int]] = []  # (volunteer index, tier)
    for v_index, volunteer in enumerate(volunteers):
        slots = 1
        if capacities is not None:
            try:
                slots = int(capacities.get(volunteer.get("id"), 1))
            except (TypeError, ValueError):
                slots = 1
        try:
            held = int((loads or {}).get(volunteer.get("id"), 0))
        except (TypeError, ValueError):
            held = 0
        # No volunteer can take more than every learner in the run, so slots
        # past that are columns the solver would carry and never use.
        for slot in range(min(max(0, slots), len(learners))):
            columns.append((v_index, max(0, held) + slot))

    if not columns:
        return [(l, None) for l in learners]

    n = len(learners)

    # One score per learner/volunteer, fanned across that volunteer's slot
    # columns — a five-slot volunteer would otherwise cost five identical
    # scorings per learner.
    if keep:
        for i, learner in enumerate(learners):
            held_by = keep.get(learner.get("id"))
            for j, volunteer in enumerate(volunteers):
                if held_by is not None and volunteer.get("id") == held_by:
                    board[i][j] += KEEP_BONUS

    # A tier has to cost more than the whole board can win back by ignoring it
    # — one learner deeper must never pay off, even if every other learner
    # gains the best score on the board.
    tier_cost = n * (max(max(row) for row in board) + 1) if spread is None else spread

    # Build cost matrix (the solver minimizes, so we use negative scores). It
    # stays rectangular: the solver handles the rectangular problem directly,
    # pairing off the shorter side optimally, so padding it out to a square
    # only hands the solver rows and columns that mean nothing — and when
    # learners outnumber slots that padding is most of the matrix.
    cost_matrix = [
        [-(row[v_index] - tier_cost * tier) for v_index, tier in columns] for row in board
    ]

    # Run Hungarian Algorithm
    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    # Map results back to original lists, in the caller's learner order. Rows
    # the solver left out are learners there was no slot for.
    assigned = dict(zip(row_ind, col_ind, strict=True))
    return [
        (learner, volunteers[columns[assigned[i]][0]] if i in assigned else None)
        for i, learner in enumerate(learners)
    ]


class ScoreMatrix:
    """Every learner-by-volunteer score from one scoring pass, keyed by id.

    A run scores the whole board once. Anything that afterwards wants a single
    cell — what the chosen pair was worth, what a pair the teacher swaps to
    would be worth — reads it back out of here instead of re-scoring that pair,
    which would re-normalize both people's survey data all over again.
    """

    __slots__ = ("_learner_rows", "_volunteer_cols", "scores")

    def __init__(
        self, scores: list[list[int]], learner_ids: Sequence[int], volunteer_ids: Sequence[int]
    ) -> None:
        self.scores = scores
        self._learner_rows = {person_id: row for row, person_id in enumerate(learner_ids)}
        self._volunteer_cols = {person_id: col for col, person_id in enumerate(volunteer_ids)}

    def of(self, learner_id: int, volunteer_id: int) -> int:
        """One pair's score.

        Args:
            learner_id (int): A learner from the pass that built this matrix.
            volunteer_id (int): A volunteer from that same pass.

        Returns:
            int: The score, identical to `Scorer.pair` on the same two people.

        Raises:
            KeyError: Either id was not in the pass — the caller is asking
                about somebody this board never scored, which is a bug rather
                than a zero.
        """
        return self.scores[self._learner_rows[learner_id]][self._volunteer_cols[volunteer_id]]


class Scorer:
    """One teacher's matching preferences, resolved once and bound to every
    way of scoring with them.

    App code holds a `Scorer`, never a loose `weights` dict. `pair`, `matrix`
    and `match_all` all run on the same resolved numbers, so the score on a
    person page, the score in a preview and the score the matcher optimised
    are one computation's worth of agreement rather than three call sites
    remembering to pass the same argument. Forgetting the teacher's settings
    would mean having no `Scorer` at all, which does not type-check.

    The module-level `score_match` / `match_all` stay the primitives underneath; a `Scorer`
    takes rows (anything `Matchable`) or `MatchEntity` dicts and hands back what it was given.
    """

    __slots__ = ("spread", "weights")

    def __init__(self, settings: MatchSettings) -> None:
        self.weights = settings["weights"]
        self.spread = settings["spread"]

    @classmethod
    def for_teacher(cls, raw: Any) -> Scorer:
        """Builds a scorer from a teacher's stored settings blob.

        Args:
            raw (Any): Whatever `Teacher.match_settings` holds — read
                leniently, see `normalize_levels`.

        Returns:
            Scorer: Bound to that teacher's weights and spread.
        """
        return cls(resolve_settings(raw))

    def pair(self, learner: Matchable | MatchEntity, volunteer: Matchable | MatchEntity) -> int:
        """This teacher's score for one already-decided pair.

        Args:
            learner (Matchable | MatchEntity): The learner (a row, or `{"id", "survey_data"}`).
            volunteer (Matchable | MatchEntity): The volunteer, likewise.

        Returns:
            int: The compatibility score.
        """
        return score_match(_preprocess_entity(_entity(learner)), _preprocess_entity(_entity(volunteer)), self.weights)

    def matrix(
        self, learners: Sequence[Matchable | MatchEntity], volunteers: Sequence[Matchable | MatchEntity]
    ) -> ScoreMatrix:
        """Scores a whole board in one pass.

        Args:
            learners (Sequence[Matchable | MatchEntity]): Learners.
            volunteers (Sequence[Matchable | MatchEntity]): Volunteers.

        Returns:
            ScoreMatrix: Every pair's score, indexed by id.
        """
        l_entities = [_entity(l) for l in learners]
        v_entities = [_entity(v) for v in volunteers]
        scores = _score_matrix(
            [_preprocess_entity(l) for l in l_entities], [_preprocess_entity(v) for v in v_entities], self.weights
        )
        return ScoreMatrix(scores, [l["id"] for l in l_entities], [v["id"] for v in v_entities])

    def match_all[L: (Matchable | MatchEntity), V: (Matchable | MatchEntity)](
        self,
        learners: Sequence[L],
        volunteers: Sequence[V],
        *,
        capacities: dict[int, int] | None = None,
        loads: dict[int, int] | None = None,
        keep: dict[int, int] | None = None,
    ) -> tuple[list[tuple[L, V | None]], ScoreMatrix]:
        """Runs the matcher on this teacher's settings, handing back the board it ran on.

        The matrix comes back because a caller that shows the run to somebody
        needs single cells out of it — the proposed pair's score, every
        alternative the reviewer could pick instead. Re-deriving those pair by
        pair is both slower than the pass that already computed them and free
        to disagree with it.

        Args:
            learners (Sequence[L]): Learners to place — rows or `MatchEntity` dicts.
            volunteers (Sequence[V]): Volunteers to place them with.
            capacities (dict[int, int] | None): Volunteer id -> free slot count (1 when absent).
            loads (dict[int, int] | None): Volunteer id -> learners already held.
            keep (dict[int, int] | None): Learner id -> the volunteer they are already with.

        Returns:
            tuple[list[tuple[L, V | None]], ScoreMatrix]: Each learner given, with the volunteer
                given that it is placed with (or None), and the scores the run decided on.
        """
        board = self.matrix(learners, volunteers)
        l_entities = [_entity(l) for l in learners]
        v_entities = [_entity(v) for v in volunteers]
        given_volunteer = {entity["id"]: volunteer for entity, volunteer in zip(v_entities, volunteers, strict=True)}
        matches = match_all(
            l_entities, v_entities, board.scores, capacities=capacities, loads=loads, spread=self.spread, keep=keep,
        )
        return [
            (learner, given_volunteer[match["id"]] if match else None)
            for learner, (_entity_l, match) in zip(learners, matches, strict=True)
        ], board


def _entity(person: Matchable | MatchEntity) -> MatchEntity:
    """A row or a dict as the `MatchEntity` the scoring primitives read."""
    if isinstance(person, Mapping):
        return MatchEntity(id=person["id"], survey_data=person.get("survey_data") or {})
    return MatchEntity(id=person.id, survey_data=person.survey_data or {})

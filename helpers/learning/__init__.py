"""Learning path — placement staircase, game completion, progress snapshots,
answer validation.

Layout:
  _placement.py   the adaptive placement-test staircase, one per placement scale
                  (CONFIRM, FLOOR_MISSES, apply_map_answer)
  _answer_log.py  the per-lesson answer log: one row per learner and lesson, one
                  entry per try at a unit (a question, or a Match Up pair)
  _completion.py  lock_learner and record_lesson_completion: XP, progress, next lesson
  _games.py       GAMES — the quiz and the 5 games as one table — deal (what a run
                  serves and scores), check_match_pair, and complete_lesson
  _run.py         lesson_run (what a run serves, where it resumes) and hint
  _snapshot.py    pair/progress snapshots, recommended course + start, worksheets
  _course_placement.py  placement bands: the course and starting topic a level points at
  _validators.py  grade — a validator per quiz content type, dispatched on it

The placement-test staircase algorithm is documented on `apply_map_answer`.
Matching algorithm (Hungarian, capacity): `docs/features/matching.md`.
"""

from helpers.learning import _answer_log as answer_log  # noqa: F401
from helpers.learning._completion import (  # noqa: F401
    CompletionPayload,
    lock_learner,
    record_lesson_completion,
)
from helpers.learning._games import (  # noqa: F401
    GAMES,
    GARDEN_PLOTS,
    IncompleteLesson,
    Unit,
    check_match_pair,
    complete_lesson,
    deal,
    dealt_questions,
    lesson_type,
    result_type,
)
from helpers.learning._placement import (  # noqa: F401
    CONFIRM,
    FLOOR_MISSES,
    apply_map_answer,
    get_subject_id,
    new_scale_state,
    next_placement_question_for_subject,
    placement_estimate,
    subject_max_level,
)
from helpers.learning._run import (  # noqa: F401
    HINT_AFTER_WRONG,
    HINT_TYPES,
    LessonRun,
    hint,
    lesson_run,
)
from helpers.learning._snapshot import (  # noqa: F401
    build_teacher_pair_summaries,
    get_current_topic_progress,
    get_first_step,
    get_learner_progress_position,
    get_pair_learning_snapshot,
    get_recommended_start,
    get_recommended_worksheets,
    get_teacher_pair_or_404,
    learner_journey,
)
from helpers.learning._validators import (  # noqa: F401
    Grade,
    grade,
    validate_drag_drop,
    validate_fill_blank,
    validate_multiple_choice,
    validate_open_answer,
    validate_word_selection,
)

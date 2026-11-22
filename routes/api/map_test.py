"""Placement test (map test) — adaptive staircase over MapQuestions."""

import math
import random

from flask import jsonify, request, url_for
from sqlalchemy.orm.attributes import flag_modified

from extensions import db
from helpers import learning
from helpers.analytics import capture_event
from helpers.audio_cache import audio_url
from helpers.current_user import current_learner as current_user
from helpers.learning import get_recommended_start
from models import LearningSession, MapQuestion, Subject
from routes.api import learner_api

# --- Adaptive placement (staircase) tuning -------------------------------
# Start mid-low so beginners reach their floor fast while advanced learners
# only need a few rises. CONFIRM and FLOOR_MISSES (helpers/learning/_placement.py
# — the staircase's own tuning) are the corrects needed to climb a level and the
# misses needed to settle at the floor. Every learner answers MIN_QUESTIONS to
# MAX_QUESTIONS questions: no scale settles before its share of MIN_QUESTIONS
# (split evenly across scales), unless its questions run out, and the cap ends
# the test regardless.
START_LEVEL = 2
MIN_QUESTIONS = 10
MAX_QUESTIONS = 20


@learner_api.route("/map/question", methods=["POST"])
def api_map_question():
    """Grade the previous placement question (if any) then serve the next one.

    Combined "grade + pick next" so the frontend always POSTs the same shape:
    the answer to the question it was just shown, or nothing on the very
    first call, which lazily creates the `LearningSession(session_type=
    "placement")` and seeds one adaptive-staircase state per placement scale
    (each subject that has MapQuestions). The climb/settle rules live in helpers.learning
    (apply_map_answer; CONFIRM is its tuning constant) — this route is HTTP
    orchestration only. Grading is skipped when the question was already
    asked (guards a double-submit re-grading the same answer) or its subject
    already settled (a stale/late request must not perturb a decision
    already made). Stops via `_complete_map_test` once every scale has
    settled (none settles before its share of `MIN_QUESTIONS`), the question
    cap (`MAX_QUESTIONS`) is hit, or no unsettled scale has a question left
    to offer.
    """

    user_id = str(current_user.id)
    data = request.get_json() or {}

    map_session = db.session.scalar(
        db.select(LearningSession).filter_by(
            learner_id=current_user.id, session_type="placement"
        )
    )

    if not map_session:
        capture_event(user_id, "map_started")

        subjects_with_questions = db.session.scalars(
            db.select(Subject).join(MapQuestion).distinct()
        ).all()

        if not subjects_with_questions:
            return jsonify({
                "error": "Configuration error",
                "message": "No subjects with placement questions found in database."
            }), 500

        min_answers = math.ceil(MIN_QUESTIONS / len(subjects_with_questions))
        subject_state = {
            s.name: learning.new_scale_state(min(START_LEVEL, learning.subject_max_level(s.id)), min_answers)
            for s in subjects_with_questions
        }
        map_session = LearningSession(
            learner_id=current_user.id,
            session_type="placement",
            subject_state=subject_state,
            asked_ids=[],
            history=[],
            count=0,
        )
        db.session.add(map_session)
        db.session.commit()

    if "id" in data and "selected_answer" in data:
        prev_q = db.session.get(MapQuestion, data["id"])
        if prev_q and prev_q.id not in map_session.asked_ids:
            is_correct = str(data["selected_answer"]).strip().lower() == str(prev_q.answer).strip().lower()
            subject_name = prev_q.subject.name
            level_at_time = prev_q.level
            state = (map_session.subject_state or {}).get(subject_name)

            if state is not None and not state.get("settled"):
                max_level = learning.subject_max_level(prev_q.subject_id)
                learning.apply_map_answer(state, level_at_time, is_correct, max_level)

            map_session.history.append({
                "id": prev_q.id,
                "subject": subject_name,
                "correct": is_correct,
                "level_at_time": level_at_time
            })
            map_session.asked_ids.append(prev_q.id)
            map_session.count = (map_session.count or 0) + 1

            flag_modified(map_session, "subject_state")
            flag_modified(map_session, "history")
            flag_modified(map_session, "asked_ids")
            db.session.commit()

            capture_event(user_id, "map_answer_submitted", {
                "question_id": prev_q.id,
                "subject": subject_name,
                "is_correct": is_correct,
                "level": level_at_time,
                "audio_only": bool(prev_q.audio_only),
            })

    # Check for completion by question cap
    if (map_session.count or 0) >= MAX_QUESTIONS:
        return _complete_map_test(current_user, map_session, "limit_reached")

    # Pick the next question from an unsettled subject (round-robin-ish).
    unsettled = [
        name for name, st in (map_session.subject_state or {}).items()
        if not st.get("settled")
    ]
    random.shuffle(unsettled)

    chosen = None
    for subject_name in unsettled:
        subject_id = learning.get_subject_id(subject_name)
        if not subject_id:
            continue
        max_level = learning.subject_max_level(subject_id)
        q = learning.next_placement_question_for_subject(map_session, subject_name, subject_id, max_level)
        if q:
            chosen = q
            break

    # Selection may have settled subjects — persist that and re-check completion.
    flag_modified(map_session, "subject_state")
    db.session.commit()

    if not chosen:
        return _complete_map_test(current_user, map_session, "converged")

    # A listening question's words are hidden on the page, which keeps them to show if the audio
    # cannot play. It is only one when there is sound to listen to.
    return jsonify({
        "id": chosen.id,
        "content_type": chosen.content_type,
        "audio_only": bool(chosen.audio_only and chosen.question_sound),
        "question_prompt": chosen.question_prompt,
        "question_text": chosen.question_text,
        "options": chosen.options if chosen.content_type == "multiple_choice" else [],
        "question_sound": chosen.question_sound,
        "question_sound_url": audio_url(chosen.question_text) if chosen.question_sound else None,
        "count": map_session.count,
    })

def _complete_map_test(user, map_session, reason):
    """Save one level per placement scale and the completion flags, delete the
    placement session (ADR 0002) and answer with the recommended course and
    topic. `reason` ("converged" | "limit_reached") is analytics-only."""
    # Final per-scale level: the settled level, else (cap reached) the staircase's estimate.
    final_levels = {
        name: learning.placement_estimate(st) for name, st in (map_session.subject_state or {}).items()
    }
    question_count = map_session.count or 0

    user.completed_map_test = True
    user.map_test_deferred = False  # actually taken now — stop reminding
    user.subject_levels = final_levels

    recommendation = get_recommended_start(user)

    # The result is fully captured by completed_map_test + subject_levels; the
    # placement LearningSession was the only history source, so drop it now that
    # the test is done (no duplicate snapshot to drift out of sync).
    db.session.delete(map_session)
    db.session.commit()

    completed_props = {"subject_levels": final_levels, "reason": reason, "question_count": question_count}
    if recommendation:
        completed_props["recommended_course_id"] = recommendation["subject_id"]
        completed_props["recommended_course"] = recommendation["subject"]
        completed_props["placement_scale"] = recommendation["placement_scale"]
        completed_props["recommended_topic_id"] = recommendation["topic_id"]
        completed_props["recommended_topic_level"] = recommendation["topic_level"]
        completed_props["assessed_level"] = recommendation["assessed_level"]
    capture_event(str(user.id), "map_completed", completed_props)

    payload = {"completed": True, "subject_levels": final_levels}
    if recommendation:
        recommendation = dict(recommendation)
        recommendation["topic_url"] = url_for(
            "learner.learner_topic_lessons", topic_id=recommendation["topic_id"]
        )
        payload["recommended_start"] = recommendation
    return jsonify(payload)

@learner_api.route('/skip-map-test', methods=['POST'])
def skip_map_test():
    """Deliberate feature, not a bypass: learners may defer the placement test.

    The map test exists to recommend a starting level. When skipped/delayed we
    leave subject_levels empty rather than inventing a level — downstream code
    treats a missing level as "no recommendation yet", and the learner can be
    re-assessed later.

    completed_map_test is the dashboard gate, so it must go True or the learner
    is stuck on the intro screen; map_test_deferred records that this was a
    deferral, which is what keeps the dashboard reminder visible and /map-intro
    reachable. Cleared in _complete_map_test once the test is really finished.
    """
    current_user.completed_map_test = True
    current_user.map_test_deferred = True
    # No invented level — empty dict = "not assessed yet / no recommendation".
    current_user.subject_levels = {}
    db.session.commit()
    capture_event(str(current_user.id), "map_skipped", properties={"mode": "user_choice"})
    return jsonify({'status': 'success'})

"""`/api` endpoints. Rate limit: 60/min. All login-required.

Layout:
  lessons.py        a lesson's run for the quiz and every game: questions, grading
                     one answer or Match Up pair, completion          (learner_api)
  map_test.py       placement test — map/question, skip-map-test        (learner_api)
  garden.py         persistent Garden Grow state + cosmetic item equip  (learner_api)
  matching.py       teacher-triggered Hungarian matching run
  announcements.py  feature announcement popup dismissal

`learner_api` is a blueprint nested in `api_bp` (same `/api` prefix, endpoints
`api.learner.<name>`) holding every learner-only route, so the role check and the
onboarding gate run once in its `before_request` instead of on each route.

Submodules are imported at the bottom of this file so their route decorators
register at import time; each does `from routes.api import api_bp` (or
`learner_api`), which works because both already exist by then.
"""

from flask import Blueprint, jsonify, request

from extensions import limiter, login_manager
from helpers.current_user import current_learner as current_user

api_bp = Blueprint("api", __name__, url_prefix="/api")
limiter.limit("60 per minute")(api_bp)

learner_api = Blueprint("learner", __name__)
limiter.limit("60 per minute")(learner_api)

#: The placement test's own calls: open once the survey is done, before the test is.
PLACEMENT_ENDPOINTS = {"api.learner.api_map_question", "api.learner.skip_map_test"}


@learner_api.before_request
def gate_learners():
    """Signed-in learners only, and only once onboarding has reached the call (JSON, never a redirect).

    The JSON twin of the learner pages' gate (`routes.learner.gate_learners`): 403 for another
    role, and `onboarding_incomplete` until the survey is done — and, except for the placement
    test's own calls, until the placement test is taken or deferred.
    """
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    if current_user.user_type != "learner":
        return jsonify({"error": "Unauthorized"}), 403
    step = current_user.onboarding_step
    if step == "survey" or (step == "placement" and request.endpoint not in PLACEMENT_ENDPOINTS):
        return jsonify({"error": "onboarding_incomplete"}), 403
    return None


from routes.api import (  # noqa: F401
    announcements,
    garden,
    lessons,
    map_test,
    matching,
)

api_bp.register_blueprint(learner_api)

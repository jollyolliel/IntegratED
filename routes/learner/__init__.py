"""Learner blueprint.

Layout:
  _dashboard.py      dashboard, survey, map-test onboarding screens
  _learning_path.py  subjects/topics/lessons browsing, overview, quiz launch
  _games.py          the 5 minigame launch routes (rocket, word storm,
                      match up, garden grow, potion workshop)
  _worksheets.py      worksheet view/file/complete

`learner_bp` is created here first; each submodule does `from routes.learner
import learner_bp` and that succeeds even though this module is still
initializing, because `learner_bp` is already bound in `routes.learner`'s
namespace by the time the bottom-of-file imports run.
"""

from flask import Blueprint, abort, redirect, request, url_for
from flask_login import login_required

from extensions import limiter
from helpers.current_user import current_learner as current_user

learner_bp = Blueprint("learner", __name__, url_prefix="/learner")
limiter.limit("120 per minute")(learner_bp)


#: Where each unfinished onboarding step is done. Past the survey goes to /map-intro, never back
#: to the survey: its re-submit returns to the dashboard, which would loop.
_STEP_PAGES = {"survey": "learner.learner_survey", "placement": "learner.learner_map_intro"}
#: Onboarding's own pages, open while it is unfinished (each sends a learner who is too early on).
ONBOARDING_ENDPOINTS = {"learner.learner_survey", "learner.learner_map_intro", "learner.learner_map"}


@learner_bp.before_request
@login_required
def gate_learners():
    """Learners only; every page but onboarding's own waits for the survey, then the placement test."""
    if current_user.user_type != "learner":
        abort(403)
    step = current_user.onboarding_step
    if step and request.endpoint not in ONBOARDING_ENDPOINTS:
        return redirect(url_for(_STEP_PAGES[step]))
    return None


# Imported at the bottom so each submodule's `@learner_bp.route(...)`
# decorators run and register against the already-created `learner_bp`.
from routes.learner import (  # noqa: F401
    _dashboard,
    _games,
    _learning_path,
    _worksheets,
)

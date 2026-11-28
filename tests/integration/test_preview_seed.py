"""The preview's data: the same on every boot, built on the PR's own migrations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from helpers.preview.personas import PERSONAS
from helpers.preview.seed import SIZES, find_persona, seed_preview
from settings import REFUSED_IN_PREVIEW

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def _snapshot():
    from extensions import db
    from models import Learner, Volunteer

    learners = db.session.scalars(db.select(Learner).order_by(Learner.username)).all()
    volunteers = db.session.scalars(db.select(Volunteer).order_by(Volunteer.email)).all()
    return (
        [(l.username, l.name, l.survey_data, l.is_matched, l.xp) for l in learners],
        [(v.email, v.name, v.survey_data, v.match_capacity) for v in volunteers],
    )


def test_seeding_twice_gives_the_same_data(preview_app):
    with preview_app.app_context():
        seed_preview("small")
        first = _snapshot()
        seed_preview("small")
        assert _snapshot() == first


def test_the_personas_are_in_the_states_their_names_promise(preview_app):
    with preview_app.app_context():
        seed_preview("small")
        people = {persona.slug: find_persona(persona.slug) for persona in PERSONAS}

        assert all(people.values())
        assert people["learner-new"].onboarding_step == "placement"
        midpath = people["learner-midpath"]
        assert midpath.onboarding_step is None
        assert midpath.completed_topic_ids and midpath.completed_lesson_ids and midpath.xp > 0
        assert people["learner-matched"].volunteer_match == people["volunteer"]
        teacher = people["teacher"]
        for slug in ("learner-new", "learner-midpath", "learner-matched", "volunteer"):
            assert people[slug].teacher_id == teacher.id
        assert people["school-admin"].school_id == teacher.school_id
        assert people["admin"].user_type == "administrator"


def test_an_unknown_slug_finds_nobody(preview_app):
    with preview_app.app_context():
        assert find_persona("1") is None


def test_the_matcher_has_work_to_do(preview_app):
    """Timing a new matching algorithm needs unmatched learners and free volunteer slots."""
    from helpers.ai.tools import ToolContext
    from helpers.ai.tools.domain import preview_auto_match

    with preview_app.app_context():
        seed_preview("small")
        result = preview_auto_match(ToolContext(teacher=find_persona("teacher"), conversation_id=0))

        assert len(result["proposals"]) >= 5


def test_the_sample_curriculum_and_worksheets_are_there(preview_app):
    from extensions import db
    from helpers.storage import get_bucket
    from models import Question, Worksheet

    with preview_app.app_context():
        seed_preview("small")
        assert db.session.scalar(db.select(db.func.count()).select_from(Question)) > 0
        worksheets = db.session.scalars(db.select(Worksheet)).all()
        assert worksheets
        assert all(w.content or get_bucket().exists(w.filepath) for w in worksheets)


def test_large_is_sized_for_matching():
    assert SIZES["large"]["learners"] >= 1000
    assert set(SIZES) == {"small", "large"}


def test_an_unknown_size_is_refused(preview_app):
    with preview_app.app_context(), pytest.raises(ValueError, match="size"):
        seed_preview("huge")


def test_seeding_refuses_outside_preview(app, db_session, school):
    from models import School

    with pytest.raises(RuntimeError, match="preview"):
        seed_preview("small")

    assert db_session.scalar(db_session.query(School).statement) is not None


def test_a_preview_boots_from_an_empty_folder_through_the_real_commands(tmp_path):
    """What entrypoint-preview.sh runs: the PR's migrations, then the seed."""
    environ = {
        key: value for key, value in os.environ.items()
        if key not in {"GOOGLE_CLIENT_ID", "TEST_DATABASE_URL", "K_SERVICE"}
    }
    # Blank, not absent: main.py loads .env, which must not hand a developer's keys to this boot.
    environ.update(dict.fromkeys(REFUSED_IN_PREVIEW, ""), APP_ENV="preview", PREVIEW_DATA_DIR=str(tmp_path))

    for command in (["db", "upgrade"], ["seed-preview"]):
        result = subprocess.run(
            [sys.executable, "-m", "flask", "--app", "main", *command],
            cwd=ROOT, env=environ, capture_output=True, text=True, timeout=180, check=False,
        )
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-4000:]

    assert (tmp_path / "site.db").is_file()

import pytest
from sqlalchemy import func, select

from tests.support.app import use_environment

pytestmark = pytest.mark.integration


def _content(app, monkeypatch, *, questions="[]", announcements="[]"):
    """Give the app a bucket whose `content/` holds these files."""
    from tests.support.storage import FakeBucket

    storage = FakeBucket()
    storage.write_key("content/questions.json", questions)
    storage.write_key("content/announcements.json", announcements)
    monkeypatch.setitem(app.config, "BUCKET", storage)
    return storage


def test_init_db_cli_command_reports_success(app, isolated_database):
    result = app.test_cli_runner().invoke(args=["init-db"])

    assert result.exit_code == 0
    assert "Initialized the database" in result.output


def test_teacher_assignment_cli_dry_run_does_not_mutate_records(
    app, db_session, school, teacher
):
    from tests.support.factories import make_learner

    learner = make_learner(db_session, school, teacher=None, username="unassigned")
    result = app.test_cli_runner().invoke(args=["fix-teacher-assignments", "--dry-run"])

    assert result.exit_code == 0
    db_session.refresh(learner)
    assert learner.teacher_id is None
    assert "DRY RUN" in result.output


def test_diagnose_teacher_reports_the_roster(app, db_session, school, teacher):
    from tests.support.factories import make_learner, make_volunteer

    make_learner(db_session, school, teacher, name="Ada")
    make_volunteer(db_session, school, teacher, name="Bo")

    result = app.test_cli_runner().invoke(args=["diagnose-teacher"])

    assert result.exit_code == 0
    assert "=== Teachers (1) ===" in result.output
    assert "Ada" in result.output
    assert "Bo" in result.output


def test_diagnose_teacher_survives_an_empty_database(app, db_session):
    result = app.test_cli_runner().invoke(args=["diagnose-teacher"])

    assert result.exit_code == 0
    assert "=== Teachers (0) ===" in result.output


def test_fix_teacher_assignments_claims_unassigned_people(app, db_session, school, teacher):
    """With one teacher in the system, they take every unassigned person."""

    from tests.support.factories import make_learner

    learner = make_learner(db_session, school, teacher=None, username="unassigned")

    result = app.test_cli_runner().invoke(args=["fix-teacher-assignments"])

    assert result.exit_code == 0
    db_session.refresh(learner)
    assert learner.teacher_id == teacher.id


def test_fix_teacher_assignments_reports_when_there_are_no_teachers(app, db_session):
    result = app.test_cli_runner().invoke(args=["fix-teacher-assignments"])

    assert result.exit_code == 0
    assert "No teachers found" in result.output


def test_fix_teacher_assignments_matches_by_school_with_several_teachers(
    app, db_session, school, teacher
):
    from tests.support.factories import make_learner, make_school, make_teacher

    other_school = make_school(db_session)
    make_teacher(db_session, other_school)
    mine = make_learner(db_session, school, teacher=None, username="mine")

    result = app.test_cli_runner().invoke(args=["fix-teacher-assignments"])

    assert result.exit_code == 0
    assert "Matching by school_id" in result.output
    db_session.refresh(mine)
    assert mine.teacher_id == teacher.id


def test_sync_sequences_is_a_no_op_on_sqlite(app, db_session):
    """Dev is SQLite, prod is Postgres — this must not explode on either."""

    result = app.test_cli_runner().invoke(args=["sync-sequences"])

    assert result.exit_code == 0
    assert "Not PostgreSQL" in result.output


def test_backup_db_is_a_no_op_outside_production(app, db_session, monkeypatch):
    use_environment(app, monkeypatch, "development")

    result = app.test_cli_runner().invoke(args=["backup-db"])

    assert result.exit_code == 0


def test_sync_announcements_reports_what_it_inserted(app, db_session, monkeypatch, tmp_path):
    import json

    from models import FeatureAnnouncement

    source = tmp_path / "announcements.json"
    source.write_text(
        json.dumps([{"uid": "cli-thing", "roles": ["learner"]}]), encoding="utf-8"
    )
    _content(app, monkeypatch, announcements=source.read_text(encoding="utf-8"))

    result = app.test_cli_runner().invoke(args=["sync-announcements"])

    assert result.exit_code == 0
    assert "cli-thing" in result.output
    assert db_session.scalar(select(func.count()).select_from(FeatureAnnouncement).filter_by(uid="cli-thing")) == 1


def test_sync_announcements_reports_none_when_nothing_is_new(app, db_session, monkeypatch, tmp_path):

    _content(app, monkeypatch, announcements="[]")

    result = app.test_cli_runner().invoke(args=["sync-announcements"])

    assert result.exit_code == 0
    assert "none" in result.output


def test_import_questions_loads_a_question_file(app, isolated_database, monkeypatch, tmp_path):
    import json

    from models import Question

    payload = [
        {
            "name": "English Grammar",
            "icon": "fa-book",
            "description": "Grammar",
            "topics": [
                {
                    "title": "Basics",
                    "icon": "fa-star",
                    "level": 1,
                    "description": "Basic grammar",
                    "overview_markdown": "# Basics",
                    "lessons": [
                        {
                            "title": "Nouns",
                            "icon": "fa-book",
                            "description": "Nouns",
                            "overview_markdown": "# Nouns",
                            "questions": [
                                {
                                    "content_type": "multiple_choice",
                                    "question_prompt": "Pick one",
                                    "question_text": "Is cat a noun?",
                                    "options": ["yes", "no"],
                                    "answer": "yes",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    _content(app, monkeypatch, questions=json.dumps(payload))

    result = app.test_cli_runner().invoke(args=["import-questions"])

    assert result.exit_code == 0, result.output
    assert isolated_database.session.scalar(select(func.count()).select_from(Question)) >= 1


def _matched_pair(db_session, school, teacher):
    from tests.support.factories import make_learner, make_volunteer

    volunteer = make_volunteer(db_session, school, teacher)
    learner = make_learner(db_session, school, teacher, volunteer_id=volunteer.id, is_matched=True)
    volunteer.is_matched = True
    db_session.commit()
    return learner, volunteer


def test_unmatch_all_dissolves_every_match(app, db_session, school, teacher):
    learner, volunteer = _matched_pair(db_session, school, teacher)

    result = app.test_cli_runner().invoke(args=["unmatch-all", "--yes"])

    assert result.exit_code == 0
    assert "Unmatched 1 learner(s)" in result.output
    db_session.refresh(learner)
    db_session.refresh(volunteer)
    assert learner.volunteer_id is None
    assert learner.is_matched is False
    assert volunteer.is_matched is False


def test_unmatch_all_aborts_without_confirmation(app, db_session, school, teacher):
    learner, _ = _matched_pair(db_session, school, teacher)

    result = app.test_cli_runner().invoke(args=["unmatch-all"], input="n\n")

    assert result.exit_code != 0
    db_session.refresh(learner)
    assert learner.volunteer_id is not None


def test_unmatch_all_reports_when_nothing_is_matched(app, db_session):
    result = app.test_cli_runner().invoke(args=["unmatch-all", "--yes"])

    assert result.exit_code == 0
    assert "No matches" in result.output


def test_unmatch_all_refuses_on_non_sqlite_database(app, db_session, school, teacher, monkeypatch):
    learner, _ = _matched_pair(db_session, school, teacher)
    monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", "postgresql://user:pw@host/db")

    result = app.test_cli_runner().invoke(args=["unmatch-all", "--yes"])

    assert "Refusing" in result.output
    db_session.refresh(learner)
    assert learner.volunteer_id is not None


def test_seed_cli_command_loads_seed_toml_and_is_safe_to_repeat(app, db_session):
    from models import Administrator, School

    runner = app.test_cli_runner()
    first = runner.invoke(args=["seed"])
    second = runner.invoke(args=["seed"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Seeded from seed/seed.toml" in first.output
    assert db_session.scalar(select(func.count()).select_from(School)) == 1
    assert db_session.scalar(select(func.count()).select_from(Administrator)) == 1


def test_seed_cli_command_refuses_outside_development(app, db_session, monkeypatch):
    use_environment(app, monkeypatch, "production")

    result = app.test_cli_runner().invoke(args=["seed"])

    assert result.exit_code != 0
    assert "Seeding is for development" in result.output


def test_content_commands_explain_a_bucket_without_content(app, db_session, monkeypatch):
    from tests.support.storage import FakeBucket

    monkeypatch.setitem(app.config, "BUCKET", FakeBucket())

    result = app.test_cli_runner().invoke(args=["import-questions"])

    assert result.exit_code != 0
    assert "content/questions.json" in result.output


def test_seed_cli_audio_flag_needs_tts_enabled(app, db_session):
    result = app.test_cli_runner().invoke(args=["seed", "--audio"])

    assert result.exit_code != 0
    assert "TTS_ENABLED" in result.output
